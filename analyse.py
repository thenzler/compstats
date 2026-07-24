"""Comp win-rate analysis queries."""
from __future__ import annotations
import json
from collections import defaultdict

import db

ARCHETYPES = {
    "sentinel":   {"sage", "cypher", "killjoy", "chamber", "deadlock", "vyse"},
    "duelist":    {"jett", "raze", "phoenix", "neon", "reyna", "yoru", "iso", "waylay"},
    "initiator":  {"sova", "breach", "skye", "fade", "kayo", "gecko", "tejo"},
    "controller": {"viper", "omen", "brimstone", "astra", "harbor", "clove"},
}


def classify_comp(agents: list[str]) -> str:
    counts = defaultdict(int)
    for a in agents:
        for arch, members in ARCHETYPES.items():
            if a.lower() in members:
                counts[arch] += 1
                break
    s = counts["sentinel"]; d = counts["duelist"]
    i = counts["initiator"]; c = counts["controller"]
    return f"{s}s-{d}d-{i}i-{c}c"


def _build_clause(tiers, map_name):
    params = []
    tier_clause = map_clause = ""
    if tiers:
        tier_clause = f"AND m.tier IN ({','.join(['?']*len(tiers))})"
        params.extend(tiers)
    if map_name:
        map_clause = "AND mr.map_name = ?"
        params.append(map_name)
    return tier_clause, map_clause, params


def comp_winrates(map_name=None, tiers=None):
    con = db.connect()
    tier_clause, map_clause, params = _build_clause(tiers, map_name)
    rows = db.fetchall(con, f"""
        SELECT mr.map_name, mr.agents_a, mr.agents_b, mr.winner
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE 1=1 {tier_clause} {map_clause}
    """, params)

    stats: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for row in rows:
        for side, winner in [("agents_a", "A"), ("agents_b", "B")]:
            agents = json.loads(row[side] if not hasattr(row, '__getitem__') else row[side])
            comp = classify_comp(agents)
            key = (comp, row["map_name"])
            stats[key][1] += 1
            if row["winner"] == winner:
                stats[key][0] += 1

    result = []
    for (comp, map_n), (wins, total) in stats.items():
        result.append({"comp": comp, "map": map_n, "wins": wins, "total": total,
                       "win_pct": round(wins / total * 100, 1) if total else 0})
    return sorted(result, key=lambda r: -r["total"])


def agent_pickrates(map_name=None, tiers=None):
    con = db.connect()
    tier_clause, map_clause, params = _build_clause(tiers, map_name)
    rows = db.fetchall(con, f"""
        SELECT mr.map_name, mr.agents_a, mr.agents_b, mr.winner
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE 1=1 {tier_clause} {map_clause}
    """, params)

    stats: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for row in rows:
        for side, winner in [("agents_a", "A"), ("agents_b", "B")]:
            agents = json.loads(row[side])
            won = row["winner"] == winner
            for agent in agents:
                key = (agent, row["map_name"])
                stats[key][0] += 1
                if won:
                    stats[key][1] += 1

    result = []
    for (agent, map_n), (picks, wins) in stats.items():
        result.append({"agent": agent, "map": map_n, "picks": picks, "wins": wins,
                       "win_pct": round(wins / picks * 100, 1) if picks else 0})
    return sorted(result, key=lambda r: -r["picks"])
