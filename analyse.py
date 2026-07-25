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


def _build_clause(tiers, map_name, seasons=None, regions=None):
    params = []
    clauses = []
    if tiers:
        clauses.append(f"m.tier IN ({','.join(['?']*len(tiers))})")
        params.extend(tiers)
    if seasons:
        clauses.append(f"m.season IN ({','.join(['?']*len(seasons))})")
        params.extend(seasons)
    if regions:
        clauses.append(f"m.region IN ({','.join(['?']*len(regions))})")
        params.extend(regions)
    tier_clause = (" AND " + " AND ".join(clauses)) if clauses else ""
    map_clause = ""
    if map_name:
        map_clause = "AND mr.map_name = ?"
        params.append(map_name)
    return tier_clause, map_clause, params


def comp_winrates(map_name=None, tiers=None, seasons=None, regions=None):
    con = db.connect()
    tier_clause, map_clause, params = _build_clause(tiers, map_name, seasons, regions)
    rows = db.fetchall(con, f"""
        SELECT mr.map_name, mr.agents_a, mr.agents_b, mr.winner,
               mr.a_atk_wins, mr.a_def_wins, mr.b_atk_wins, mr.b_def_wins,
               m.team_a, m.team_b
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE 1=1 {tier_clause} {map_clause}
    """, params)

    # [wins, total, atk_wins, atk_rounds, def_wins, def_rounds, nm_wins, nm_total]
    stats: dict[tuple, list] = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0, 0])
    agent_counts: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    lineup_stats: dict[tuple, dict] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    team_stats: dict[tuple, dict] = defaultdict(lambda: defaultdict(lambda: [0, 0]))

    for row in rows:
        d = dict(row)
        a_atk = d.get("a_atk_wins") or 0
        a_def = d.get("a_def_wins") or 0
        b_atk = d.get("b_atk_wins") or 0
        b_def = d.get("b_def_wins") or 0
        have_rounds = (a_atk + a_def + b_atk + b_def) > 0

        agents_a = json.loads(d["agents_a"])
        agents_b = json.loads(d["agents_b"])
        comp_a = classify_comp(agents_a)
        comp_b = classify_comp(agents_b)

        for side, winner, agents, comp, opp, team in [
            ("agents_a", "A", agents_a, comp_a, comp_b, d.get("team_a") or ""),
            ("agents_b", "B", agents_b, comp_b, comp_a, d.get("team_b") or ""),
        ]:
            key = (comp, d["map_name"])
            s = stats[key]
            s[1] += 1
            won = d["winner"] == winner
            if won:
                s[0] += 1

            if have_rounds:
                if side == "agents_a":
                    s[2] += a_atk;       s[3] += a_atk + b_def
                    s[4] += a_def;       s[5] += a_def + b_atk
                else:
                    s[2] += b_atk;       s[3] += b_atk + a_def
                    s[4] += b_def;       s[5] += b_def + a_atk

            if comp != opp:
                s[7] += 1
                if won:
                    s[6] += 1

            for agent in agents:
                agent_counts[key][agent] += 1

            lineup = tuple(sorted(agents))
            lineup_stats[key][lineup][1] += 1
            if won:
                lineup_stats[key][lineup][0] += 1

            if team:
                team_stats[key][team][1] += 1
                if won:
                    team_stats[key][team][0] += 1

    result = []
    for (comp, map_n), s in stats.items():
        wins, total, atk_w, atk_r, def_w, def_r, nm_wins, nm_total = s
        result.append({
            "comp": comp, "map": map_n, "wins": wins, "total": total,
            "win_pct":    round(wins / total * 100, 1) if total else 0,
            "atk_wins":   atk_w,  "atk_rounds": atk_r,
            "def_wins":   def_w,  "def_rounds":  def_r,
            "atk_wr":     round(atk_w / atk_r * 100, 1) if atk_r else None,
            "def_wr":     round(def_w / def_r * 100, 1) if def_r else None,
            "nm_total":   nm_total,
            "nm_wins":    nm_wins,
            "nm_win_pct": round(nm_wins / nm_total * 100, 1) if nm_total else None,
            "mirror_matches": (total - nm_total) // 2,
            "agents":     dict(sorted(agent_counts[(comp, map_n)].items(), key=lambda x: -x[1])),
            "lineups":    sorted(
                [{"agents": list(lu), "wins": w, "total": t,
                  "win_pct": round(w / t * 100, 1) if t else 0}
                 for lu, (w, t) in lineup_stats[(comp, map_n)].items()],
                key=lambda x: -x["total"]
            )[:10],
            "teams": sorted(
                [{"team": tm, "wins": w, "total": t,
                  "win_pct": round(w / t * 100, 1) if t else 0}
                 for tm, (w, t) in team_stats[(comp, map_n)].items()],
                key=lambda x: -x["total"]
            )[:20],
        })
    return sorted(result, key=lambda r: -r["total"])


