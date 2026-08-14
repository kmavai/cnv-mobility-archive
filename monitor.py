#!/usr/bin/env python3
"""
Fail loudly if the archive has stalled.

Silent degradation is the failure mode that already killed one public GBFS
archive: MaxHalford/bike-sharing-history kept running for 100+ systems while
its Vancouver series returned nothing for over a year, unnoticed. A stalled
scraper is worse than no scraper, because you believe you have data.

Checks, per system:
  1. Time since the most recent snapshot (staleness).
  2. The largest gap between consecutive snapshots in the recent window.

Exits non-zero if either exceeds --max-gap-minutes, so the scheduled workflow
goes red and GitHub emails on failure.

Run:  python3 monitor.py [--max-gap-minutes 90] [--window-hours 24]
"""
import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"

# data/<system>/<YYYY>/<MM>/<YYYY-MM-DD>/<HHMMSS>Z.<kind>.json.gz
STAMP = re.compile(r"^(\d{6})Z\.[kds]\.json\.gz$")


def snapshot_times(system_dir: Path):
    out = []
    for f in system_dir.rglob("*.json.gz"):
        m = STAMP.match(f.name)
        if not m:
            continue
        day = f.parent.name  # YYYY-MM-DD
        try:
            ts = datetime.strptime(f"{day} {m.group(1)}", "%Y-%m-%d %H%M%S")
        except ValueError:
            continue
        out.append(ts.replace(tzinfo=timezone.utc))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-gap-minutes", type=float, default=90)
    ap.add_argument("--window-hours", type=float, default=24)
    args = ap.parse_args()

    if not DATA.exists():
        print("FAIL: no data/ directory at all", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - args.window_hours * 3600
    problems = []
    any_system = False

    for system_dir in sorted(p for p in DATA.iterdir() if p.is_dir()):
        any_system = True
        sid = system_dir.name
        times = snapshot_times(system_dir)
        if not times:
            problems.append(f"{sid}: NO SNAPSHOTS AT ALL")
            continue

        stale_min = (now - times[-1]).total_seconds() / 60
        recent = [t for t in times if t.timestamp() >= cutoff]

        # Largest gap inside the window. Needs >=2 points to say anything.
        worst_gap = None
        if len(recent) >= 2:
            gaps = [(recent[i + 1] - recent[i]).total_seconds() / 60
                    for i in range(len(recent) - 1)]
            worst_gap = max(gaps)

        gap_s = f"{worst_gap:.0f}m" if worst_gap is not None else "n/a"
        print(f"{sid}: {len(recent)} snapshots in last {args.window_hours:g}h | "
              f"last {stale_min:.0f}m ago | worst gap {gap_s}")

        if stale_min > args.max_gap_minutes:
            problems.append(f"{sid}: STALE - last snapshot {stale_min:.0f} min ago "
                            f"(limit {args.max_gap_minutes:g})")
        if worst_gap is not None and worst_gap > args.max_gap_minutes:
            problems.append(f"{sid}: GAP - {worst_gap:.0f} min between consecutive "
                            f"snapshots (limit {args.max_gap_minutes:g})")

    if not any_system:
        problems.append("no system directories under data/")

    if problems:
        print("\n" + "=" * 60, file=sys.stderr)
        print("ARCHIVE HEALTH CHECK FAILED", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.exit(1)

    print("\nok - all systems within freshness limits")


if __name__ == "__main__":
    main()
