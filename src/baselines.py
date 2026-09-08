"""Clean the daily series and establish baselines the real model must beat.

CLEANING DECISIONS, each defensible and each visible here rather than buried:

  Weekends are dropped. Weekend volume averages 102 contacts against 1,799 on
  weekdays -- that is after-hours logging, not staffed service. There is no
  staffing decision to make on a day the center is closed.

  Holidays and closures are EXCLUDED FROM EVALUATION, not imputed. A closed
  office is not a demand event. Forecasting "1 contact on Thanksgiving" is
  trivially easy and would flatter every error metric. They are identified
  from the data -- weekdays under 40% of a trailing median -- rather than from
  a hardcoded federal calendar, which also catches snow closures and other
  unscheduled shutdowns.

  Storm days STAY IN. The highest-volume days in the series are winter storms
  (25-27 Jan 2016, Winter Storm Jonas, peaked at 5,001 contacts against a
  median near 1,780). Removing them would make every error metric look better
  and every staffing decision worse. The tail is the point.

EVALUATION is rolling-origin one-day-ahead: every forecast uses only data
available before the day being predicted. No random splits, no future leakage.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

CLOSURE_THRESHOLD = 0.40    # of trailing median -> treated as a closure
TRAIL_WINDOW = 60           # weekdays used for the trailing median
MIN_HISTORY = 120           # weekdays before the first forecast is scored


def load_clean():
    df = pd.read_parquet(PROC / "daily_phone.parquet")
    df = df[df["dow"] < 5].sort_values("day").reset_index(drop=True)

    # Trailing median uses only prior days, so closure flags are point-in-time.
    df["trail_med"] = (df["contacts"].shift(1)
                       .rolling(TRAIL_WINDOW, min_periods=20).median())
    df["is_closure"] = df["contacts"] < CLOSURE_THRESHOLD * df["trail_med"]
    df["is_closure"] = df["is_closure"].fillna(False)
    return df


def build_forecasts(df):
    """Every forecast for day t uses only days strictly before t."""
    d = df.copy()
    prev = d["contacts"].shift(1)

    # 1. seasonal naive -- same weekday last week
    d["f_snaive"] = d["contacts"].shift(5)

    # 2. trailing mean for this weekday (last 8 occurrences)
    d["f_dow_mean"] = (d.groupby("dow")["contacts"]
                        .transform(lambda s: s.shift(1).rolling(8, min_periods=3).mean()))

    # 3. trailing median for this weekday -- robust to storm spikes
    d["f_dow_med"] = (d.groupby("dow")["contacts"]
                       .transform(lambda s: s.shift(1).rolling(8, min_periods=3).median()))

    # 4. weekday level scaled by a month index, both estimated from prior data
    overall = prev.rolling(TRAIL_WINDOW, min_periods=20).median()
    dow_ratio = (d.groupby("dow")["contacts"]
                  .transform(lambda s: s.shift(1).rolling(12, min_periods=4).median())) / overall
    month_ratio = (d.groupby("month")["contacts"]
                    .transform(lambda s: s.shift(1).rolling(60, min_periods=10).median())) / overall
    d["f_dow_month"] = overall * dow_ratio * month_ratio

    return d


def score(d, cols):
    rows = []
    for c in cols:
        m = d[c].notna()
        err = d.loc[m, "contacts"] - d.loc[m, c]
        rows.append({
            "forecast": c.replace("f_", ""),
            "n": int(m.sum()),
            "MAE": round(err.abs().mean(), 1),
            "RMSE": round(np.sqrt((err ** 2).mean()), 1),
            "MAPE": round((err.abs() / d.loc[m, "contacts"]).mean() * 100, 2),
            "bias": round(err.mean(), 1),
        })
    return pd.DataFrame(rows)


def main():
    df = load_clean()
    print(f"weekdays: {len(df):,}", flush=True)
    print(f"range: {df['day'].min().date()} to {df['day'].max().date()}\n", flush=True)

    n_clo = df["is_closure"].sum()
    print(f"closures detected: {n_clo} ({n_clo / len(df):.1%})", flush=True)
    print("\nmost recent 10 closures:", flush=True)
    print(df[df["is_closure"]].tail(10)[["day", "dow_name", "contacts"]]
          .to_string(index=False), flush=True)

    d = build_forecasts(df)

    # Score on open days only, after enough history has accumulated.
    ev = d.iloc[MIN_HISTORY:]
    ev = ev[~ev["is_closure"]].copy()
    print(f"\nevaluation days: {len(ev):,} "
          f"({ev['day'].min().date()} to {ev['day'].max().date()})\n", flush=True)

    cols = ["f_snaive", "f_dow_mean", "f_dow_med", "f_dow_month"]
    print("ROLLING-ORIGIN ONE-DAY-AHEAD ACCURACY", flush=True)
    print(score(ev, cols).to_string(index=False), flush=True)

    best = min(cols, key=lambda c: (ev["contacts"] - ev[c]).abs().mean())
    print(f"\nbest by MAE: {best.replace('f_', '')}", flush=True)

    print("\nMAE by year (best baseline):", flush=True)
    ev = ev.copy()
    ev["abs_err"] = (ev["contacts"] - ev[best]).abs()
    print(ev.groupby("year").agg(
        days=("abs_err", "size"),
        mean_volume=("contacts", "mean"),
        MAE=("abs_err", "mean"),
    ).round(1).to_string(), flush=True)

    print("\nMAE by weekday (best baseline):", flush=True)
    print(ev.groupby("dow_name").agg(
        days=("abs_err", "size"),
        mean_volume=("contacts", "mean"),
        MAE=("abs_err", "mean"),
    ).round(1).sort_values("MAE").to_string(), flush=True)

    # The tail is where staffing decisions actually hurt.
    print("\nERROR ON HIGH-VOLUME DAYS (top 5% of the series):", flush=True)
    thresh = ev["contacts"].quantile(0.95)
    tail = ev[ev["contacts"] >= thresh]
    print(f"  threshold: {thresh:.0f} contacts, {len(tail)} days", flush=True)
    print(f"  MAE on those days: {tail['abs_err'].mean():.0f} "
          f"vs {ev['abs_err'].mean():.0f} overall", flush=True)
    under = (tail["contacts"] - tail[best])
    print(f"  mean UNDER-forecast on those days: {under.mean():+.0f} contacts",
          flush=True)

    d.to_parquet(PROC / "series_with_baselines.parquet", index=False)
    print(f"\nsaved: {PROC / 'series_with_baselines.parquet'}", flush=True)


if __name__ == "__main__":
    main()