# cnv-mobility-archive

Archives shared-mobility supply-side data for Metro Vancouver, for the CNV active
mobility research project.

**Why this exists:** GBFS feeds are live snapshots with no history. There is a
real, openly-licensed ~3-year archive of Mobi already (see `mirror/`), but
**nothing at all** for Lime Vancouver — so every day without collection is
permanently lost for that system.

## Quick start

    pip install -r requirements.txt
    python3 scrape.py                 # all systems
    python3 scrape.py mobi-vancouver  # one system

Then push to GitHub. `.github/workflows/scrape.yml` runs every 15 minutes and
commits results.

**Make the repo public.** Two reasons: GitHub Actions minutes are unlimited on
public repos and this schedule would exceed the free private allowance; and a
public archive is itself the advocacy argument — it demonstrates that publishing
this data is trivial and harmless.

## Mirror the existing archives first

    ./mirror/mirror_existing_archives.sh ./mirrors

Pulls both existing public Mobi archives. Neither has a preservation
commitment — one is git history in a single person's repo, the other is an
endpoint its maintainers label "experimental." Do this before anything else.

Known permanent gap in the existing archives: **2024-04-12 to 2024-08-22.**

## Storage model

    data/<system>/<YYYY>/<MM>/<YYYY-MM-DD>/<HHMMSS>Z.<k|d|s>.json.gz

`k` = keyframe (full state, first poll of each UTC day) · `d` = delta (changed
stations only) · `s` = snapshot (full, free-floating systems)

Files are immutable and append-only. Nothing is ever rewritten, so retried or
overlapping runs can't corrupt earlier data.

Reconstruct any moment by replaying the day's keyframe then applying deltas in
filename order — `consolidate.py` does this.

## Monthly consolidation

    pip install -r requirements-consolidate.txt
    python3 consolidate.py mobi-vancouver 2026-08
    python3 consolidate.py mobi-vancouver 2026-08 --prune

Raw gzipped JSON is the right *capture* format and the wrong *storage* format.
Consolidate monthly to Parquet, verify, then prune. `--prune` reads the Parquet
back and asserts the row count before deleting anything.

Rough expectations: Mobi ~1-2 MB/month raw with deltas; Lime ~300 MB/year raw
as full snapshots, which is why monthly consolidation matters more for Lime.

## Three design decisions worth knowing

**1. Feed URLs are auto-discovered, never hardcoded.** The main public GBFS
archive silently lost its Vancouver series because its config still pointed at
Mobi's retired Smoove endpoint after the operator migrated hosts. Every run
re-resolves feeds from `gbfs.json`, so a host migration is followed rather than
silently dropped.

**2. It fails loudly.** That same archive kept running for 100+ other systems
while Vancouver returned nothing, for roughly a year, unnoticed. A system
yielding zero records exits non-zero here so the scheduler surfaces it. Watch
for the failure emails; a silent scraper is worse than no scraper because you
believe you have data.

**3. Coordinates are kept at ~1m precision.** These are publicly visible parked
vehicles, not riders, and no trip or rider data is collected. Coarser rounding
would destroy the curb-level analysis this exists to support. If the archive is
ever used for anything rider-adjacent, revisit this.

## What this data can and cannot answer

**Can:** fleet size over time · spatial distribution and rebalancing · station
stockouts and dock-fulls · service-area changes · vehicle dwell times · supply
equity across neighbourhoods.

**Cannot:** trips, origin-destination pairs, rider attributes, trip duration.
GBFS contains none of these. Inferring trips from snapshot differences conflates
operator rebalancing with real trips and misses anything shorter than the poll
interval — for free-floating fleets it's especially unreliable. Don't do it.

For Mobi demand-side questions use the operator's trip files
(<https://www.mobibikes.ca/en/system-data>, 2017-present, hour-rounded
timestamps). Because that overlaps this archive from Aug 2023, trips and
availability can be joined — which is the interesting analysis.
