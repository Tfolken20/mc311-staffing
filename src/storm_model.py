"""Storm-specific staffing: how big should the surge actually be?

WHAT THE SURGE ANALYSIS FOUND

Triggering a surge on snow works -- it beats every fixed quantile on cost. But
the surge is too SMALL. On the 68 snow days, staffing to the 95th percentile
still left a mean shortfall of 299 contacts (5.4 agents) and covered only 66%
of them.

The reason is structural. A quantile estimated from the whole residual
distribution describes ORDINARY variation: its 95th percentile is about 1.2x
the point forecast. Storm days are not ordinary -- Winter Storm Jonas ran 2.6x.
Asking the 95th percentile of normal days to cover a 2.6x event is asking the
wrong distribution.

THE FIX: condition on the event. Estimate the volume ratio from PRIOR STORMS,
not from all days, and staff to a quantile of that conditional distribution.

SAMPLE SIZE IS THE BINDING CONSTRAINT. There are 68 triggered days in twelve
years. Any estimator fit on that must be nearly parameter-free or it will fit
noise. This uses a trailing quantile of prior storm ratios, optionally split by
accumulation band -- no regression, no tuning. Days before enough prior storms
have accumulated fall back to the fixed-quantile policy, so the walk-forward
never borrows from the future.

UPPER BOUND CAVEAT: observed weather is used, so this measures the value of a
perfect forecast. Snow of this magnitude is forecast with high skill at 24-48
hours, but the number here is a ceiling.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

CONTACTS_PER_AGENT_DAY = 55
COST_OVER_AGENT_DAY = 21.53 * 1.35 * 8.0
COST_PER_CONTACT = 4.15
UNDER_MULTIPLIER = 2.5

SNOW_WINDOW = "snow_sum5d"
SNOW_TRIGGER = 4.0
COLD_TRIGGER = 20.0
MIN_PRIOR_STORMS = 8          # before the conditional estimate is trusted
STORM_QUANTILES = [0.50, 0.70, 0.80, 0.90]
SENSITIVITY = [1.5, 2.0, 2.5, 3.0, 4.0, 6.0]


def c_over_per_contact():
    return COST_OVER_AGENT_DAY / CONTACTS_PER_AGENT_DAY


def policy_cost(actual, staffed, multiplier=UNDER_MULTIPLIER):
    over = np.maximum(staffed - actual, 0) * c_over_per_contact()
    under = np.maximum(actual - staffed, 0) * COST_PER_CONTACT * multiplier
    return over + under


def summarize(ev, staffed, name, multiplier=UNDER_MULTIPLIER):
    a = ev["contacts"].to_numpy()
    s = np.asarray(staffed, dtype=float)
    cost = policy_cost(a, s, multiplier)
    short = np.maximum(a - s, 0)
    trig = ev["snow_trigger"].to_numpy()
    return {
        "policy": name,
        "annual_cost": round(cost.mean() * 250, 0),
        "pct_days_short": round((short > 0).mean(), 3),
        "contacts_missed_yr": round(short.mean() * 250, 0),
        "storm_coverage": round((a[trig] <= s[trig]).mean(), 3) if trig.sum() else np.nan,
        "storm_shortfall": round(short[trig].mean(), 0) if trig.sum() else np.nan,
    }


def storm_multipliers(ev, q):
    """For each triggered day, the q-th quantile of PRIOR storm-day ratios.

    Split by accumulation band once enough prior storms exist in that band,
    otherwise pooled across all prior storms. NaN where there is insufficient
    history -- the caller falls back to the fixed-quantile policy there.
    """
    out = np.full(len(ev), np.nan)
    hist_ratio, hist_snow = [], []

    for i, r in enumerate(ev.itertuples(index=False)):
        if getattr(r, "snow_trigger"):
            if len(hist_ratio) >= MIN_PRIOR_STORMS:
                hr = np.array(hist_ratio)
                hs = np.array(hist_snow)
                # Same accumulation band, if there is enough of it.
                heavy = getattr(r, SNOW_WINDOW) >= 8.0
                band = hr[hs >= 8.0] if heavy else hr[hs < 8.0]
                use = band if len(band) >= MIN_PRIOR_STORMS else hr
                out[i] = np.quantile(use, q)

        # State update AFTER the row is scored -- never uses its own outcome.
        if getattr(r, "snow_trigger"):
            hist_ratio.append(r.ratio)
            hist_snow.append(getattr(r, SNOW_WINDOW))

    return out


def main():
    ev = pd.read_parquet(PROC / "calls_with_weather.parquet")
    ev = ev[ev[SNOW_WINDOW].notna()].sort_values("day").reset_index(drop=True)
    ev["snow_trigger"] = ev[SNOW_WINDOW] >= SNOW_TRIGGER
    ev["cold_trigger"] = ev["temperature_2m_min"] < COLD_TRIGGER

    n_trig = int(ev["snow_trigger"].sum())
    print(f"evaluation days: {len(ev):,}   snow-triggered: {n_trig}", flush=True)

    # What do storm days actually look like?
    st = ev[ev["snow_trigger"]]
    print("\nSTORM-DAY VOLUME RATIOS (the conditional distribution)", flush=True)
    print(f"  n={len(st)}  mean {st['ratio'].mean():.3f}  "
          f"median {st['ratio'].median():.3f}", flush=True)
    print("  quantiles: " + "  ".join(
        f"q{int(q*100)}={st['ratio'].quantile(q):.3f}"
        for q in (0.5, 0.7, 0.8, 0.9, 0.95)), flush=True)
    print("\n  for comparison, ALL days:", flush=True)
    print("  quantiles: " + "  ".join(
        f"q{int(q*100)}={ev['ratio'].quantile(q):.3f}"
        for q in (0.5, 0.7, 0.8, 0.9, 0.95)), flush=True)
    print("\n  by accumulation band:", flush=True)
    st_band = st.copy()
    st_band["band"] = np.where(st_band[SNOW_WINDOW] >= 8.0, "8+ in", "4-8 in")
    print(st_band.groupby("band")["ratio"].agg(
        n="size", mean="mean", median="median",
        q80=lambda s: s.quantile(0.80)).round(3).to_string(), flush=True)

    # ---- policies ----
    policies = {
        "fixed q70": ev["fq70"].to_numpy(),
        "fixed q80": ev["fq80"].to_numpy(),
        "fixed q90": ev["fq90"].to_numpy(),
        "surge to q95 on snow": np.where(ev["snow_trigger"], ev["fq95"], ev["fq70"]),
    }

    for q in STORM_QUANTILES:
        mult = storm_multipliers(ev, q)
        staffed = np.where(
            ev["snow_trigger"] & ~np.isnan(mult),
            ev["f_dow_med"].to_numpy() * np.nan_to_num(mult, nan=1.0),
            np.where(ev["cold_trigger"], ev["fq80"], ev["fq70"]),
        )
        policies[f"storm model, q{int(q * 100)} of prior storms"] = staffed

    rows = [summarize(ev, v, k) for k, v in policies.items()]
    res = pd.DataFrame(rows)
    base = res.loc[res["policy"] == "fixed q70", "annual_cost"].iloc[0]
    res["vs_q70"] = (res["annual_cost"] - base).round(0)

    print(f"\nPOLICY COMPARISON at C_under/C_over = {UNDER_MULTIPLIER}", flush=True)
    print(res.to_string(index=False), flush=True)

    best = res.nsmallest(1, "annual_cost")
    print(f"\n  cheapest: {best['policy'].iloc[0]}  "
          f"(${-best['vs_q70'].iloc[0]:,.0f} vs fixed q70)", flush=True)

    # ---- how many prior storms were available? ----
    mult80 = storm_multipliers(ev, 0.80)
    have = (~np.isnan(mult80)) & ev["snow_trigger"].to_numpy()
    print(f"\n  storm days with enough prior history to model: "
          f"{have.sum()} of {n_trig}", flush=True)
    print(f"  (the rest fall back to the fixed-quantile policy)", flush=True)

    # ---- sensitivity ----
    print("\nSENSITIVITY TO THE COST RATIO", flush=True)
    rows = []
    for m in SENSITIVITY:
        costs = {k: policy_cost(ev["contacts"].to_numpy(),
                                np.asarray(v, dtype=float), m).mean() * 250
                 for k, v in policies.items()}
        b = min(costs, key=costs.get)
        rows.append({
            "under/over": m,
            "best_policy": b,
            "best_annual": round(costs[b], 0),
            "q70_annual": round(costs["fixed q70"], 0),
            "saving": round(costs["fixed q70"] - costs[b], 0),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    ev.to_parquet(PROC / "storm_model_eval.parquet", index=False)
    print(f"\nsaved: {PROC / 'storm_model_eval.parquet'}", flush=True)


if __name__ == "__main__":
    main()