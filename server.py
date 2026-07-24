"""FastAPI backend for CompStats — includes background scraper thread."""
from __future__ import annotations
import json, os, threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
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
ROOT = Path(__file__).parent


@app.get("/")
def index():
    return FileResponse(ROOT / "ui" / "index.html")


@app.get("/api/stats")
def stats():
    con = db.connect()
    n_matches = db.fetchone(con, "SELECT COUNT(*) as n FROM matches")["n"]
    n_maps    = db.fetchone(con, "SELECT COUNT(*) as n FROM map_results")["n"]
    tiers     = [dict(r) for r in db.fetchall(con,
        "SELECT tier, COUNT(*) as n FROM matches GROUP BY tier ORDER BY tier"
    )]
    return JSONResponse({"matches": n_matches, "map_results": n_maps, "tiers": tiers})


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



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8003))
    host = "0.0.0.0" if os.environ.get("DATABASE_URL") else "127.0.0.1"
    print(f"\nOpen: http://localhost:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
