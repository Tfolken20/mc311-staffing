"""Quantile forecasting and the staffing decision.

THE ARGUMENT

A forecast optimized for average accuracy is the wrong input to a staffing
decision, because the costs of being wrong are not symmetric. Idle agents cost
wages. Insufficient agents cost abandoned contacts, callbacks, and service
failure. When those costs differ, the optimal staffing level is not the mean
of the demand distribution -- it is a QUANTILE of it:

    optimal quantile = C_under / (C_under + C_over)

The baseline analysis established the concrete problem: on the top 5% of days,
the best point forecast under-forecasts by an average of 436 contacts, and its
error triples from 147 to 437. That bias is structural, not incidental -- every
smoothed central estimate is low on spikes by construction.

COST ANCHORS (both published, both varied in sensitivity below)

  C_over  -- BLS reports the median hourly wage for customer service
             representatives at $21.53 (May 2025). A 1.35x fully-loaded
             multiplier for benefits and overhead gives ~$29/hour, or ~$232
             per idle agent-day at 8 hours.

  C_under -- Industry benchmark cost per call is $2.70-$5.60 (analysis of 18
             large companies, 900K-9M annual call volume); midpoint $4.15. An
             unhandled contact is not merely a wasted one -- it becomes a
             callback plus a service failure -- so its cost is at least one
             contact's cost and plausibly several times more.

  Base case ratio C_under/C_over = 2.5, implying a target quantile of 0.71.
  The ratio is the number a manager would argue with, so the recommendation is
  reported across a range of it.

EVALUATION is rolling-origin: quantiles are estimated from trailing residuals
available before the forecast day. Nothing uses future information.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

# --- cost parameters ---
HOURLY_WAGE = 21.53          # BLS median, CSR, May 2025
LOADED_MULT = 1.35           # benefits + overhead
SHIFT_HOURS = 8.0
CONTACTS_PER_AGENT_DAY = 55  # handle time + occupancy assumption
COST_PER_CONTACT = 4.15      # industry benchmark midpoint

COST_OVER_AGENT_DAY = HOURLY_WAGE * LOADED_MULT * SHIFT_HOURS
UNDER_MULTIPLIER = 2.5       # base case: unhandled contact costs 2.5x a handled one

RESID_WINDOW = 250           # trailing weekdays for the residual distribution
MIN_HISTORY = 400
SENSITIVITY = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0]


def cost_per_unhandled(multiplier):
    return COST_PER_CONTACT * multiplier


def target_quantile(multiplier):
    """Newsvendor critical ratio, expressed per contact."""
    c_over_per_contact = COST_OVER_AGENT_DAY / CONTACTS_PER_AGENT_DAY
    c_under_per_contact = cost_per_unhandled(multiplier)
    return c_under_per_contact / (c_under_per_contact + c_over_per_contact)


def add_quantiles(d, base_col="f_dow_med"):
    """Trailing residual quantiles, applied multiplicatively to the point forecast.

    Residuals are computed as ratios rather than differences because error
    scales with volume: a 200-contact miss on a 2,400-contact Monday is not
    the same as on a 1,500-contact Friday.
    """
    d = d.copy()
    d["ratio"] = d["contacts"] / d[base_col]

    for q in (0.50, 0.60, 0.70, 0.71, 0.75, 0.80, 0.85, 0.90, 0.95):
        d[f"r_q{int(q * 100)}"] = (
            d["ratio"].shift(1)
            .rolling(RESID_WINDOW, min_periods=60)
            .quantile(q)
        )
        d[f"fq{int(q * 100)}"] = d[base_col] * d[f"r_q{int(q * 100)}"]
    return d


def pinball(actual, pred, q):
    e = actual - pred
    return np.mean(np.maximum(q * e, (q - 1) * e))


def policy_cost(actual, staffed_contacts, multiplier):
    """Daily cost of a staffing policy expressed in contact-equivalents."""
    c_over_per_contact = COST_OVER_AGENT_DAY / CONTACTS_PER_AGENT_DAY
    over = np.maximum(staffed_contacts - actual, 0) * c_over_per_contact
    under = np.maximum(actual - staffed_contacts, 0) * cost_per_unhandled(multiplier)
    return over + under


def main():
    d = pd.read_parquet(PROC / "series_with_baselines.parquet")
    d = add_quantiles(d)

    ev = d.iloc[MIN_HISTORY:]
    ev = ev[~ev["is_closure"] & ev["fq50"].notna()].copy()
    print(f"evaluation days: {len(ev):,} "
          f"({ev['day'].min().date()} to {ev['day'].max().date()})", flush=True)
    print(f"mean daily contacts: {ev['contacts'].mean():.0f}\n", flush=True)

    q_star = target_quantile(UNDER_MULTIPLIER)
    print("COST STRUCTURE", flush=True)
    print(f"  idle agent-day:            ${COST_OVER_AGENT_DAY:,.2f}", flush=True)
    print(f"  per contact of capacity:   "
          f"${COST_OVER_AGENT_DAY / CONTACTS_PER_AGENT_DAY:,.2f}", flush=True)
    print(f"  unhandled contact ({UNDER_MULTIPLIER}x):    "
          f"${cost_per_unhandled(UNDER_MULTIPLIER):,.2f}", flush=True)
    print(f"  implied target quantile:   {q_star:.3f}\n", flush=True)

    # ---- 1. does the quantile forecast actually hit its quantile? ----
    print("1. COVERAGE -- does each quantile forecast cover what it claims?", flush=True)
    rows = []
    for q in (50, 60, 70, 75, 80, 85, 90, 95):
        col = f"fq{q}"
        covered = (ev["contacts"] <= ev[col]).mean()
        rows.append({
            "nominal": q / 100,
            "actual_coverage": round(covered, 4),
            "gap": round(covered - q / 100, 4),
            "mean_staffed": round(ev[col].mean(), 0),
            "pinball": round(pinball(ev["contacts"], ev[col], q / 100), 2),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    # ---- 2. cost of each policy at the base-case ratio ----
    print(f"\n2. POLICY COST at C_under/C_over = {UNDER_MULTIPLIER} "
          f"(target quantile {q_star:.2f})", flush=True)
    policies = {
        "point forecast (mean-optimal)": ev["f_dow_med"],
        "quantile 0.70": ev["fq70"],
        "quantile 0.75": ev["fq75"],
        "quantile 0.80": ev["fq80"],
        "quantile 0.90": ev["fq90"],
        "perfect foresight": ev["contacts"],
    }
    rows = []
    for name, staffed in policies.items():
        c = policy_cost(ev["contacts"].to_numpy(), staffed.to_numpy(), UNDER_MULTIPLIER)
        short = np.maximum(ev["contacts"].to_numpy() - staffed.to_numpy(), 0)
        rows.append({
            "policy": name,
            "mean_daily_cost": round(c.mean(), 0),
            "annual_cost": round(c.mean() * 250, 0),
            "days_short": int((short > 0).sum()),
            "pct_days_short": round((short > 0).mean(), 3),
            "contacts_missed_per_yr": round(short.mean() * 250, 0),
        })
    res = pd.DataFrame(rows)
    base = res.loc[res["policy"] == "point forecast (mean-optimal)",
                   "annual_cost"].iloc[0]
    res["vs_point_forecast"] = (res["annual_cost"] - base).round(0)
    print(res.to_string(index=False), flush=True)

    best = res[res["policy"] != "perfect foresight"].nsmallest(1, "annual_cost")
    print(f"\n  cheapest implementable policy: {best['policy'].iloc[0]}", flush=True)
    print(f"  annual saving vs point forecast: "
          f"${-best['vs_point_forecast'].iloc[0]:,.0f}", flush=True)

    # ---- 3. sensitivity to the cost ratio ----
    print("\n3. SENSITIVITY -- the cost ratio is the assumption to argue with", flush=True)
    qcols = [50, 60, 70, 75, 80, 85, 90, 95]
    rows = []
    for m in SENSITIVITY:
        qs = target_quantile(m)
        costs = {q: policy_cost(ev["contacts"].to_numpy(),
                                ev[f"fq{q}"].to_numpy(), m).mean()
                 for q in qcols}
        best_q = min(costs, key=costs.get)
        pt = policy_cost(ev["contacts"].to_numpy(),
                         ev["f_dow_med"].to_numpy(), m).mean()
        rows.append({
            "under/over": m,
            "implied_q": round(qs, 3),
            "best_policy_q": best_q / 100,
            "annual_cost_best": round(costs[best_q] * 250, 0),
            "annual_cost_point": round(pt * 250, 0),
            "annual_saving": round((pt - costs[best_q]) * 250, 0),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    print("\n  If the recommendation is stable across this range, the decision", flush=True)
    print("  does not hinge on getting the cost ratio exactly right.", flush=True)

    ev.to_parquet(PROC / "staffing_evaluation.parquet", index=False)
    print(f"\nsaved: {PROC / 'staffing_evaluation.parquet'}", flush=True)


if __name__ == "__main__":
    main()