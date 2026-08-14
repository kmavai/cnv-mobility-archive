#!/usr/bin/env python3
"""
Consolidate a month of raw snapshots into a single Parquet file.

Why: raw gzipped JSON is the right *capture* format (immutable, append-only,
diff-friendly) but the wrong *storage* format. Columnar Parquet on the same
data is typically 5-15x smaller and vastly faster to query. Run this monthly,
verify the output, then prune the raw files.

Usage:
  python3 consolidate.py mobi-vancouver 2026-08
  python3 consolidate.py mobi-vancouver 2026-08 --prune
"""
import argparse
import gzip
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "parquet"


def iter_files(system, year, month):
    base = DATA / system / year / month
    if not base.exists():
        sys.exit(f"no data at {base}")
    for day in sorted(base.iterdir()):
        if day.is_dir():
            for f in sorted(day.iterdir()):
                if f.name.endswith(".json.gz"):
                    yield f


def load(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def build_station_frame(files):
    """Replay keyframes + deltas into a full per-poll station panel."""
    rows, state = [], {}
    for f in files:
        doc = load(f)
        ts = doc["ts"]
        if doc["type"] == "keyframe":
            state = {str(r.get("station_id")): r for r in doc["stations"]}
        elif doc["type"] == "delta":
            for r in doc.get("changed", []):
                state[str(r.get("station_id"))] = r
            for k in doc.get("removed", []):
                state.pop(k, None)
        else:
            continue
        for sid, r in state.items():
            rows.append({"ts": ts, "station_id": sid, **{k: v for k, v in r.items()
                                                          if k != "station_id"}})
    return pd.DataFrame(rows)


def build_vehicle_frame(files):
    rows = []
    for f in files:
        doc = load(f)
        if doc.get("type") != "snapshot":
            continue
        ts = doc["ts"]
        for v in doc["vehicles"]:
            rows.append({"ts": ts, **v})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("system")
    ap.add_argument("month", help="YYYY-MM")
    ap.add_argument("--prune", action="store_true",
                    help="delete raw files after verifying the parquet")
    args = ap.parse_args()

    year, month = args.month.split("-")
    files = list(iter_files(args.system, year, month))
    if not files:
        sys.exit("no snapshot files found")

    kinds = {f.name.split(".")[-3] for f in files}
    df = build_vehicle_frame(files) if "s" in kinds else build_station_frame(files)
    if df.empty:
        sys.exit("no rows produced - refusing to write an empty parquet")

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{args.system}-{args.month}.parquet"
    df.to_parquet(out, compression="zstd", index=False)

    raw_mb = sum(f.stat().st_size for f in files) / 1e6
    pq_mb = out.stat().st_size / 1e6
    print(f"{len(df):,} rows  |  raw {raw_mb:.1f} MB -> parquet {pq_mb:.1f} MB "
          f"({raw_mb / pq_mb:.1f}x smaller)")
    print(f"wrote {out}")

    if args.prune:
        # Read it back before deleting anything. Never prune on faith.
        check = pd.read_parquet(out)
        assert len(check) == len(df), "parquet readback mismatch - NOT pruning"
        shutil.rmtree(DATA / args.system / year / month)
        print(f"pruned raw {DATA / args.system / year / month}")


if __name__ == "__main__":
    main()
