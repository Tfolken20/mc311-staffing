"""How bad are the short days, and where is the pain concentrated?

"30.8% of days have some unmet demand" is an alarming sentence and a
misleading one. A day two contacts short and a day 800 contacts short are the
same row in a frequency count and entirely different operational events.

This script answers what an operations manager would actually ask:

  - When we are short, by how much?
  - What share of total unmet demand comes from the worst few days?
  - Which weekdays and which months carry the risk?
  - Would a policy that flexes by weekday beat a single fixed quantile?

The last question matters because Monday averages 2,075 contacts and Friday
1,594 -- a fixed percentile of a fixed point forecast may not distribute risk
sensibly across a week with that much structure.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

CONTACTS_PER_AGENT_DAY = 55
POLICIES = {
    "point forecast": "f_dow_med",
    "quantile 0.70": "fq70",
    "quantile 0.80": "fq80",
    "quantile 0.90": "fq90",
}


def shortfall(ev, col):
    return np.maximum(ev["contacts"] - ev[col], 0)


def main():
    ev = pd.read_parquet(PROC / "staffing_evaluation.parquet")
    print(f"evaluation days: {len(ev):,}\n", flush=True)

    # ---- 1. magnitude when short ----
    print("1. WHEN WE ARE SHORT, BY HOW MUCH?", flush=True)
    rows = []
    for name, col in POLICIES.items():
        s = shortfall(ev, col)
        short_days = s[s > 0]
        rows.append({
            "policy": name,
            "pct_days_short": round((s > 0).mean(), 3),
            "median_shortfall": round(short_days.median(), 0),
            "p90_shortfall": round(short_days.quantile(0.90), 0),
            "max_shortfall": round(short_days.max(), 0),
            "median_agents_short": round(short_days.median() / CONTACTS_PER_AGENT_DAY, 1),
            "p90_agents_short": round(short_days.quantile(0.90) / CONTACTS_PER_AGENT_DAY, 1),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    print("\n  A day short by 40 contacts is under one agent's daily capacity.", flush=True)
    print("  Frequency of shortfall and severity of shortfall are different things.", flush=True)

    # ---- 2. concentration ----
    print("\n2. CONCENTRATION -- where does unmet demand actually come from?", flush=True)
    rows = []
    for name, col in POLICIES.items():
        s = shortfall(ev, col).sort_values(ascending=False)
        total = s.sum()
        if total == 0:
            continue
        n = len(ev)
        rows.append({
            "policy": name,
            "total_missed": round(total, 0),
            "top_1pct_days": round(s.head(max(1, n // 100)).sum() / total, 3),
            "top_5pct_days": round(s.head(max(1, n // 20)).sum() / total, 3),
            "top_10pct_days": round(s.head(max(1, n // 10)).sum() / total, 3),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    print("\n  If most unmet demand is concentrated in a handful of days, the", flush=True)
    print("  answer is a surge plan for those days, not more baseline headcount.", flush=True)

    # ---- 3. where the risk sits ----
    base = "fq70"
    ev = ev.copy()
    ev["short"] = shortfall(ev, base)

    print(f"\n3. RISK BY WEEKDAY (policy: {base})", flush=True)
    by_dow = ev.groupby("dow_name").agg(
        days=("short", "size"),
        mean_volume=("contacts", "mean"),
        pct_short=("short", lambda s: (s > 0).mean()),
        mean_shortfall=("short", "mean"),
        total_missed=("short", "sum"),
    ).round(3)
    by_dow["share_of_missed"] = (by_dow["total_missed"]
                                 / by_dow["total_missed"].sum()).round(3)
    print(by_dow.sort_values("total_missed", ascending=False).to_string(), flush=True)

    print(f"\n4. RISK BY MONTH (policy: {base})", flush=True)
    by_month = ev.groupby("month").agg(
        days=("short", "size"),
        mean_volume=("contacts", "mean"),
        pct_short=("short", lambda s: (s > 0).mean()),
        mean_shortfall=("short", "mean"),
    ).round(3)
    print(by_month.to_string(), flush=True)

    # ---- 5. the worst days ----
    print("\n5. THE TEN WORST DAYS (policy: fq70)", flush=True)
    worst = ev.nlargest(10, "short")[
        ["day", "dow_name", "contacts", "f_dow_med", base, "short"]]
    worst = worst.assign(agents_short=(worst["short"] / CONTACTS_PER_AGENT_DAY).round(1))
    print(worst.round(0).to_string(index=False), flush=True)

    # ---- 6. would a per-weekday quantile do better? ----
    print("\n6. FIXED QUANTILE vs PER-WEEKDAY QUANTILE", flush=True)
    print("   Does one percentile serve every weekday equally well?", flush=True)
    cov = ev.groupby("dow_name").apply(
        lambda g: pd.Series({
            "coverage_q70": (g["contacts"] <= g["fq70"]).mean(),
            "coverage_q80": (g["contacts"] <= g["fq80"]).mean(),
        }), include_groups=False
    ).round(3)
    print(cov.to_string(), flush=True)
    spread = cov["coverage_q70"].max() - cov["coverage_q70"].min()
    print(f"\n   coverage spread across weekdays at q70: {spread:.3f}", flush=True)
    if spread < 0.05:
        print("   -> a single quantile serves every weekday well; no need to", flush=True)
        print("      complicate the policy with per-weekday targets.", flush=True)
    else:
        print("   -> coverage varies materially by weekday; a per-weekday", flush=True)
        print("      quantile is worth testing.", flush=True)


if __name__ == "__main__":
    main()