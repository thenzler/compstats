"""FastAPI backend for CompStats — includes background scraper thread."""
from __future__ import annotations
import json, os, threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

import db, analyse


@asynccontextmanager
async def lifespan(app: FastAPI):
    import scheduler as sched
    interval_h = float(os.environ.get("SCRAPE_INTERVAL_H", "24"))
    def _loop():
        import time
        sched.run_once()
        while True:
            time.sleep(interval_h * 3600)
            sched.run_once()
    threading.Thread(target=_loop, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
ROOT = Path(__file__).parent


@app.get("/")
def index():
    return FileResponse(ROOT / "ui" / "index.html")


@app.get("/api/stats")
def stats(tiers: str = "", seasons: str = "", regions: str = ""):
    con = db.connect()
    tier_l = _lst(tiers); season_l = _lst(seasons); region_l = _lst(regions)
    # build clauses for matches table (no prefix) and for join queries (m. prefix)
    bare, prefixed, params = [], [], []
    if tier_l:
        ph = ','.join(['?'] * len(tier_l))
        bare.append(f"tier IN ({ph})"); prefixed.append(f"m.tier IN ({ph})")
        params.extend(tier_l)
    if season_l:
        ph = ','.join(['?'] * len(season_l))
        bare.append(f"season IN ({ph})"); prefixed.append(f"m.season IN ({ph})")
        params.extend(season_l)
    if region_l:
        ph = ','.join(['?'] * len(region_l))
        bare.append(f"region IN ({ph})"); prefixed.append(f"m.region IN ({ph})")
        params.extend(region_l)
    m_where  = ("WHERE " + " AND ".join(bare))      if bare      else ""
    mr_where = ("WHERE " + " AND ".join(prefixed))  if prefixed  else ""
    n_matches = db.fetchone(con, f"SELECT COUNT(*) as n FROM matches {m_where}", params)["n"]
    n_maps    = db.fetchone(con,
        f"SELECT COUNT(*) as n FROM map_results mr JOIN matches m ON m.id=mr.match_id {mr_where}",
        params)["n"]
    tier_rows = [dict(r) for r in db.fetchall(con,
        f"SELECT tier, COUNT(*) as n FROM matches {m_where} GROUP BY tier ORDER BY tier", params)]
    return JSONResponse({"matches": n_matches, "map_results": n_maps, "tiers": tier_rows})


@app.get("/api/maps/list")
def maps_list(tiers: str = ""):
    con = db.connect()
    tier_list = [t.strip() for t in tiers.split(",") if t.strip()]
    if tier_list:
        rows = db.fetchall(con,
            f"SELECT DISTINCT mr.map_name FROM map_results mr "
            f"JOIN matches m ON m.id=mr.match_id "
            f"WHERE m.tier IN ({','.join(['?']*len(tier_list))}) "
            f"ORDER BY mr.map_name",
            tier_list
        )
    else:
        rows = db.fetchall(con, "SELECT DISTINCT map_name FROM map_results ORDER BY map_name")
    return JSONResponse([r["map_name"] for r in rows])


def _lst(s: str):
    return [x.strip() for x in s.split(",") if x.strip()] or None


@app.get("/api/filters")
def filters():
    con = db.connect()
    seasons = [r["season"] for r in db.fetchall(con,
        "SELECT DISTINCT season FROM matches WHERE season IS NOT NULL ORDER BY season DESC"
    )]
    regions = [r["region"] for r in db.fetchall(con,
        "SELECT DISTINCT region FROM matches WHERE region IS NOT NULL ORDER BY region"
    )]
    return JSONResponse({"seasons": seasons, "regions": regions})


@app.get("/api/teams")
def teams_logos():
    con = db.connect()
    rows = db.fetchall(con, "SELECT name, logo_url FROM teams WHERE logo_url IS NOT NULL AND logo_url != ''")
    return JSONResponse({r["name"]: r["logo_url"] for r in rows})


@app.get("/api/comps")
def comps(map: str = "", tiers: str = "", seasons: str = "", regions: str = "", min_sample: int = 10):
    rows = analyse.comp_winrates(
        map_name=map or None, tiers=_lst(tiers), seasons=_lst(seasons), regions=_lst(regions)
    )
    rows = [r for r in rows if r["total"] >= min_sample]
    return JSONResponse(rows)


@app.get("/api/comp/matchups")
def comp_matchups_ep(comp: str, map: str = "", tiers: str = "", seasons: str = "", regions: str = ""):
    rows = analyse.comp_matchups(comp, map_name=map or None, tiers=_lst(tiers), seasons=_lst(seasons), regions=_lst(regions))
    return JSONResponse(rows)


@app.get("/api/agents")
def agents(map: str = "", tiers: str = "", seasons: str = "", regions: str = "", min_sample: int = 5):
    rows = analyse.agent_pickrates(
        map_name=map or None, tiers=_lst(tiers), seasons=_lst(seasons), regions=_lst(regions)
    )
    rows = [r for r in rows if r["picks"] >= min_sample]
    return JSONResponse(rows)


@app.get("/api/maps/meta")
def maps_meta(tiers: str = "", seasons: str = "", regions: str = ""):
    """Per-map stats: total, avg_rounds, atk_wr, pistol_atk_wr."""
    rows = analyse.map_meta_stats(tiers=_lst(tiers), seasons=_lst(seasons), regions=_lst(regions))
    return JSONResponse(rows)


@app.get("/api/team")
def team_ep(name: str, tiers: str = "", seasons: str = "", regions: str = ""):
    result = analyse.team_stats(name, tiers=_lst(tiers), seasons=_lst(seasons), regions=_lst(regions))
    return JSONResponse(result)

@app.get("/api/team/search")
def team_search_ep(q: str = ""):
    if len(q) < 2:
        return JSONResponse([])
    return JSONResponse(analyse.team_search(q))

@app.get("/api/synergy")
def synergy_ep(map: str = "", tiers: str = "", seasons: str = "", regions: str = ""):
    rows = analyse.agent_synergy(map_name=map or None, tiers=_lst(tiers), seasons=_lst(seasons), regions=_lst(regions))
    return JSONResponse(rows)

@app.get("/api/trends")
def trends_ep(tiers: str = "", seasons: str = "", regions: str = ""):
    data = analyse.comp_trends(tiers=_lst(tiers), seasons=_lst(seasons), regions=_lst(regions))
    return JSONResponse(data)



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8003))
    host = "0.0.0.0" if os.environ.get("DATABASE_URL") else "127.0.0.1"
    print(f"\nOpen: http://localhost:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