def comp_matchups(comp: str, map_name=None, tiers=None, seasons=None, regions=None):
    """Win/loss record of comp against each different opponent comp (min 3 games)."""
    con = db.connect()
    tier_clause, map_clause, params = _build_clause(tiers, map_name, seasons, regions)
    rows = db.fetchall(con, f"""
        SELECT mr.agents_a, mr.agents_b, mr.winner
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE 1=1 {tier_clause} {map_clause}
    """, params)
    matchups: dict[str, list] = defaultdict(lambda: [0, 0])
    for row in rows:
        d = dict(row)
        agents_a = json.loads(d["agents_a"])
        agents_b = json.loads(d["agents_b"])
        comp_a = classify_comp(agents_a)
        comp_b = classify_comp(agents_b)
        if comp_a == comp:
            opp, won = comp_b, d["winner"] == "A"
        elif comp_b == comp:
            opp, won = comp_a, d["winner"] == "B"
        else:
            continue
        if opp == comp:
            continue
        matchups[opp][1] += 1
        if won:
            matchups[opp][0] += 1
    return sorted(
        [{"opp": o, "wins": w, "total": t, "win_pct": round(w / t * 100, 1) if t else 0}
         for o, (w, t) in matchups.items() if t >= 3],
        key=lambda x: -x["total"]
    )


def agent_pickrates(map_name=None, tiers=None, seasons=None, regions=None):
    con = db.connect()
    tier_clause, map_clause, params = _build_clause(tiers, map_name, seasons, regions)
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


def team_stats(team_name: str, tiers=None, seasons=None, regions=None):
    """All maps played by a team: comp used, map, win/loss, agents, opponent."""
    con = db.connect()
    tier_clause, _, params_t = _build_clause(tiers, None, seasons, regions)
    rows = db.fetchall(con, f"""
        SELECT mr.map_name, mr.agents_a, mr.agents_b, mr.winner,
               m.team_a, m.team_b, m.event_name, m.tier, m.date, m.id as match_id,
               mr.a_atk_wins, mr.a_def_wins, mr.b_atk_wins, mr.b_def_wins
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE (m.team_a = ? OR m.team_b = ?) {tier_clause}
        ORDER BY m.date DESC
    """, [team_name, team_name] + params_t)

    maps = []
    agent_counts = defaultdict(int)
    comp_counts  = defaultdict(lambda: [0, 0])  # comp -> [wins, total]
    map_counts   = defaultdict(lambda: [0, 0])  # map  -> [wins, total]

    for row in rows:
        d = dict(row)
        is_a = d["team_a"] == team_name
        side  = "A" if is_a else "B"
        opp   = d["team_b"] if is_a else d["team_a"]
        won   = d["winner"] == side
        agents = json.loads(d["agents_a"] if is_a else d["agents_b"])
        comp   = classify_comp(agents)

        for ag in agents:
            agent_counts[ag] += 1
        comp_counts[comp][1]      += 1
        if won: comp_counts[comp][0] += 1
        map_counts[d["map_name"]][1]      += 1
        if won: map_counts[d["map_name"]][0] += 1

        atk_w = (d["a_atk_wins"] or 0) if is_a else (d["b_atk_wins"] or 0)
        def_w = (d["a_def_wins"] or 0) if is_a else (d["b_def_wins"] or 0)

        maps.append({
            "match_id":  d["match_id"],
            "map":       d["map_name"],
            "event":     d["event_name"],
            "tier":      d["tier"],
            "date":      d["date"],
            "opponent":  opp,
            "comp":      comp,
            "agents":    agents,
            "won":       won,
            "atk_wins":  atk_w,
            "def_wins":  def_w,
        })

    total = len(maps)
    wins  = sum(1 for m in maps if m["won"])
    return {
        "team":     team_name,
        "total":    total,
        "wins":     wins,
        "win_pct":  round(wins / total * 100, 1) if total else 0,
        "maps_played": [
            {"map": mn, "wins": s[0], "total": s[1],
             "win_pct": round(s[0]/s[1]*100,1) if s[1] else 0}
            for mn, s in sorted(map_counts.items(), key=lambda x: -x[1][1])
        ],
        "comps": [
            {"comp": c, "wins": s[0], "total": s[1],
             "win_pct": round(s[0]/s[1]*100,1) if s[1] else 0}
            for c, s in sorted(comp_counts.items(), key=lambda x: -x[1][1])
        ],
        "agents": dict(sorted(agent_counts.items(), key=lambda x: -x[1])),
        "recent_maps": maps[:40],
    }


