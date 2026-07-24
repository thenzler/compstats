"""VLR.gg scraper — events → matches → map/agent/winner data."""
from __future__ import annotations
import re, time, json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from bs4 import BeautifulSoup

BASE = "https://www.vlr.gg"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) compstats-scraper/0.1"}
DELAY  = 1.5   # seconds between requests — be polite


def _get(path: str) -> BeautifulSoup:
    url = BASE + path if path.startswith("/") else path
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    time.sleep(DELAY)
    return BeautifulSoup(r.text, "html.parser")


# ── Tier classification ───────────────────────────────────────────────────────

def classify_tier(event_name: str) -> str:
    name = event_name.upper()
    if "GAME CHANGERS" in name:  return "GC"
    if "VCT" in name and "CHALLENGERS" not in name: return "T1"
    if "CHALLENGERS" in name:    return "T2"
    return "T3"


# ── Round data parser ────────────────────────────────────────────────────────

def _parse_rounds(game_el) -> dict | None:
    """
    Parse per-round attack/defense data from .vlr-rounds-row-col columns.
    Each round column has two .rnd-sq divs (team A top, team B bottom).
    Classes: mod-win = winner, mod-t = T-side (attack), mod-ct = CT-side (defense).
    Returns dict with score/atk/def/pistol fields, or None if no round data.
    """
    cols = game_el.select(".vlr-rounds-row-col")
    if len(cols) < 2:
        return None

    score_a = score_b = 0
    a_atk = a_def = b_atk = b_def = 0
    pistol1_atk = pistol2_atk = None

    for col in cols[1:]:  # first col is team label
        sqs = col.select(".rnd-sq")
        if len(sqs) < 2:
            continue
        cls_a = set(sqs[0].get("class") or [])
        cls_b = set(sqs[1].get("class") or [])
        a_won = "mod-win" in cls_a
        b_won = "mod-win" in cls_b
        if not a_won and not b_won:
            continue  # unused OT slot

        num_el = col.select_one(".rnd-num")
        rnd_num = int(num_el.get_text(strip=True)) if num_el else 0

        if a_won:
            score_a += 1
            t_won = "mod-t" in cls_a
            if t_won:                 a_atk += 1
            elif "mod-ct" in cls_a:   a_def += 1
        else:
            score_b += 1
            t_won = "mod-t" in cls_b
            if t_won:                 b_atk += 1
            elif "mod-ct" in cls_b:   b_def += 1

        if rnd_num == 1:   pistol1_atk = 1 if t_won else 0
        elif rnd_num == 13: pistol2_atk = 1 if t_won else 0

    if score_a + score_b == 0:
        return None

    return {
        "score_a": score_a, "score_b": score_b,
        "a_atk_wins": a_atk, "a_def_wins": a_def,
        "b_atk_wins": b_atk, "b_def_wins": b_def,
        "pistol1_atk": pistol1_atk, "pistol2_atk": pistol2_atk,
    }


def parse_match_rounds(match_id: str) -> list[dict] | None:
    """Re-scrape match page for round data only (no agent re-parsing)."""
    soup = _get(f"/{match_id}")
    results = []
    for game_el in soup.select(".vm-stats-game[data-game-id]"):
        map_span = game_el.select_one(".map span")
        map_name = map_span.contents[0].strip() if map_span else ""
        if not map_name:
            continue
        rd = _parse_rounds(game_el)
        if rd:
            results.append({"map": map_name, **rd})
    return results or None


# ── Match page parser ─────────────────────────────────────────────────────────

