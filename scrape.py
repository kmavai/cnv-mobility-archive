#!/usr/bin/env python3
"""
Poll GBFS feeds and append immutable snapshots to data/.

Design notes (these encode lessons from how the existing public archive broke):

1. AUTO-DISCOVERY, NEVER HARDCODED FEED URLS.
   The main public GBFS archive silently lost its Vancouver series because its
   config still pointed at Mobi's retired Smoove endpoint after the operator
   migrated hosts. We resolve every feed from the system's gbfs.json each run,
   so a host migration is followed automatically rather than silently dropped.

2. FAIL LOUDLY.
   That same archive kept running for 100+ other systems while Vancouver
   returned nothing, for a year, unnoticed. A system that yields zero records
   here exits non-zero so the scheduler surfaces it.

3. IMMUTABLE APPEND-ONLY FILES.
   One new file per poll. Nothing is ever rewritten, so concurrent or retried
   runs cannot corrupt earlier data and git stores clean additions.

4. KEYFRAME + DELTA for station systems.
   A full snapshot at the first poll of each UTC day, deltas thereafter. Cuts
   storage ~10x versus full snapshots while remaining fully reconstructable:
   replay the day's keyframe then apply deltas in filename order.
"""
import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
DATA = ROOT / "data"
STATE = ROOT / "state"
UA = "cnv-mobility-archive/1.0 (civic research; contact via repo)"
TIMEOUT = 30
RETRIES = 3


def get_json(url):
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - we want to retry anything transient
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET failed after {RETRIES} attempts: {url}: {last}")


def discover(discovery_url):
    """Resolve feed name -> url from a GBFS auto-discovery document.

    Handles both the language-keyed 2.x shape and the flat 3.x shape.
    """
    doc = get_json(discovery_url)
    data = doc.get("data", {})
    if "feeds" in data:
        feeds = data["feeds"]
    else:
        # 2.x: {"data": {"en": {"feeds": [...]}}} - take the first language.
        first = next(iter(data.values()))
        feeds = first["feeds"]
    return {f["name"]: f["url"] for f in feeds}


def pick(feeds, *candidates):
    """Return the first feed url present, tolerating 2.x/3.x renames."""
    for name in candidates:
        if name in feeds:
            return feeds[name]
    return None


def station_records(feeds):
    status_url = pick(feeds, "station_status")
    if not status_url:
        return [], {}
    doc = get_json(status_url)
    stations = doc.get("data", {}).get("stations", [])

    # station_information changes rarely; capture it in the daily keyframe only.
    info = {}
    info_url = pick(feeds, "station_information")
    if info_url:
        try:
            idoc = get_json(info_url)
            for s in idoc.get("data", {}).get("stations", []):
                info[str(s.get("station_id"))] = {
                    "name": s.get("name"),
                    "lat": s.get("lat"),
                    "lon": s.get("lon"),
                    "capacity": s.get("capacity"),
                }
        except Exception as e:  # noqa: BLE001
            print(f"  warn: station_information failed: {e}", file=sys.stderr)

    keep = (
        "station_id", "num_bikes_available", "num_docks_available",
        "num_bikes_disabled", "num_docks_disabled", "is_installed",
        "is_renting", "is_returning", "last_reported",
    )
    out = []
    for s in stations:
        rec = {k: s.get(k) for k in keep if k in s}
        types = s.get("vehicle_types_available") or s.get("num_bikes_available_types")
        if types:
            rec["vehicle_types_available"] = types
        out.append(rec)
    return out, info


def free_floating_records(feeds):
    url = pick(feeds, "free_bike_status", "vehicle_status", "bike_status")
    if not url:
        return []
    doc = get_json(url)
    data = doc.get("data", {})
    bikes = data.get("bikes") or data.get("vehicles") or []
    out = []
    for b in bikes:
        lat, lon = b.get("lat"), b.get("lon")
        out.append({
            "id": b.get("bike_id") or b.get("vehicle_id"),
            # 5 dp ~ 1m. Deliberately NOT truncated further: this is a supply-side
            # record of publicly-visible parked vehicles, and coarser rounding
            # would destroy the curb-level analysis this exists to support.
            "lat": round(lat, 5) if isinstance(lat, (int, float)) else lat,
            "lon": round(lon, 5) if isinstance(lon, (int, float)) else lon,
            "is_reserved": b.get("is_reserved"),
            "is_disabled": b.get("is_disabled"),
            "vehicle_type_id": b.get("vehicle_type_id"),
            "current_range_meters": b.get("current_range_meters"),
        })
    return out


def load_state(system_id):
    p = STATE / f"{system_id}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save_state(system_id, state):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / f"{system_id}.json").write_text(json.dumps(state, separators=(",", ":")))


def write_snapshot(system_id, now, kind, payload):
    d = DATA / system_id / now.strftime("%Y") / now.strftime("%m") / now.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now.strftime('%H%M%S')}Z.{kind}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return path


def run_system(system, now):
    sid = system["id"]
    print(f"[{sid}] discovering feeds...")
    feeds = discover(system["discovery"])
    print(f"[{sid}] feeds: {sorted(feeds)}")

    day_dir = DATA / sid / now.strftime("%Y") / now.strftime("%m") / now.strftime("%Y-%m-%d")
    first_of_day = not day_dir.exists() or not any(day_dir.glob("*.k.json.gz"))

    if system["kind"] == "station":
        records, info = station_records(feeds)
        if not records:
            raise RuntimeError(f"{sid}: station_status returned zero stations")

        prev = load_state(sid)
        curr = {str(r.get("station_id")): r for r in records}

        if first_of_day:
            payload = {"ts": now.isoformat(), "type": "keyframe",
                       "stations": records, "station_information": info}
            p = write_snapshot(sid, now, "k", payload)
            print(f"[{sid}] keyframe: {len(records)} stations -> {p.name}")
        else:
            changed = [r for k, r in curr.items() if prev.get(k) != r]
            gone = [k for k in prev if k not in curr]
            if changed or gone:
                payload = {"ts": now.isoformat(), "type": "delta",
                           "changed": changed, "removed": gone}
                p = write_snapshot(sid, now, "d", payload)
                print(f"[{sid}] delta: {len(changed)} changed, {len(gone)} removed -> {p.name}")
            else:
                print(f"[{sid}] no change; nothing written")
        save_state(sid, curr)
        return len(records)

    records = free_floating_records(feeds)
    if not records:
        raise RuntimeError(f"{sid}: no free-floating vehicles returned "
                           "(feed shape changed, or system not operating?)")
    payload = {"ts": now.isoformat(), "type": "snapshot", "vehicles": records}
    p = write_snapshot(sid, now, "s", payload)
    print(f"[{sid}] snapshot: {len(records)} vehicles -> {p.name}")
    return len(records)


def main():
    cfg = json.loads((ROOT / "systems.json").read_text())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    only = sys.argv[1] if len(sys.argv) > 1 else None

    failures = []
    for system in cfg["systems"]:
        if only and system["id"] != only:
            continue
        try:
            run_system(system, now)
        except Exception as e:  # noqa: BLE001
            print(f"[{system['id']}] FAILED: {e}", file=sys.stderr)
            failures.append(system["id"])

    if failures:
        # Non-zero exit so the scheduler raises this instead of silently
        # continuing for the systems that still work.
        print(f"\nFAILED SYSTEMS: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)
    print("\nok")


if __name__ == "__main__":
    main()
