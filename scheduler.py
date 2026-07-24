"""
Auto-scraper scheduler — runs daily, discovers all current events,
scrapes new matches only (duplicates are always skipped).

Usage:
    python scheduler.py              # run once now + loop every 24h
    python scheduler.py --once       # run once and exit
    python scheduler.py --interval 6 # run every 6 hours

Add to Windows startup:
    Task Scheduler → Create Basic Task → "CompStats Scraper"
    Action: python.exe  "C:\...\compstats\scheduler.py"
"""
from __future__ import annotations
import argparse, os, time, sys
from datetime import datetime

import db, scraper


TIER_WHITELIST = {"T1", "T2", "T3", "GC"}   # set to {"T1"} to only scrape pro
DEFAULT_INTERVAL_H = 24


def run_once() -> tuple[int, int]:
    """Scrape all current events. Returns (new_matches, skipped)."""
    con = db.connect()
    new = skipped = 0

    max_pages = int(os.environ.get("SCRAPE_MAX_PAGES", "100"))
    print(f"\n[{datetime.now():%Y-%m-%d %H:%M}] Fetching event list (max_pages={max_pages})…")
    try:
        events = scraper.event_ids(completed=True, max_pages=max_pages) + scraper.event_ids(completed=False, max_pages=max_pages)
    except Exception as e:
        print(f"  ERROR fetching events: {e}")
        return 0, 0

    seen_events: set[str] = set()
    for eid, name in events:
        if eid in seen_events:
            continue
        seen_events.add(eid)
        tier = scraper.classify_tier(name)
        if tier not in TIER_WHITELIST:
            continue

        try:
            match_ids = scraper.match_ids_for_event(eid)
        except Exception as e:
            print(f"  event {eid} ({name}): ERROR — {e}")
            continue

        event_new = 0
        for mid in match_ids:
            if db.already_scraped(con, mid):
                skipped += 1
                continue
            try:
                result = scraper.parse_match(mid)
            except Exception as e:
                print(f"    match {mid}: ERROR — {e}")
                continue
            if result:
                db.insert_match(
                    con,
                    match_id=result["id"],
                    **{k: result[k] for k in result if k not in ("maps", "id")},
                    maps=result["maps"]
                )
                event_new += 1
                new += 1

        if event_new:
            print(f"  {tier:2} {name}: +{event_new} matches")

    n_matches = db.fetchone(con, "SELECT COUNT(*) as n FROM matches")["n"]
    n_maps    = db.fetchone(con, "SELECT COUNT(*) as n FROM map_results")["n"]
    print(f"  Done. DB: {n_matches} matches · {n_maps} map results  (+{new} new, {skipped} skipped)")
    return new, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_H,
                        help="Hours between runs (default 24)")
    args = parser.parse_args()

    run_once()
    if args.once:
        return

    interval_s = args.interval * 3600
    while True:
        print(f"\nSleeping {args.interval}h until next run…")
        time.sleep(interval_s)
        run_once()


if __name__ == "__main__":
    main()