def agent_synergy(map_name=None, tiers=None, seasons=None, regions=None):
    """Co-occurrence and win rate for every agent pair."""
    con = db.connect()
    tier_clause, map_clause, params = _build_clause(tiers, map_name, seasons, regions)
    rows = db.fetchall(con, f"""
        SELECT mr.agents_a, mr.agents_b, mr.winner
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE 1=1 {tier_clause} {map_clause}
    """, params)

    pairs: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for row in rows:
        d = dict(row)
        for side, winner in [("agents_a", "A"), ("agents_b", "B")]:
            agents = json.loads(d[side])
            won = d["winner"] == winner
            for i in range(len(agents)):
                for j in range(i + 1, len(agents)):
                    pair = tuple(sorted([agents[i], agents[j]]))
                    pairs[pair][1] += 1
                    if won:
                        pairs[pair][0] += 1

    result = []
    for (a1, a2), (w, t) in pairs.items():
        if t < 5:
            continue
        result.append({
            "a1": a1, "a2": a2,
            "picks": t, "wins": w,
            "win_pct": round(w / t * 100, 1) if t else 0
        })
    return sorted(result, key=lambda x: -x["picks"])


def comp_trends(tiers=None, seasons=None, regions=None):
    """Weekly pick rate and win rate for each comp. Returns last 12 weeks."""
    import re as _re
    con = db.connect()
    tier_clause, _, params = _build_clause(tiers, None, seasons, regions)
    rows = db.fetchall(con, f"""
        SELECT mr.agents_a, mr.agents_b, mr.winner, m.date
        FROM map_results mr JOIN matches m ON m.id = mr.match_id
        WHERE m.date IS NOT NULL AND m.date != '' {tier_clause}
        ORDER BY m.date
    """, params)

    week_totals: dict[str, int] = defaultdict(int)
    week_comp: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: [0, 0]))

    for row in rows:
        d = dict(row)
        date_str = str(d["date"] or "")[:10]
        if not _re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            continue
        from datetime import date as _date
        try:
            dt = _date.fromisoformat(date_str)
        except Exception:
            continue
        week = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"

        for side, winner in [("agents_a", "A"), ("agents_b", "B")]:
            agents = json.loads(d[side])
            comp = classify_comp(agents)
            won = d["winner"] == winner
            week_totals[week] += 1
            week_comp[week][comp][1] += 1
            if won:
                week_comp[week][comp][0] += 1

    all_comp_totals: dict[str, int] = defaultdict(int)
    for week, comps in week_comp.items():
        for comp, (w, t) in comps.items():
            all_comp_totals[comp] += t
    top_comps = [c for c, _ in sorted(all_comp_totals.items(), key=lambda x: -x[1])[:10]]

    weeks = sorted(week_totals.keys())[-12:]
    return {
        "weeks": weeks,
        "comps": [
            {
                "comp": comp,
                "data": [
                    {
                        "week": w,
                        "pick_rate": round(week_comp[w][comp][1] / week_totals[w] * 100, 1) if week_totals[w] else 0,
                        "win_pct":   round(week_comp[w][comp][0] / week_comp[w][comp][1] * 100, 1) if week_comp[w][comp][1] else None,
                        "total":     week_comp[w][comp][1],
                    }
                    for w in weeks
                ]
            }
            for comp in top_comps
        ]
    }


def team_search(query: str, limit: int = 15):
    """Find team names matching a query string."""
    con = db.connect()
    like = f"%{query}%"
    try:
        rows = db.fetchall(con,
            "SELECT DISTINCT team_a as name FROM matches WHERE team_a ILIKE ? "
            "UNION SELECT DISTINCT team_b as name FROM matches WHERE team_b ILIKE ? "
            "ORDER BY name LIMIT ?",
            [like, like, limit])
    except Exception:
        rows = db.fetchall(con,
            "SELECT DISTINCT team_a as name FROM matches WHERE LOWER(team_a) LIKE LOWER(?) "
            "UNION SELECT DISTINCT team_b as name FROM matches WHERE LOWER(team_b) LIKE LOWER(?) "
            "ORDER BY name LIMIT ?",
            [like, like, limit])
    return [r["name"] for r in rows]


def map_meta_stats(tiers=None, seasons=None, regions=None):
    """Per-map: total, avg_rounds, atk_wr, pistol_atk_wr, a_wins."""
    con = db.connect()
    tier_clause, _, params = _build_clause(tiers, None, seasons, regions)
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
