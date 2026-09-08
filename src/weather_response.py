"""How does contact volume actually respond to weather?

Profile the response before designing features. The ten worst staffing days are
all winter storms, but the naive feature -- same-day snowfall -- is wrong. When
Winter Storm Jonas dropped 14.4 inches on Saturday 23 January 2016, the county
was closed; the call surge arrived Monday through Thursday. Demand is deferred
into the reopening, not concentrated in the storm.

So the questions to answer empirically, before writing any feature:

  1. What is the lag structure? How many days after snow does volume stay high?
  2. Does accumulation over a window beat a single day's snowfall?
  3. Is there a threshold, or is the response continuous in inches?
  4. Does anything other than snow matter -- rain, wind, heat, cold?
  5. How much of the extreme tail does weather actually explain?

Question 5 is the one that decides whether this is worth building. If weather
explains most of the tail, a surge protocol has something to trigger on. If it
explains a third, the tail is mostly idiosyncratic and no weather feature will
fix it.

Volume is measured as a RATIO to the point forecast, not in raw contacts, so
day-of-week and trend structure are already removed.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

MAX_LAG = 5


def main():
    calls = pd.read_parquet(PROC / "staffing_evaluation.parquet")
    wx = pd.read_parquet(RAW / "weather_daily.parquet")

    # Lagged and accumulated weather, computed on the full calendar (including
    # weekends) so a Saturday storm is visible to the following Monday.
    wx = wx.sort_values("day").reset_index(drop=True)
    for lag in range(0, MAX_LAG + 1):
        wx[f"snow_lag{lag}"] = wx["snowfall_sum"].shift(lag)
        wx[f"rain_lag{lag}"] = wx["rain_sum"].shift(lag)
    for w in (2, 3, 5, 7):
        wx[f"snow_sum{w}d"] = wx["snowfall_sum"].rolling(w, min_periods=1).sum()
    wx["cold"] = wx["temperature_2m_min"] < 20
    wx["hot"] = wx["temperature_2m_max"] > 95
    wx["windy"] = wx["wind_gusts_10m_max"] > 45
    wx["heavy_rain"] = wx["rain_sum"] > 1.0

    d = calls.merge(wx, on="day", how="left")
    d["ratio"] = d["contacts"] / d["f_dow_med"]
    print(f"days joined: {len(d):,}  "
          f"weather missing: {d['snowfall_sum'].isna().mean():.2%}\n", flush=True)

    # ---- 1. lag structure ----
    print("1. LAG STRUCTURE -- volume ratio by days since 2+ inches of snow", flush=True)
    rows = []
    for lag in range(0, MAX_LAG + 1):
        m = d[f"snow_lag{lag}"] >= 2.0
        if m.sum() < 5:
            continue
        rows.append({
            "days_after_snow": lag,
            "n": int(m.sum()),
            "mean_ratio": round(d.loc[m, "ratio"].mean(), 3),
            "median_ratio": round(d.loc[m, "ratio"].median(), 3),
            "pct_above_1.2x": round((d.loc[m, "ratio"] > 1.2).mean(), 3),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    print(f"\n   baseline (all days): mean ratio "
          f"{d['ratio'].mean():.3f}, {(d['ratio'] > 1.2).mean():.1%} above 1.2x",
          flush=True)

    # ---- 2. accumulation windows ----
    print("\n2. ACCUMULATION -- does a multi-day window beat a single day?", flush=True)
    rows = []
    for col in ["snowfall_sum"] + [f"snow_sum{w}d" for w in (2, 3, 5, 7)]:
        sub = d[[col, "ratio"]].dropna()
        rows.append({
            "feature": col,
            "corr_with_ratio": round(sub[col].corr(sub["ratio"]), 4),
            "corr_when_snowing": round(
                sub[sub[col] > 0][col].corr(sub[sub[col] > 0]["ratio"]), 4),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    # ---- 3. threshold or continuous? ----
    print("\n3. DOSE RESPONSE -- 3-day snow accumulation", flush=True)
    bins = [-0.01, 0.001, 0.5, 1, 2, 4, 8, 100]
    labels = ["none", "trace-0.5", "0.5-1", "1-2", "2-4", "4-8", "8+"]
    d["snow_band"] = pd.cut(d["snow_sum3d"], bins=bins, labels=labels)
    band = d.groupby("snow_band", observed=True).agg(
        days=("ratio", "size"),
        mean_ratio=("ratio", "mean"),
        median_ratio=("ratio", "median"),
        p90_ratio=("ratio", lambda s: s.quantile(0.90)),
    ).round(3)
    print(band.to_string(), flush=True)

    # ---- 4. other weather ----
    print("\n4. OTHER CONDITIONS -- mean volume ratio", flush=True)
    rows = []
    for flag in ("cold", "hot", "windy", "heavy_rain"):
        m = d[flag].fillna(False)
        if m.sum() < 20:
            continue
        rows.append({
            "condition": flag,
            "days": int(m.sum()),
            "mean_ratio": round(d.loc[m, "ratio"].mean(), 3),
            "vs_baseline": round(d.loc[m, "ratio"].mean() - d["ratio"].mean(), 3),
        })
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    # ---- 5. how much of the tail does weather explain? ----
    print("\n5. THE TAIL -- what share of extreme days follows snow?", flush=True)
    for pct in (0.99, 0.95, 0.90):
        thr = d["ratio"].quantile(pct)
        tail = d[d["ratio"] >= thr]
        snowy = (tail["snow_sum3d"] >= 1.0).mean()
        base_rate = (d["snow_sum3d"] >= 1.0).mean()
        print(f"   top {(1 - pct) * 100:.0f}% of days by ratio "
              f"(n={len(tail)}, threshold {thr:.2f}x):", flush=True)
        print(f"      preceded by 1+ inch in 3 days: {snowy:.1%}  "
              f"(base rate {base_rate:.1%}, lift {snowy / base_rate:.1f}x)",
              flush=True)

    print("\n6. THE TEN LARGEST VOLUME RATIOS", flush=True)
    worst = d.nlargest(10, "ratio")[
        ["day", "dow_name", "contacts", "f_dow_med", "ratio",
         "snowfall_sum", "snow_sum3d", "temperature_2m_min"]]
    print(worst.round(2).to_string(index=False), flush=True)

    d.to_parquet(PROC / "calls_with_weather.parquet", index=False)
    print(f"\nsaved: {PROC / 'calls_with_weather.parquet'}", flush=True)


if __name__ == "__main__":
    main()