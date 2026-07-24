"""FastAPI backend for CompStats — includes background scraper thread."""
from __future__ import annotations
import json, os, threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

import db, analyse

app = FastAPI()
ROOT = Path(__file__).parent


@app.get("/")
def index():
    return FileResponse(ROOT / "ui" / "index.html")


@app.get("/api/stats")
def stats():
    con = db.connect()
    n_matches = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    n_maps    = con.execute("SELECT COUNT(*) FROM map_results").fetchone()[0]
    tiers     = [dict(r) for r in con.execute(
        "SELECT tier, COUNT(*) as n FROM matches GROUP BY tier ORDER BY tier"
    ).fetchall()]
    return JSONResponse({"matches": n_matches, "map_results": n_maps, "tiers": tiers})


@app.get("/api/maps/list")
def maps_list(tiers: str = ""):
    con = db.connect()
    tier_list = [t.strip() for t in tiers.split(",") if t.strip()]
    if tier_list:
        rows = con.execute(
            f"SELECT DISTINCT mr.map_name FROM map_results mr "
            f"JOIN matches m ON m.id=mr.match_id "
            f"WHERE m.tier IN ({','.join('?'*len(tier_list))}) "
            f"ORDER BY mr.map_name",
            tier_list
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT DISTINCT map_name FROM map_results ORDER BY map_name"
        ).fetchall()
    return JSONResponse([r[0] for r in rows])


@app.get("/api/comps")
def comps(map: str = "", tiers: str = "", min_sample: int = 10):
    tier_list = [t.strip() for t in tiers.split(",") if t.strip()] or None
    rows = analyse.comp_winrates(
        map_name=map or None,
        tiers=tier_list
    )
    rows = [r for r in rows if r["total"] >= min_sample]
    return JSONResponse(rows)


@app.get("/api/agents")
def agents(map: str = "", tiers: str = "", min_sample: int = 5):
    tier_list = [t.strip() for t in tiers.split(",") if t.strip()] or None
    rows = analyse.agent_pickrates(
        map_name=map or None,
        tiers=tier_list
    )
    rows = [r for r in rows if r["picks"] >= min_sample]
    return JSONResponse(rows)


@app.get("/api/maps/meta")
def maps_meta(tiers: str = ""):
    """Per-map stats: total, avg_rounds, atk_wr, pistol_atk_wr."""
    tier_list = [t.strip() for t in tiers.split(",") if t.strip()] or None
    rows = analyse.map_meta_stats(tiers=tier_list)
    return JSONResponse(rows)


@app.on_event("startup")
def start_scheduler():
    import scheduler as sched
    interval_h = float(os.environ.get("SCRAPE_INTERVAL_H", "24"))
    def _loop():
        import time
        sched.run_once()
        while True:
            time.sleep(interval_h * 3600)
            sched.run_once()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8003))
    host = "0.0.0.0" if os.environ.get("DATABASE_URL") else "127.0.0.1"
    print(f"\nOpen: http://localhost:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