def parse_match(match_id: str) -> dict | None:
    """
    Returns {
        id, event_name, tier, date, team_a, team_b,
        maps: [{map, agents_a: [5], agents_b: [5], winner: 'A'|'B'|None}]
    }
    or None if the match has no completed maps.
    """
    soup = _get(f"/{match_id}")

    # ── Event name
    event_el = soup.select_one(".match-header-event div[style]")
    event_name = event_el.get_text(strip=True) if event_el else ""
    tier = classify_tier(event_name)

    # ── Date
    date_el = soup.select_one(".match-header-date .moment-tz-convert")
    date = date_el.get("data-utc-ts", "") if date_el else ""

    # ── Team names (left=A, right=B)
    team_els = soup.select(".match-header-vs .wf-title-med")
    teams = [el.get_text(strip=True) for el in team_els]
    if len(teams) < 2:
        return None
    team_a, team_b = teams[0], teams[1]

    # ── Per-map data
    maps = []
    for game_el in soup.select(".vm-stats-game[data-game-id]"):
        # Map name
        map_span = game_el.select_one(".map span")
        map_name = map_span.contents[0].strip() if map_span else ""
        if not map_name:
            continue

        # Winner: team with .score.mod-win
        win_score = game_el.select_one(".score.mod-win")
        if not win_score:
            continue  # map not played yet

        win_side = "A" if "mod-right" not in (win_score.parent.get("class") or []) else "B"

        # Agent lists — two .ovw-table blocks, one per team
        ovw_tables = game_el.select(".ovw-table")
        if len(ovw_tables) < 2:
            continue

        def _agents(table) -> list[str]:
            return [
                img["src"].split("/")[-1].replace(".png", "")
                for img in table.select("img")
                if "/game/agents/" in img.get("src", "")
            ]

        agents_a = _agents(ovw_tables[0])
        agents_b = _agents(ovw_tables[1])
        if len(agents_a) != 5 or len(agents_b) != 5:
            continue

        rounds = _parse_rounds(game_el)
        maps.append({
            "map": map_name, "agents_a": agents_a, "agents_b": agents_b,
            "winner": win_side, **(rounds or {})
        })

    if not maps:
        return None

    return dict(id=str(match_id), event_name=event_name, tier=tier,
                date=date, team_a=team_a, team_b=team_b, maps=maps)


# ── Event match list ──────────────────────────────────────────────────────────

def match_ids_for_event(event_id: str) -> list[str]:
    """Return all match IDs for a VLR event."""
    soup = _get(f"/event/matches/{event_id}/")
    ids = []
    for a in soup.select("a.match-item"):
        href = a.get("href", "")
        m = re.match(r"/(\d+)/", href)
        if m:
            ids.append(m.group(1))
    return ids


# ── Event listing ─────────────────────────────────────────────────────────────

def event_ids(completed: bool = True) -> list[tuple[str, str]]:
    """Return [(event_id, event_name)] from the VLR events page."""
    path = "/events" + ("?series_id=all&status=0" if completed else "")
    soup = _get(path)
    results = []
    for a in soup.select("a.event-item"):
        href = a.get("href", "")
        m = re.match(r"/event/(\d+)/", href)
        if not m:
            continue
        eid = m.group(1)
        name_el = a.select_one(".event-item-title")
        name = name_el.get_text(strip=True) if name_el else ""
        results.append((eid, name))
    return results


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import db

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    p_match = sub.add_parser("match", help="Scrape a single match by ID")
    p_match.add_argument("match_id")

    p_event = sub.add_parser("event", help="Scrape all matches in an event")
    p_event.add_argument("event_id")

    p_events = sub.add_parser("events", help="List recent events")
    sub.add_parser("refresh-rounds", help="Backfill atk/def round data for all scraped matches")

    args = parser.parse_args()
    con = db.connect()

    if args.cmd == "match":
        result = parse_match(args.match_id)
        if result:
            db.insert_match(con, match_id=result["id"], **{k: result[k] for k in result if k not in ("maps","id")}, maps=result["maps"])
            print(f"Saved match {args.match_id}: {len(result['maps'])} maps")
        else:
            print("No completed maps found.")

    elif args.cmd == "event":
        ids = match_ids_for_event(args.event_id)
        print(f"Found {len(ids)} matches")
        for mid in ids:
            if db.already_scraped(con, mid):
                print(f"  skip {mid}")
                continue
            result = parse_match(mid)
            if result:
                db.insert_match(con, match_id=result["id"], **{k: result[k] for k in result if k not in ("maps","id")}, maps=result["maps"])
                print(f"  saved {mid}: {result['team_a']} vs {result['team_b']} ({len(result['maps'])} maps)")
            else:
                print(f"  skip {mid} (no completed maps)")

    elif args.cmd == "events":
        for eid, name in event_ids():
            print(f"{eid:>8}  {classify_tier(name):3}  {name}")

    elif args.cmd == "refresh-rounds":
        rows = con.execute("SELECT id FROM matches").fetchall()
        ids = [r[0] for r in rows]
        print(f"Refreshing round data for {len(ids)} matches…")
        ok = skipped = 0
        for mid in ids:
            if not db.needs_round_refresh(con, mid):
                skipped += 1
                continue
            result = parse_match_rounds(mid)
            if result:
                db.update_map_rounds(con, mid, result)
                ok += 1
                print(f"  updated {mid} ({len(result)} maps)")
            else:
                print(f"  skip    {mid} (no round data)")
        print(f"Done: {ok} updated, {skipped} already had data.")
