"""Database helpers — Postgres in production, SQLite locally."""
from __future__ import annotations
import json, os
from pathlib import Path

# ── Backend selection ─────────────────────────────────────────────────────────
# Set DATABASE_URL env var for Postgres (Railway sets this automatically).
# Falls back to local SQLite when not set.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_USE_PG = bool(DATABASE_URL)

if _USE_PG:
    import psycopg2
    import psycopg2.extras
else:
    import sqlite3
    _DB_PATH = Path(__file__).parent / "data" / "compstats.db"
    _DB_PATH.parent.mkdir(exist_ok=True)


# ── Connection ────────────────────────────────────────────────────────────────

def connect():
    if _USE_PG:
        con = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        _init_pg(con)
        return con
    else:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        _init_sqlite(con)
        return con


def _q(sql: str) -> str:
    """Convert ? placeholders to %s for Postgres."""
    return sql.replace("?", "%s") if _USE_PG else sql


# ── Schema init ───────────────────────────────────────────────────────────────

def _init_pg(con) -> None:
    with con.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id          TEXT PRIMARY KEY,
            event_name  TEXT,
            tier        TEXT,
            date        TEXT,
            team_a      TEXT,
            team_b      TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS map_results (
            id          SERIAL PRIMARY KEY,
            match_id    TEXT REFERENCES matches(id),
            map_name    TEXT,
            agents_a    TEXT,
            agents_b    TEXT,
            winner      TEXT
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mr_map  ON map_results(map_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_m_tier  ON matches(tier)")
    con.commit()


def _init_sqlite(con) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS matches (
        id TEXT PRIMARY KEY, event_name TEXT, tier TEXT,
        date TEXT, team_a TEXT, team_b TEXT
    );
    CREATE TABLE IF NOT EXISTS map_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT REFERENCES matches(id),
        map_name TEXT, agents_a TEXT, agents_b TEXT, winner TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_mr_map  ON map_results(map_name);
    CREATE INDEX IF NOT EXISTS idx_m_tier  ON matches(tier);
    """)
    con.commit()


# ── Queries ───────────────────────────────────────────────────────────────────

def _exec(con, sql: str, params=()):
    if _USE_PG:
        cur = con.cursor()
        cur.execute(_q(sql), params)
        return cur
    else:
        return con.execute(_q(sql), params)


def _fetchone(con, sql: str, params=()):
    return _exec(con, sql, params).fetchone()


def _fetchall(con, sql: str, params=()):
    return _exec(con, sql, params).fetchall()


def insert_match(con, match_id: str, event_name: str, tier: str,
                 date: str, team_a: str, team_b: str, maps: list[dict]) -> None:
    if _USE_PG:
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO matches VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (match_id, event_name, tier, date, team_a, team_b)
            )
            for m in maps:
                cur.execute(
                    "INSERT INTO map_results (match_id,map_name,agents_a,agents_b,winner) VALUES (%s,%s,%s,%s,%s)",
                    (match_id, m["map"], json.dumps(m["agents_a"]), json.dumps(m["agents_b"]), m["winner"])
                )
    else:
        con.execute("INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?)",
                    (match_id, event_name, tier, date, team_a, team_b))
        for m in maps:
            con.execute(
                "INSERT INTO map_results (match_id,map_name,agents_a,agents_b,winner) VALUES (?,?,?,?,?)",
                (match_id, m["map"], json.dumps(m["agents_a"]), json.dumps(m["agents_b"]), m["winner"])
            )
    con.commit()


def already_scraped(con, match_id: str) -> bool:
    row = _fetchone(con, "SELECT 1 FROM matches WHERE id=?", (match_id,))
    return bool(row)


def fetchall(con, sql: str, params=()):
    return _fetchall(con, sql, params)


def fetchone(con, sql: str, params=()):
    return _fetchone(con, sql, params)
