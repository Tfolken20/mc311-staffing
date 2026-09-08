"""Build and diagnose the daily phone-contact series before any modeling.

Phone is 82% of MC311 volume; every other channel is under 14% and most are
rounding errors. Phone alone is the staffing-relevant series.

This script does not fit anything. It answers the questions that determine how
the forecast should be built:

  - Is this a weekday-only operation?
  - How strong is the day-of-week effect?
  - Is there annual seasonality, and at what scale?
  - Is there a trend, and are there structural breaks (COVID, system changes)?
  - How do holidays behave?
  - Are there outliers that need handling rather than modeling?

Answering these first is the difference between a forecast that fits the data
and one that fits the operation.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

PRIMARY_CHANNEL = "Phone"


def main():
    df = pd.read_parquet(RAW / "daily_total.parquet")
    df = df[df["sr_subtype_cd"] == PRIMARY_CHANNEL]

    # Collapse request types into one daily count, and keep the fulfillment
    # share separately -- fulfillment requests take longer to handle than
    # general information calls, so the mix is a workload signal.
    daily = df.groupby("day").agg(
        contacts=("n", "sum"),
    ).reset_index()

    fulfil = (df[df["sr_type"] == "Service Request - Fulfillment"]
              .groupby("day")["n"].sum().rename("fulfillment"))
    daily = daily.merge(fulfil, on="day", how="left")
    daily["fulfillment"] = daily["fulfillment"].fillna(0)
    daily["fulfil_share"] = daily["fulfillment"] / daily["contacts"]

    daily = daily.sort_values("day").reset_index(drop=True)
    daily["dow"] = daily["day"].dt.dayofweek          # 0 = Monday
    daily["dow_name"] = daily["day"].dt.day_name()
    daily["month"] = daily["day"].dt.month
    daily["year"] = daily["day"].dt.year

    print(f"days with any phone volume: {len(daily):,}", flush=True)
    print(f"range: {daily['day'].min().date()} to {daily['day'].max().date()}",
          flush=True)

    span = (daily["day"].max() - daily["day"].min()).days + 1
    print(f"calendar days in range:     {span:,}", flush=True)
    print(f"coverage:                   {len(daily) / span:.1%}\n", flush=True)

    # --- 1. day of week ---
    print("1. DAY OF WEEK", flush=True)
    dow = daily.groupby(["dow", "dow_name"])["contacts"].agg(
        days="size", mean="mean", median="median").reset_index()
    dow["vs_overall"] = (dow["mean"] / daily["contacts"].mean()).round(3)
    print(dow.round(1).to_string(index=False), flush=True)

    weekend = daily[daily["dow"] >= 5]
    print(f"\n   weekend days present: {len(weekend):,} "
          f"({len(weekend) / len(daily):.1%})", flush=True)
    if len(weekend):
        print(f"   weekend mean volume: {weekend['contacts'].mean():.0f} "
              f"vs weekday {daily[daily['dow'] < 5]['contacts'].mean():.0f}",
              flush=True)

    # --- 2. trend by year ---
    print("\n2. TREND", flush=True)
    yearly = daily.groupby("year").agg(
        days=("contacts", "size"),
        mean_daily=("contacts", "mean"),
        total=("contacts", "sum"),
    ).round(0)
    yearly["pct_change"] = yearly["mean_daily"].pct_change().round(3)
    print(yearly.to_string(), flush=True)

    # --- 3. annual seasonality (weekdays only, to avoid dow contamination) ---
    print("\n3. MONTHLY SEASONALITY (weekdays only)", flush=True)
    wd = daily[daily["dow"] < 5]
    monthly = wd.groupby("month")["contacts"].mean()
    monthly_idx = (monthly / monthly.mean()).round(3)
    print(pd.DataFrame({"mean_daily": monthly.round(0),
                        "index": monthly_idx}).to_string(), flush=True)
    print(f"\n   peak month vs trough: "
          f"{monthly_idx.max() / monthly_idx.min():.2f}x", flush=True)

    # --- 4. outliers ---
    print("\n4. OUTLIERS (weekdays)", flush=True)
    med = wd["contacts"].median()
    mad = (wd["contacts"] - med).abs().median()
    wd = wd.copy()
    wd["z"] = (wd["contacts"] - med) / (1.4826 * mad)

    high = wd.nlargest(10, "contacts")[["day", "dow_name", "contacts", "z"]]
    low = wd.nsmallest(10, "contacts")[["day", "dow_name", "contacts", "z"]]
    print("   highest days:", flush=True)
    print(high.round(2).to_string(index=False), flush=True)
    print("\n   lowest days (likely holidays or closures):", flush=True)
    print(low.round(2).to_string(index=False), flush=True)

    n_low = (wd["contacts"] < 0.5 * med).sum()
    print(f"\n   weekdays under half the median: {n_low:,} "
          f"({n_low / len(wd):.1%}) -- candidate holidays/closures", flush=True)

    # --- 5. request mix ---
    print("\n5. REQUEST MIX", flush=True)
    print(f"   fulfillment share of phone contacts: "
          f"mean {daily['fulfil_share'].mean():.1%}", flush=True)
    yearly_mix = daily.groupby("year")["fulfil_share"].mean().round(3)
    print("   by year:", flush=True)
    print(yearly_mix.to_string(), flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(OUT / "daily_phone.parquet", index=False)
    print(f"\nsaved: {OUT / 'daily_phone.parquet'}", flush=True)


if __name__ == "__main__":
    main()