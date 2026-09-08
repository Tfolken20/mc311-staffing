"""Pull daily MC311 contact volume, aggregated server-side.

The full dataset is ~7.9M service requests. We do not need row-level data --
the forecasting unit is a day. Socrata aggregates server-side, so a handful of
grouped queries return a few thousand daily rows instead of millions of records.

Three pulls:
  daily_total.parquet    -- counts by date, channel, and request type
  daily_dept.parquet     -- counts by date and department (for allocation work)
  sla_by_area.parquet    -- SLA window and breach rate by service area

CHANNEL MATTERS. sr_subtype_cd splits Phone / Web / Internal / Email. Only
phone (and inbound-equivalent) contacts consume agent handle time, so the
staffing-relevant series is phone volume, not total requests.
"""
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
ENDPOINT = "https://data.montgomerycountymd.gov/resource/xtyh-brr2.json"
PAGE = 50000


def soql(select, group=None, where=None, order=None):
    """Run a Socrata query, paging until exhausted."""
    out, offset = [], 0
    while True:
        params = {"$select": select, "$limit": PAGE, "$offset": offset}
        if group:
            params["$group"] = group
        if where:
            params["$where"] = where
        if order:
            params["$order"] = order

        for attempt in range(4):
            try:
                r = requests.get(ENDPOINT, params=params, timeout=120)
                r.raise_for_status()
                break
            except Exception as e:
                if attempt == 3:
                    raise
                print(f"    retry {attempt + 1} after {type(e).__name__}", flush=True)
                time.sleep(3 * (attempt + 1))

        chunk = r.json()
        out.extend(chunk)
        print(f"    +{len(chunk):,} rows (total {len(out):,})", flush=True)
        if len(chunk) < PAGE:
            break
        offset += PAGE
    return pd.DataFrame(out)


def main():
    RAW.mkdir(parents=True, exist_ok=True)

    # --- 1. daily counts by channel and request type ---
    print("daily counts by channel and type...", flush=True)
    df = soql(
        select="date_trunc_ymd(created) AS day, sr_subtype_cd, sr_type, count(1) AS n",
        group="day, sr_subtype_cd, sr_type",
        order="day",
    )
    df["day"] = pd.to_datetime(df["day"])
    df["n"] = pd.to_numeric(df["n"])
    df.to_parquet(RAW / "daily_total.parquet", index=False)
    print(f"  saved daily_total.parquet  {df.shape}", flush=True)
    print(f"  date range: {df['day'].min().date()} to {df['day'].max().date()}",
          flush=True)
    print(f"  channels: {sorted(df['sr_subtype_cd'].dropna().unique())}\n", flush=True)

    # --- 2. daily counts by department ---
    print("daily counts by department...", flush=True)
    dept = soql(
        select="date_trunc_ymd(created) AS day, department, sr_subtype_cd, count(1) AS n",
        group="day, department, sr_subtype_cd",
        order="day",
    )
    dept["day"] = pd.to_datetime(dept["day"])
    dept["n"] = pd.to_numeric(dept["n"])
    dept.to_parquet(RAW / "daily_dept.parquet", index=False)
    print(f"  saved daily_dept.parquet  {dept.shape}", flush=True)
    print(f"  departments: {dept['department'].nunique()}\n", flush=True)

    # --- 3. SLA structure by service area ---
    print("SLA structure by service area...", flush=True)
    sla = soql(
        select=("sr_area, department, count(1) AS n, "
                "avg(x_sla::number) AS sla_days_avg, "
                "sum(sla_no::number) AS breaches"),
        group="sr_area, department",
    )
    for c in ("n", "sla_days_avg", "breaches"):
        sla[c] = pd.to_numeric(sla[c], errors="coerce")
    sla["breach_rate"] = sla["breaches"] / sla["n"]
    sla = sla.sort_values("n", ascending=False)
    sla.to_parquet(RAW / "sla_by_area.parquet", index=False)
    print(f"  saved sla_by_area.parquet  {sla.shape}\n", flush=True)

    # --- summary ---
    print("=" * 60, flush=True)
    phone = df[df["sr_subtype_cd"] == "Phone"].groupby("day")["n"].sum()
    print(f"\nphone contacts: {phone.sum():,.0f} across {len(phone):,} days", flush=True)
    print(f"daily phone volume:", flush=True)
    print(phone.describe().round(1).to_string(), flush=True)

    print("\nvolume share by channel:", flush=True)
    share = df.groupby("sr_subtype_cd")["n"].sum().sort_values(ascending=False)
    print((share / share.sum()).round(4).to_string(), flush=True)

    print("\ntop 10 service areas by volume:", flush=True)
    print(sla.head(10)[["sr_area", "department", "n", "sla_days_avg",
                        "breach_rate"]].round(3).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()