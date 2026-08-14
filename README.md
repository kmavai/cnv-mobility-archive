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

Poll once and exit (the default), or sample on a fixed cadence:

    python3 scrape.py --interval 900 --duration 2400   # poll every 15 min for 30 min

Then push to GitHub. `.github/workflows/scrape.yml` runs it on a schedule and
commits results — but see **Cadence** below, because the schedule is not what
sets the sampling rate.

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

## Cadence — read this before changing the cron

**GitHub's scheduler cannot deliver a 15-minute cadence, and tuning the cron
will not fix it.** Measured over 10 consecutive runs off a `*/15` schedule, gaps
between runs were **58, 58, 32, 39, 25, 28, 28, 31, 29 minutes** — a median of
31 and an effective **44 runs/day against a target of 96**. GitHub throttles
scheduled workflows heavily and offers no guarantee about delivery.

So the sampling rate is set **inside the job**, not by the scheduler.
`scrape.py --interval 900 --duration 2400` polls every 15 minutes for 30
minutes, then the job commits and exits. The schedule's only job is to fire
often enough that a successor is always queued; `concurrency: cancel-in-progress:
false` makes runs chain back-to-back rather than overlap.

**Achieved cadence: ~15-minute sampling (≈96 snapshots/day), continuous**, versus
~44/day before. The schedule still says `*/15`; that is intentional and means
"start as often as you're willing," not "sample every 15 minutes."

Three constraints shaped this, and they're worth knowing before retuning:

- **Runs are kept short (~32 min), not maximal.** Data is only committed at the
  end of a run, so a long run leaves the newest *committed* snapshot stale even
  while scraping is perfectly healthy — which would trip the 90-minute monitor
  for no reason. Short runs also bound how much is lost if a job is cancelled.
- **Lime cannot be delta-encoded**, so every Lime poll is a full ~36 KB gzipped
  file. At 15 min that's ~1.3 GB/year; at 2 min it would be ~9.5 GB/year in a git
  repo. See the vehicle-ID note below for why faster sampling buys less than it
  appears to.
- **Alternatives considered.** Staggering several offset workflow files raises the
  run count but each run still samples once, so it treats the symptom; the
  in-process loop decouples cadence from the scheduler entirely and was strictly
  better. A VPS or self-hosted runner with real cron would give exact timing and
  remains the right answer if sub-5-minute sampling is ever needed — it costs
  money and a host, so it wasn't justified for a target the loop already meets.

## Monitoring — `monitor.py`

    python3 monitor.py --max-gap-minutes 90 --window-hours 24

Fails non-zero if any system's newest snapshot is older than the limit, or if any
gap between consecutive snapshots inside the window exceeds it. Runs hourly via
`.github/workflows/monitor.yml`; a red run emails the repo owner.

It is a **separate workflow from `scrape` on purpose**: if the scraper stops
being scheduled or dies, its own steps never execute and therefore can never
report the problem. The check has to be able to fail while the scraper is silent.

## Storage model

    data/<system>/<YYYY>/<MM>/<YYYY-MM-DD>/<HHMMSS>Z.<k|d|s>.json.gz

`k` = keyframe (full state, first poll of each UTC day) · `d` = delta (changed
stations only) · `s` = snapshot (full, free-floating systems)

Files are immutable and append-only. Nothing is ever rewritten, so retried or
overlapping runs can't corrupt earlier data.

Reconstruct any moment by replaying the day's keyframe then applying deltas in
filename order — `consolidate.py` does this.

**A delta contains only stations whose *meaningful* state changed.** Two feed
quirks are normalized out before comparing, both found by noticing that "263 of
263 stations changed" on every single poll:

- `vehicle_types_available` comes back from Mobi in **nondeterministic order** —
  the same counts, permuted. It is sorted on capture so records are canonical.
- `last_reported` is a **heartbeat that advances every poll** whether or not
  availability moved, so it is excluded from the change comparison (though still
  stored for stations that do change).

Without these, every "delta" was a full snapshot under a misleading name — ~2.7 KB
instead of ~400 bytes — and, more damagingly, any downstream analysis of
rebalancing or change frequency would have concluded that every station changes
constantly. **Consequence to know when reading reconstructed data:**
`last_reported` reflects that station's last *meaningful* change, not the instant
of the poll.

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

### Lime rotates vehicle IDs every poll — verified, and it's a hard limit

Measured across consecutive Lime snapshots: **100% of `bike_id` values differ
every time**, as 36-character UUIDs. Not fleet turnover — a deliberate GBFS
privacy measure. Two consequences, both load-bearing:

1. **No vehicle can be followed across snapshots**, so trip reconstruction for
   Lime is not merely unreliable (as above) but *impossible in principle*. What
   the archive records is the supply-side spatial distribution at each instant.
   Anyone downstream assuming otherwise will produce nonsense.
2. **Delta encoding is impossible** — there are no stable keys to diff against —
   which is why Lime writes full snapshots while Mobi writes deltas, and why
   Lime dominates the storage budget.

This also tempers the case for very high-frequency sampling: since vehicles
can't be tracked anyway, faster polling sharpens the picture of *the
distribution* (rebalancing, demand peaks, how fast a curb empties) rather than
revealing movement.

For Mobi demand-side questions use the operator's trip files
(<https://www.mobibikes.ca/en/system-data>, 2017-present, hour-rounded
timestamps). Because that overlaps this archive from Aug 2023, trips and
availability can be joined — which is the interesting analysis.
