"""Small database helper layer.

One PostgreSQL transaction per request: the connection is committed in
teardown_appcontext on success and rolled back on an exception. This keeps
multi-statement administrative actions atomic without an ORM dependency.
"""
from flask import current_app, g
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(current_app.config["DATABASE_URL"])
    return g.db


def query(sql: str, params=None):
    """Return all matching rows as dicts."""
    with get_db().cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql: str, params=None):
    """Return a single matching row as a dict, or None."""
    with get_db().cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params=None):
    """Execute a statement and return the affected row, if any."""
    with get_db().cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone() if cur.description else None


def scalar(sql: str, params=None, default=0):
    row = query_one(sql, params)
    if not row:
        return default
    value = next(iter(row.values()))
    return default if value is None else value


def commit():
    if "db" in g:
        g.db.commit()


def rollback():
    if "db" in g:
        g.db.rollback()


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is None:
        return
    try:
        if exc is None:
            conn.commit()
        else:
            conn.rollback()
    finally:
        conn.close()
