"""Daily weather for Montgomery County, MD, from the Open-Meteo historical archive.

WHY: the ten worst staffing days in this series are all winter storms. Baseline
staffing handles routine variation; the residual risk is concentrated in
weather events.

A CRITICAL HONESTY POINT ABOUT WHAT THIS CAN AND CANNOT SHOW

Using OBSERVED weather for a day to predict that day's call volume is not a
forecast -- it is hindsight. The real staffing decision is made the afternoon
before, using a National Weather Service forecast, which is imperfect.

Historical forecast archives spanning 2012-2026 are not readily available for
free. So observed weather is used here as a PROXY, and every result built on
it is an UPPER BOUND on what a real deployment could achieve -- the value of a
perfect forecast.

That bound is still decision-relevant. If perfect weather knowledge does not
materially improve tail coverage, an imperfect forecast certainly will not, and
the idea can be dropped cheaply. If it does help substantially, the next step
is to quantify the degradation under realistic forecast skill. Note also that
the gap is narrower for this variable than for most: major snow events are
forecast with high skill 24-48 hours out, unlike precise precipitation amounts.

Location: Montgomery County centroid, near Rockville / Gaithersburg.
"""
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

# Montgomery County, MD -- county centroid, close to the population centre
LAT, LON = 39.14, -77.20
START, END = "2012-07-01", "2026-09-07"

ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
]


def main():
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": START,
        "end_date": END,
        "daily": ",".join(DAILY_VARS),
        "timezone": "America/New_York",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "wind_speed_unit": "mph",
    }

    print(f"fetching {START} to {END} for ({LAT}, {LON})...", flush=True)
    r = requests.get(ENDPOINT, params=params, timeout=180)
    r.raise_for_status()
    payload = r.json()

    if "daily" not in payload:
        raise SystemExit(f"unexpected response: {list(payload.keys())}")

    df = pd.DataFrame(payload["daily"])
    df = df.rename(columns={"time": "day"})
    df["day"] = pd.to_datetime(df["day"])

    print(f"rows: {len(df):,}", flush=True)
    print(f"range: {df['day'].min().date()} to {df['day'].max().date()}\n", flush=True)

    print("missing rate by variable:", flush=True)
    print(df.isna().mean().round(4).to_string(), flush=True)

    print("\nsummary:", flush=True)
    print(df.describe().round(2).to_string(), flush=True)

    # Snow is the variable of interest -- check it looks like a real snow record.
    snow = df[df["snowfall_sum"] > 0]
    print(f"\ndays with any snowfall: {len(snow):,} "
          f"({len(snow) / len(df):.1%})", flush=True)
    print(f"days with 4+ inches:    {(df['snowfall_sum'] >= 4).sum():,}", flush=True)

    print("\nten largest snowfall days:", flush=True)
    top = df.nlargest(10, "snowfall_sum")[
        ["day", "snowfall_sum", "precipitation_sum", "temperature_2m_max"]]
    print(top.to_string(index=False), flush=True)

    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / "weather_daily.parquet"
    df.to_parquet(out, index=False)
    print(f"\nsaved: {out}", flush=True)


if __name__ == "__main__":
    main()