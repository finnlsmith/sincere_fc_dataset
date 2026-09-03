"""
Scrape DataMB's top-7-leagues position files and combine into one dated
snapshot CSV.

No authentication needed — the xlsx files are publicly served, CORS-open,
confirmed working with a plain requests.get() and no cookies (see
sincerefc_scraping_project_spec.md, section 4, DataMB).

Usage:
    python scrape_datamb.py [output_dir]

If output_dir is omitted, defaults to a dated folder: data/datamb/snapshots/<YYYY-MM-DD>/

Example:
    python scrape_datamb.py
    python scrape_datamb.py data/datamb/snapshots/2026-08-18

Can also be imported and called directly:
    from scrape_datamb import scrape_datamb
    combined_csv_path = scrape_datamb("data/datamb/snapshots/2026-08-18")
"""

import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://datamb.football/database/CURRENT/TOP72526/{pos}/{pos}.xlsx"
POSITIONS = ["GK", "CB", "FB", "CM", "FW", "ST"]

# Sanity-check thresholds from the last known-good scrape (see spec).
# A run returning far fewer rows than this for a position likely means
# DataMB changed something and needs investigating, not a silent save.
EXPECTED_MIN_ROWS = {
    "GK": 100, "CB": 300, "FB": 250, "CM": 400, "FW": 250, "ST": 150,
}


def scrape_datamb(output_dir: str | None = None) -> Path:
    if output_dir is None:
        today = datetime.now().strftime("%Y-%m-%d")
        output_dir = f"data/datamb/snapshots/{today}"

    out_dir = Path(output_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    dfs = []
    failed = []

    for pos in POSITIONS:
        url = BASE_URL.format(pos=pos)
        print(f"Fetching {pos} ...")

        try:
            r = requests.get(url, timeout=30)
        except requests.RequestException as e:
            print(f"  ✗ Request failed: {e}")
            failed.append(pos)
            continue

        if r.status_code != 200:
            print(f"  ✗ HTTP {r.status_code}")
            failed.append(pos)
            continue

        try:
            df = pd.read_excel(BytesIO(r.content))
        except Exception as e:
            print(f"  ✗ Failed to parse xlsx: {e}")
            failed.append(pos)
            continue

        expected_min = EXPECTED_MIN_ROWS.get(pos, 0)
        if len(df) < expected_min:
            print(f"  ⚠️  Only {len(df)} rows (expected at least ~{expected_min}) "
                  f"— saving anyway, but this looks like a possible silent failure")
        else:
            print(f"  ✓ {len(df)} rows, {len(df.columns)} columns")

        # Keep a raw copy per position for provenance / debugging
        raw_path = raw_dir / f"{pos}.xlsx"
        with open(raw_path, "wb") as f:
            f.write(r.content)

        df["position"] = pos
        dfs.append(df)

    if not dfs:
        raise RuntimeError(f"All {len(POSITIONS)} position fetches failed — nothing to save")

    if failed:
        print(f"\n⚠️  {len(failed)}/{len(POSITIONS)} positions failed: {failed}")
        print("   Combined snapshot will be missing those positions.")

    combined = pd.concat(dfs, ignore_index=True)

    combined_path = out_dir / "datamb_top7_combined.csv"
    combined.to_csv(combined_path, index=False)

    print(f"\n✓ Combined snapshot saved: {combined_path} "
          f"({len(combined)} rows, {combined['position'].nunique()} positions)")

    return combined_path


if __name__ == "__main__":
    if len(sys.argv) > 2:
        print("Usage: python scrape_datamb.py [output_dir]")
        sys.exit(1)

    output_dir = sys.argv[1] if len(sys.argv) == 2 else None

    try:
        scrape_datamb(output_dir)
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
