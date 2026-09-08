"""Does a weather-triggered surge policy beat a fixed quantile?

WHAT THE DIAGNOSTIC ESTABLISHED

  - Same-day snow correlates NEGATIVELY with volume (-0.03). During the storm
    the county is closed and nobody calls.
  - Correlation rises monotonically with the accumulation window: 2d 0.11,
    3d 0.21, 5d 0.32, 7d 0.35. Demand is DEFERRED into the reopening and stays
    elevated for most of a week.
  - The response has a threshold near 4 inches. Below it, ratios sit at 1.00-1.04
    -- indistinguishable from an ordinary day. At 4-8 inches the mean ratio is
    1.17; above 8 inches it is 1.67.
  - 40.6% of the top 1% of days follow 1+ inch within three days, against a
    3.7% base rate -- an 11x lift.
  - Cold days (min below 20F) run 1.135, an independent effect from snow.

POLICIES COMPARED

  fixed q70        the current recommendation
  fixed q80/q90    buy tail coverage with permanent headcount
  surge            q70 normally, higher quantile only when weather triggers

The surge policy is the interesting one: it buys tail coverage only on the days
that need it, instead of carrying idle capacity all year.

UPPER BOUND CAVEAT: this uses OBSERVED weather, so it measures the value of a
PERFECT forecast. A real deployment would use an NWS forecast issued the
afternoon before. Snow events of this magnitude are forecast with high skill at
24-48 hours, so the degradation should be modest -- but it is real, and this
result is a ceiling, not a delivered number.
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

SNOW_TRIGGER = 4.0        # inches accumulated over the trailing window
SNOW_WINDOW = "snow_sum5d"
COLD_TRIGGER = 20.0       # min temperature, F
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
    return {
        "policy": name,
        "mean_staffed": round(s.mean(), 0),
        "annual_cost": round(cost.mean() * 250, 0),
        "pct_days_short": round((short > 0).mean(), 3),
        "contacts_missed_yr": round(short.mean() * 250, 0),
        "tail_coverage": round(
            (a[a >= np.quantile(a, 0.95)]
             <= s[a >= np.quantile(a, 0.95)]).mean(), 3),
    }


def main():
    ev = pd.read_parquet(PROC / "calls_with_weather.parquet")
    ev = ev[ev[SNOW_WINDOW].notna()].copy()
    print(f"evaluation days: {len(ev):,} "
          f"({ev['day'].min().date()} to {ev['day'].max().date()})\n", flush=True)

    ev["snow_trigger"] = ev[SNOW_WINDOW] >= SNOW_TRIGGER
    ev["cold_trigger"] = ev["temperature_2m_min"] < COLD_TRIGGER
    ev["any_trigger"] = ev["snow_trigger"] | ev["cold_trigger"]

    print("TRIGGER FREQUENCY", flush=True)
    for c in ("snow_trigger", "cold_trigger", "any_trigger"):
        n = ev[c].sum()
        print(f"  {c:14s} {n:4d} days ({n / len(ev):.1%})  "
              f"mean ratio {ev.loc[ev[c], 'ratio'].mean():.3f}", flush=True)
    print(f"  {'no trigger':14s} {(~ev['any_trigger']).sum():4d} days  "
          f"mean ratio {ev.loc[~ev['any_trigger'], 'ratio'].mean():.3f}\n",
          flush=True)

    # ---- policies ----
    fixed = {
        "fixed q70 (current rec)": ev["fq70"],
        "fixed q80": ev["fq80"],
        "fixed q90": ev["fq90"],
        "fixed q95": ev["fq95"],
    }
    surge = {
        "surge: q70 -> q90 on snow": np.where(ev["snow_trigger"], ev["fq90"], ev["fq70"]),
        "surge: q70 -> q95 on snow": np.where(ev["snow_trigger"], ev["fq95"], ev["fq70"]),
        "surge: q70 -> q90 on snow or cold": np.where(ev["any_trigger"],
                                                      ev["fq90"], ev["fq70"]),
        "surge: q70 -> q95 on snow, q80 on cold": np.where(
            ev["snow_trigger"], ev["fq95"],
            np.where(ev["cold_trigger"], ev["fq80"], ev["fq70"])),
    }

    rows = [summarize(ev, v, k) for k, v in {**fixed, **surge}.items()]
    res = pd.DataFrame(rows)
    base = res.loc[res["policy"] == "fixed q70 (current rec)", "annual_cost"].iloc[0]
    res["vs_q70"] = (res["annual_cost"] - base).round(0)

    print(f"POLICY COMPARISON at C_under/C_over = {UNDER_MULTIPLIER}", flush=True)
    print(res.to_string(index=False), flush=True)

    best = res.nsmallest(1, "annual_cost")
    print(f"\n  cheapest: {best['policy'].iloc[0]}  "
          f"(${-best['vs_q70'].iloc[0]:,.0f} vs fixed q70)", flush=True)

    # ---- how the surge performs on trigger days specifically ----
    print("\nPERFORMANCE ON TRIGGERED DAYS ONLY", flush=True)
    trig = ev[ev["snow_trigger"]]
    if len(trig):
        for label, col in (("q70", "fq70"), ("q90", "fq90"), ("q95", "fq95")):
            s = np.maximum(trig["contacts"] - trig[col], 0)
            print(f"  {label}: covered {(trig['contacts'] <= trig[col]).mean():.1%} "
                  f"of {len(trig)} snow days, mean shortfall "
                  f"{s.mean():.0f} contacts "
                  f"({s.mean() / CONTACTS_PER_AGENT_DAY:.1f} agents)", flush=True)

    # ---- cost of the surge itself ----
    print("\nWHAT THE SURGE COSTS", flush=True)
    n_trig = int(ev["snow_trigger"].sum())
    extra = (ev.loc[ev["snow_trigger"], "fq95"]
             - ev.loc[ev["snow_trigger"], "fq70"]).mean()
    print(f"  snow triggers fire {n_trig} times in {len(ev):,} days "
          f"({n_trig / len(ev) * 250:.1f} days per year)", flush=True)
    print(f"  extra capacity when triggered: {extra:.0f} contacts "
          f"({extra / CONTACTS_PER_AGENT_DAY:.1f} agents)", flush=True)

    # ---- sensitivity ----
    print("\nSENSITIVITY TO THE COST RATIO", flush=True)
    rows = []
    for m in SENSITIVITY:
        costs = {k: policy_cost(ev["contacts"].to_numpy(),
                                np.asarray(v, dtype=float), m).mean() * 250
                 for k, v in {**fixed, **surge}.items()}
        b = min(costs, key=costs.get)
        rows.append({
            "under/over": m,
            "best_policy": b,
            "best_annual": round(costs[b], 0),
            "q70_annual": round(costs["fixed q70 (current rec)"], 0),
            "saving": round(costs["fixed q70 (current rec)"] - costs[b], 0),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    ev.to_parquet(PROC / "weather_policy_eval.parquet", index=False)
    print(f"\nsaved: {PROC / 'weather_policy_eval.parquet'}", flush=True)


if __name__ == "__main__":
    main()