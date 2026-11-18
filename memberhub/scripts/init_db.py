#!/usr/bin/env python3
"""Create the PostgreSQL database (if needed) and apply the schema.

Usage:
    python3 scripts/init_db.py
"""
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
from psycopg2 import sql

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from memberhub.config import Config  # noqa: E402

SCHEMA = BASE_DIR / "migrations" / "001_init.sql"


def ensure_database(url: str) -> None:
    parsed = urlparse(url)
    dbname = parsed.path.lstrip("/") or "sgbl_member_hub"
    maintenance_url = (
        f"{parsed.scheme}:///postgres" if not parsed.netloc
        else urlunparse(parsed._replace(path="/postgres"))
    )
    conn = psycopg2.connect(maintenance_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if not cur.fetchone():
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
                print(f"Created database {dbname}.")
            else:
                print(f"Database {dbname} already exists.")
    finally:
        conn.close()


def apply_schema(url: str) -> None:
    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA.read_text(encoding="utf-8"))
        print("Schema applied successfully (idempotent).")
    finally:
        conn.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else Config.DATABASE_URL
    ensure_database(target)
    apply_schema(target)
