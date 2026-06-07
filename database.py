"""EUREKAI Database — SQLite for local, PostgreSQL for cloud."""
import os
import json
import logging
from contextlib import contextmanager
from typing import Optional

import config

logger = logging.getLogger("ergovision.db")

# ── Database Selection ──────────────────────────────────────────
_uses_postgres = bool(config.DATABASE_URL)

if _uses_postgres:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    logger.info("Using PostgreSQL: %s", config.DATABASE_URL.split("@")[-1])
else:
    import sqlite3
    logger.info("Using SQLite: %s", config.SQLITE_PATH)
    os.makedirs(os.path.dirname(config.SQLITE_PATH), exist_ok=True)


def _get_conn():
    """Get a database connection."""
    if _uses_postgres:
        return psycopg2.connect(config.DATABASE_URL)
    return sqlite3.connect(config.SQLITE_PATH, check_same_thread=False)


# ── Schema ──────────────────────────────────────────────────────

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS analyses (
    id SERIAL PRIMARY KEY,
    lens TEXT,
    filename TEXT,
    filepath TEXT,
    file_size INTEGER DEFAULT 0,
    duration REAL DEFAULT 0,
    fps REAL DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    status TEXT DEFAULT 'uploaded',
    pose_data TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evidence (
    id SERIAL PRIMARY KEY,
    analysis_id INTEGER REFERENCES analyses(id),
    image_path TEXT,
    frame_number INTEGER DEFAULT 0,
    timestamp REAL DEFAULT 0,
    rula_score INTEGER,
    reba_score INTEGER,
    safety_score REAL DEFAULT 50,
    label TEXT,
    risk_level TEXT DEFAULT 'medium',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _init_sqlite():
    """SQLite-compatible schema (no SERIAL, no TIMESTAMP type)."""
    return _INIT_SQL.replace("SERIAL", "INTEGER").replace(" TIMESTAMP ", " TEXT ")


def init_db():
    """Initialize database tables."""
    sql = _INIT_SQL if _uses_postgres else _init_sqlite()
    conn = _get_conn()
    try:
        for stmt in sql.strip().split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.commit()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error("DB init error: %s", e)
    finally:
        conn.close()


# ── Analysis CRUD ───────────────────────────────────────────────

def insert_analysis(lens: str, filename: str, filepath: str,
                    file_size: int = 0, duration: float = 0,
                    fps: float = 0, width: int = 0, height: int = 0) -> int:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO analyses (lens, filename, filepath, file_size, duration, fps, width, height, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'uploaded') RETURNING id"
            if _uses_postgres else
            "INSERT INTO analyses (lens, filename, filepath, file_size, duration, fps, width, height, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uploaded')",
            (lens, filename, filepath, file_size, duration, fps, width, height)
        )
        if _uses_postgres:
            row_id = cur.fetchone()[0]
        else:
            row_id = cur.lastrowid
        conn.commit()
        logger.info("Inserted analysis id=%s lens=%s", row_id, lens)
        return row_id
    except Exception as e:
        logger.error("Insert analysis error: %s", e)
        conn.rollback()
        return -1
    finally:
        conn.close()


def get_analysis(aid: int) -> Optional[dict]:
    conn = _get_conn()
    try:
        if _uses_postgres:
            cur = conn.cursor(cursor_factory=RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
        cur.execute("SELECT * FROM analyses WHERE id = %s" if _uses_postgres else
                    "SELECT * FROM analyses WHERE id = ?", (aid,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("Get analysis error: %s", e)
        return None
    finally:
        conn.close()


def update_analysis(aid: int, status: str = None, pose_data: str = None,
                    metadata: dict = None):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        if status:
            cur.execute("UPDATE analyses SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
                        if _uses_postgres else
                        "UPDATE analyses SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (status, aid))
        if pose_data:
            cur.execute("UPDATE analyses SET pose_data = %s WHERE id = %s"
                        if _uses_postgres else
                        "UPDATE analyses SET pose_data = ? WHERE id = ?",
                        (pose_data, aid))
        if metadata:
            meta_str = json.dumps(metadata) if isinstance(metadata, dict) else str(metadata)
            cur.execute("UPDATE analyses SET metadata = %s WHERE id = %s"
                        if _uses_postgres else
                        "UPDATE analyses SET metadata = ? WHERE id = ?",
                        (meta_str, aid))
        conn.commit()
    except Exception as e:
        logger.error("Update analysis error: %s", e)
        conn.rollback()
    finally:
        conn.close()


def mark_failed(aid: int, error: str = ""):
    """Mark analysis as failed with error message."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE analyses SET status = 'failed', metadata = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
                    if _uses_postgres else
                    "UPDATE analyses SET status = 'failed', metadata = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps({"error": error}), aid))
        conn.commit()
    except Exception as e:
        logger.error("Mark failed error: %s", e)
        conn.rollback()
    finally:
        conn.close()


def list_analyses(limit: int = 50) -> list:
    conn = _get_conn()
    try:
        if _uses_postgres:
            cur = conn.cursor(cursor_factory=RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
        cur.execute("SELECT * FROM analyses ORDER BY created_at DESC LIMIT %s"
                    if _uses_postgres else
                    "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?",
                    (limit,))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("List analyses error: %s", e)
        return []
    finally:
        conn.close()


# ── Evidence CRUD ───────────────────────────────────────────────

def insert_evidence(analysis_id: int, image_path: str = "",
                    frame_number: int = 0, timestamp: float = 0,
                    rula_score: int = None, reba_score: int = None,
                    safety_score: float = 50, label: str = "",
                    risk_level: str = "medium"):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO evidence (analysis_id, image_path, frame_number, timestamp, "
            "rula_score, reba_score, safety_score, label, risk_level) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            if _uses_postgres else
            "INSERT INTO evidence (analysis_id, image_path, frame_number, timestamp, "
            "rula_score, reba_score, safety_score, label, risk_level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (analysis_id, image_path, frame_number, timestamp,
             rula_score, reba_score, safety_score, label, risk_level)
        )
        conn.commit()
    except Exception as e:
        logger.error("Insert evidence error: %s", e)
        conn.rollback()
    finally:
        conn.close()


def get_evidence_for_analysis(aid: int) -> list:
    conn = _get_conn()
    try:
        if _uses_postgres:
            cur = conn.cursor(cursor_factory=RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
        cur.execute("SELECT * FROM evidence WHERE analysis_id = %s ORDER BY frame_number"
                    if _uses_postgres else
                    "SELECT * FROM evidence WHERE analysis_id = ? ORDER BY frame_number",
                    (aid,))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("Get evidence error: %s", e)
        return []
    finally:
        conn.close()


# ── Init ────────────────────────────────────────────────────────
init_db()
logger.info("Database ready at %s", config.DATABASE_URL or config.SQLITE_PATH)
