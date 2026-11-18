#!/usr/bin/env python3
"""Create the first administrator account (or reset an existing one).

Usage:
    python3 scripts/create_admin.py
Environment (optional, avoids prompts):
    ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME
"""
import getpass
import os
import sys
from pathlib import Path

import psycopg2

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from memberhub.config import Config  # noqa: E402
from memberhub.security import hash_password, strong_enough  # noqa: E402


def main() -> None:
    username = os.environ.get("ADMIN_USERNAME", "").strip() or input("Admin username: ").strip()
    email = (os.environ.get("ADMIN_EMAIL", "").strip() or input("Admin email: ").strip()).lower()
    full_name = os.environ.get("ADMIN_NAME", "").strip() or input("Admin full name: ").strip()
    password = os.environ.get("ADMIN_PASSWORD", "") or getpass.getpass("Temporary password: ")

    if not strong_enough(password):
        sys.exit("Password must be at least 10 characters with letters and numbers.")

    conn = psycopg2.connect(Config.DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE lower(username)=%s", (username,))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE users SET password_hash=%s, role_id=(SELECT id FROM roles WHERE name='admin'), is_active=TRUE WHERE id=%s",
                    (hash_password(password), existing[0]),
                )
                cur.execute(
                    "UPDATE member_profiles SET membership_status='active', verified_at=now() WHERE user_id=%s",
                    (existing[0],),
                )
                print(f"Existing account @{username} promoted to administrator.")
            else:
                cur.execute(
                    """INSERT INTO users (username, email, password_hash, role_id)
                       VALUES (%s, %s, %s, (SELECT id FROM roles WHERE name='admin')) RETURNING id""",
                    (username, email, hash_password(password)),
                )
                user_id = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO member_profiles (user_id, full_name, membership_status, verified_at)
                       VALUES (%s, %s, 'active', now())""",
                    (user_id, full_name),
                )
                print(f"Administrator @{username} created (id={user_id}).")
            cur.execute(
                "INSERT INTO audit_logs (actor_id, action, target_type, target_id, details) VALUES (NULL, 'admin.bootstrap', 'user', %s, 'CLI administrator setup')",
                (username,),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
