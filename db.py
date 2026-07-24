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

_ROUND_COLS = [
    ("score_a",     "INTEGER"),
    ("score_b",     "INTEGER"),
    ("a_atk_wins",  "INTEGER"),
    ("a_def_wins",  "INTEGER"),
    ("b_atk_wins",  "INTEGER"),
    ("b_def_wins",  "INTEGER"),
    ("pistol1_atk", "INTEGER"),
    ("pistol2_atk", "INTEGER"),
]


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
            winner      TEXT,
            score_a     INTEGER,
            score_b     INTEGER,
            a_atk_wins  INTEGER,
            a_def_wins  INTEGER,
            b_atk_wins  INTEGER,
            b_def_wins  INTEGER,
            pistol1_atk INTEGER,
            pistol2_atk INTEGER
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mr_map  ON map_results(map_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_m_tier  ON matches(tier)")
        # Migration: add columns if they don't exist yet
        for col, typ in _ROUND_COLS:
            try:
                cur.execute(f"ALTER TABLE map_results ADD COLUMN {col} {typ}")
            except Exception:
                pass  # column already exists
    con.commit()


def _init_sqlite(con) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS matches (
        id TEXT PRIMARY KEY, event_name TEXT, tier TEXT,
        date TEXT, team_a TEXT, team_b TEXT
    );
    CREATE TABLE IF NOT EXISTS map_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT REFERENCES matches(id),
        map_name TEXT, agents_a TEXT, agents_b TEXT, winner TEXT,
        score_a INTEGER, score_b INTEGER,
        a_atk_wins INTEGER, a_def_wins INTEGER,
        b_atk_wins INTEGER, b_def_wins INTEGER,
        pistol1_atk INTEGER, pistol2_atk INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_mr_map  ON map_results(map_name);
    CREATE INDEX IF NOT EXISTS idx_m_tier  ON matches(tier);
    """)
    # Migration: add columns to existing DB if missing
    existing = {row[1] for row in con.execute("PRAGMA table_info(map_results)").fetchall()}
    for col, typ in _ROUND_COLS:
        if col not in existing:
            con.execute(f"ALTER TABLE map_results ADD COLUMN {col} {typ}")
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


def _round_vals(m: dict) -> tuple:
    return (
        m.get("score_a"), m.get("score_b"),
        m.get("a_atk_wins"), m.get("a_def_wins"),
        m.get("b_atk_wins"), m.get("b_def_wins"),
        m.get("pistol1_atk"), m.get("pistol2_atk"),
    )


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
                    """INSERT INTO map_results
                       (match_id,map_name,agents_a,agents_b,winner,
                        score_a,score_b,a_atk_wins,a_def_wins,b_atk_wins,b_def_wins,pistol1_atk,pistol2_atk)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (match_id, m["map"], json.dumps(m["agents_a"]), json.dumps(m["agents_b"]), m["winner"],
                     *_round_vals(m))
                )
    else:
        con.execute("INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?)",
                    (match_id, event_name, tier, date, team_a, team_b))
        for m in maps:
            con.execute(
                """INSERT INTO map_results
                   (match_id,map_name,agents_a,agents_b,winner,
                    score_a,score_b,a_atk_wins,a_def_wins,b_atk_wins,b_def_wins,pistol1_atk,pistol2_atk)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (match_id, m["map"], json.dumps(m["agents_a"]), json.dumps(m["agents_b"]), m["winner"],
                 *_round_vals(m))
            )
    con.commit()


def update_map_rounds(con, match_id: str, rounds: list[dict]) -> None:
    """Update round data for existing map_results rows (used by refresh-rounds)."""
    sql = _q("""UPDATE map_results SET
        score_a=?, score_b=?,
        a_atk_wins=?, a_def_wins=?,
        b_atk_wins=?, b_def_wins=?,
        pistol1_atk=?, pistol2_atk=?
        WHERE match_id=? AND map_name=?""")
    if _USE_PG:
        with con.cursor() as cur:
            for r in rounds:
                cur.execute(sql, (*_round_vals(r), match_id, r["map"]))
    else:
        for r in rounds:
            con.execute(sql, (*_round_vals(r), match_id, r["map"]))
    con.commit()


def needs_round_refresh(con, match_id: str) -> bool:
    """True if any map_results row for this match is missing round data."""
    row = _fetchone(con,
        "SELECT 1 FROM map_results WHERE match_id=? AND a_atk_wins IS NOT NULL LIMIT 1",
        (match_id,))
    return not bool(row)


def already_scraped(con, match_id: str) -> bool:
    row = _fetchone(con, "SELECT 1 FROM matches WHERE id=?", (match_id,))
    return bool(row)


def fetchall(con, sql: str, params=()):
    return _fetchall(con, sql, params)


def fetchone(con, sql: str, params=()):
    return _fetchone(con, sql, params)
