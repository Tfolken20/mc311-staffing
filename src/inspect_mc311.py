"""Pull a small sample from the MC311 Socrata API to see what the data looks like."""
import json
from collections import Counter

import pandas as pd
import requests

ENDPOINT = "https://data.montgomerycountymd.gov/resource/xtyh-brr2.json"
SAMPLE = 2000


def main():
    print(f"fetching {SAMPLE} rows...", flush=True)
    r = requests.get(ENDPOINT, params={"$limit": SAMPLE}, timeout=60)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows)

    print(f"shape: {df.shape}\n", flush=True)
    print("columns:", flush=True)
    for c in df.columns:
        nn = df[c].notna().mean()
        print(f"  {c!r}  ({df[c].dtype})  populated={nn:.1%}")

    print("\nfirst record, full:", flush=True)
    print(json.dumps(rows[0], indent=2), flush=True)

    # Anything that looks like a channel / origin field is the key question:
    # phone-origin requests are the staffing-relevant ones.
    for c in df.columns:
        low = str(c).lower()
        if any(k in low for k in ("source", "channel", "origin", "method", "type", "dept", "department")):
            print(f"\nvalue counts for {c!r}:", flush=True)
            print(df[c].value_counts().head(12).to_string(), flush=True)

    # Total row count available on the server.
    cr = requests.get(ENDPOINT, params={"$select": "count(1)"}, timeout=60)
    if cr.ok:
        print(f"\ntotal rows on server: {cr.json()}", flush=True)


if __name__ == "__main__":
    main()