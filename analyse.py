"""Comp win-rate analysis queries."""
from __future__ import annotations
import json
from collections import defaultdict

import db

ARCHETYPES = {
    "sentinel":   {"sage", "cypher", "killjoy", "chamber", "deadlock", "vyse"},
    "duelist":    {"jett", "raze", "phoenix", "neon", "reyna", "yoru", "iso", "waylay"},
    "initiator":  {"sova", "breach", "skye", "fade", "kayo", "gekko", "tejo"},
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
        SELECT mr.map_name, mr.agents_a, mr.agents_b, mr.winner,
               mr.a_atk_wins, mr.a_def_wins, mr.b_atk_wins, mr.b_def_wins
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE 1=1 {tier_clause} {map_clause}
    """, params)

    # [wins, total, atk_wins, atk_rounds, def_wins, def_rounds]
    stats: dict[tuple, list] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])

    for row in rows:
        d = dict(row)
        a_atk = d.get("a_atk_wins") or 0
        a_def = d.get("a_def_wins") or 0
        b_atk = d.get("b_atk_wins") or 0
        b_def = d.get("b_def_wins") or 0
        have_rounds = (a_atk + a_def + b_atk + b_def) > 0

        for side, winner in [("agents_a", "A"), ("agents_b", "B")]:
            agents = json.loads(d[side])
            comp = classify_comp(agents)
            key = (comp, d["map_name"])
            s = stats[key]
            s[1] += 1
            if d["winner"] == winner:
                s[0] += 1

            if have_rounds:
                if side == "agents_a":
                    # A played atk for a_atk+b_def rounds, def for a_def+b_atk rounds
                    s[2] += a_atk
                    s[3] += a_atk + b_def
                    s[4] += a_def
                    s[5] += a_def + b_atk
                else:
                    s[2] += b_atk
                    s[3] += b_atk + a_def
                    s[4] += b_def
                    s[5] += b_def + a_atk

    result = []
    for (comp, map_n), (wins, total, atk_w, atk_r, def_w, def_r) in stats.items():
        result.append({
            "comp": comp, "map": map_n, "wins": wins, "total": total,
            "win_pct":   round(wins / total * 100, 1) if total else 0,
            "atk_wins":  atk_w,  "atk_rounds": atk_r,
            "def_wins":  def_w,  "def_rounds":  def_r,
            "atk_wr":    round(atk_w / atk_r * 100, 1) if atk_r else None,
            "def_wr":    round(def_w / def_r * 100, 1) if def_r else None,
        })
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


def map_meta_stats(tiers=None):
    """Per-map: total, avg_rounds, atk_wr, pistol_atk_wr, a_wins."""
    con = db.connect()
    tier_clause, _, params = _build_clause(tiers, None)
    rows = db.fetchall(con, f"""
        SELECT mr.map_name, mr.winner,
               mr.score_a, mr.score_b,
               mr.a_atk_wins, mr.b_atk_wins,
               mr.pistol1_atk, mr.pistol2_atk
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE 1=1 {tier_clause}
    """, params)

    stats = defaultdict(lambda: {
        "total": 0, "a_wins": 0,
        "total_rounds": 0, "atk_wins": 0, "maps_w_rounds": 0,
        "pistol_atk_wins": 0, "pistol_count": 0,
    })

    for row in rows:
        d = dict(row)
        m = d["map_name"]
        s = stats[m]
        s["total"] += 1
        s["a_wins"] += 1 if d["winner"] == "A" else 0

        sa = d.get("score_a") or 0
        sb = d.get("score_b") or 0
        if sa + sb > 0:
            s["total_rounds"]  += sa + sb
            s["atk_wins"]      += (d.get("a_atk_wins") or 0) + (d.get("b_atk_wins") or 0)
            s["maps_w_rounds"] += 1

        for p in ("pistol1_atk", "pistol2_atk"):
            v = d.get(p)
            if v is not None:
                s["pistol_atk_wins"] += v
                s["pistol_count"]    += 1

    result = []
    for map_name, s in stats.items():
        n = s["total"]; nr = s["maps_w_rounds"]
        result.append({
            "map":          map_name,
            "total":        n,
            "a_wins":       s["a_wins"],
            "b_wins":       n - s["a_wins"],
            "atk_wr":       round(s["atk_wins"] / s["total_rounds"] * 100, 1) if s["total_rounds"] else None,
            "avg_rounds":   round(s["total_rounds"] / nr, 1) if nr else None,
            "pistol_atk_wr": round(s["pistol_atk_wins"] / s["pistol_count"] * 100, 1) if s["pistol_count"] else None,
        })
    return sorted(result, key=lambda r: -r["total"])
