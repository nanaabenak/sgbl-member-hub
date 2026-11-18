"""Authentication, CSRF, RBAC and audit helpers."""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlencode

import bcrypt
from flask import abort, current_app, g, redirect, request, session, url_for
from werkzeug.exceptions import BadRequest

from . import db


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def strong_enough(password: str) -> bool:
    return len(password) >= 10 and any(c.isalpha() for c in password) and any(c.isdigit() for c in password)


# ---------------------------------------------------------------------------
# Identifiers and IP handling
# ---------------------------------------------------------------------------
def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_ip() -> str:
    """Store a salted hash instead of a raw IP address (data minimisation)."""
    addr = request.remote_addr or ""
    if not addr:
        return ""
    return hmac.new(current_app.config["SECRET_KEY"].encode(), addr.encode(), hashlib.sha256).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# Current user / web sessions
# ---------------------------------------------------------------------------
def load_current_user() -> None:
    """Run before every request. Validates the server-side session record."""
    g.current_user = None
    g.web_session = None

    sid = session.get("sid")
    if not sid:
        if "anon_csrf" not in session:
            session["anon_csrf"] = new_token()
        return

    row = db.query_one(
        """SELECT ws.id AS session_id, ws.csrf_token, ws.last_seen_at, ws.expires_at,
                  u.*, r.name AS role_name
             FROM web_sessions ws
             JOIN users u ON u.id = ws.user_id
             JOIN roles r ON r.id = u.role_id
            WHERE ws.sid_hash = %s""",
        (sha256(sid),),
    )
    if not row:
        session.clear()
        session["anon_csrf"] = new_token()
        return

    now = datetime.now(timezone.utc)
    idle_limit = current_app.config["SESSION_IDLE_TIMEOUT_SECONDS"]
    if row["expires_at"] <= now or (now - row["last_seen_at"]).total_seconds() > idle_limit:
        db.execute("DELETE FROM web_sessions WHERE id = %s", (row["session_id"],))
        session.clear()
        session["anon_csrf"] = new_token()
        return

    if not row["is_active"]:
        session.clear()
        session["anon_csrf"] = new_token()
        return

    db.execute("UPDATE web_sessions SET last_seen_at = now() WHERE id = %s", (row["session_id"],))
    g.web_session = row
    g.current_user = row


def start_login_session(user_id: int) -> None:
    sid = new_token()
    csrf = new_token()
    lifetime = current_app.config["PERMANENT_SESSION_LIFETIME_SECONDS"]
    db.execute(
        """INSERT INTO web_sessions (user_id, sid_hash, csrf_token, ip_hash, user_agent, expires_at)
           VALUES (%s, %s, %s, %s, %s, now() + %s * interval '1 second')""",
        (
            user_id,
            sha256(sid),
            csrf,
            hash_ip(),
            request.headers.get("User-Agent", "")[:250],
            lifetime,
        ),
    )
    db.execute(
        "UPDATE users SET last_login_at = now(), failed_attempts = 0, locked_until = NULL WHERE id = %s",
        (user_id,),
    )
    session.clear()
    session["sid"] = sid
    session.permanent = True


def end_login_session() -> None:
    if g.web_session:
        db.execute("DELETE FROM web_sessions WHERE id = %s", (g.web_session["session_id"],))
    session.clear()
    session["anon_csrf"] = new_token()


def csrf_token() -> str:
    if g.web_session:
        return g.web_session["csrf_token"]
    if "anon_csrf" not in session:
        session["anon_csrf"] = new_token()
    return session["anon_csrf"]


def check_csrf() -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = csrf_token()
    if not supplied or not hmac.compare_digest(str(supplied), str(expected)):
        current_app.logger.warning("Rejected request with invalid CSRF token: %s %s", request.method, request.path)
        abort(403, description="Invalid or missing CSRF token. Please reload the page and try again.")


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.current_user:
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login") + "?" + urlencode({"next": next_url}))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.current_user["role_name"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def has_permission(name: str) -> bool:
    if not g.current_user:
        return False
    row = db.query_one(
        """SELECT 1 FROM role_permissions rp
             JOIN permissions p ON p.id = rp.permission_id
            WHERE rp.role_id = %s AND p.name = %s""",
        (g.current_user["role_id"], name),
    )
    return row is not None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def audit(action: str, target_type: str = "", target_id="", details: str = "") -> None:
    actor = g.current_user["id"] if g.current_user else None
    db.execute(
        """INSERT INTO audit_logs (actor_id, action, target_type, target_id, details, ip_hash)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (actor, action, target_type, str(target_id) if target_id is not None else "", details[:1000], hash_ip()),
    )


def db_error(exc: Exception):
    """Translate constraint violations into a friendly form error."""
    raise BadRequest("The submitted information could not be saved. Check it and try again.") from exc
