"""Login, registration and logout."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .. import db, security
from ..validation import email as valid_email
from ..validation import text, username as valid_username

bp = Blueprint("auth", __name__)


def _safe_next(value: str) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return ""


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user:
        return redirect(url_for("member.dashboard") if g.current_user["role_name"] == "member" else url_for("admin.dashboard"))

    if request.method == "POST":
        identity = (request.form.get("identity") or "").strip().lower()
        password = request.form.get("password") or ""
        errors = []
        if not identity or not password:
            errors.append("Enter your username or email and password.")

        user = db.query_one(
            """SELECT u.*, r.name AS role_name FROM users u
                 JOIN roles r ON r.id = u.role_id
                WHERE lower(u.username) = %s OR u.email = %s""",
            (identity, identity),
        ) if not errors else None

        if user and user["locked_until"] and user["locked_until"] > datetime.now(timezone.utc):
            errors.append("Too many failed attempts. Try again in a few minutes.")

        if not errors:
            if user and security.verify_password(password, user["password_hash"]):
                if not user["is_active"]:
                    errors.append("This account is disabled. Contact an administrator.")
                else:
                    security.start_login_session(user["id"])
                    security.audit("auth.login", "user", user["id"], "Signed in")
                    flash("Signed in.", "ok")
                    next_url = _safe_next(request.form.get("next") or "")
                    if next_url:
                        return redirect(next_url)
                    return redirect(url_for("member.dashboard" if user["role_name"] == "member" else "admin.dashboard"))

            attempts = (user["failed_attempts"] if user else 0) + 1
            if user:
                locked_until = datetime.now(timezone.utc) + timedelta(minutes=15) if attempts >= 5 else None
                db.execute(
                    "UPDATE users SET failed_attempts = %s, locked_until = %s WHERE id = %s",
                    (attempts, locked_until, user["id"]),
                )
            errors.append("Invalid username/email or password.")

        for error in errors:
            flash(error, "bad")
    return render_template("auth/login.html", next_url=_safe_next(request.args.get("next", "")))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.current_user:
        return redirect(url_for("member.dashboard"))

    values = {
        "username": "",
        "email": "",
        "full_name": "",
        "student_id": "",
        "location": "",
    }
    if request.method == "POST":
        errors = []
        values = {key: request.form.get(key, "") for key in values}
        values["username"] = valid_username(values["username"], errors)
        values["email"] = valid_email(values["email"], errors)
        values["full_name"] = text(values["full_name"], "Full name", max_len=120, required=True, errors=errors)
        values["student_id"] = text(values["student_id"], "Student ID", max_len=40, errors=errors)
        values["location"] = text(values["location"], "Location", max_len=80, errors=errors)

        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not security.strong_enough(password):
            errors.append("Password: at least 10 characters, with letters and numbers.")
        if password != confirm:
            errors.append("Passwords do not match.")
        terms = request.form.get("terms")
        if not terms:
            errors.append("Confirm that the details are accurate.")

        if db.query_one("SELECT 1 FROM users WHERE lower(username) = %s", (values["username"],)):
            errors.append("That username is already taken.")
        if db.query_one("SELECT 1 FROM users WHERE email = %s", (values["email"],)):
            errors.append("That email is already registered.")

        if not errors:
            role_id = db.scalar("SELECT id FROM roles WHERE name = 'member'")
            user = db.execute(
                """INSERT INTO users (username, email, password_hash, role_id)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (values["username"], values["email"], security.hash_password(password), role_id),
            )
            db.execute(
                """INSERT INTO member_profiles (user_id, full_name, student_id, location, membership_status)
                   VALUES (%s, %s, %s, %s, 'pending')""",
                (user["id"], values["full_name"], values["student_id"], values["location"]),
            )
            security.audit("member.register", "user", user["id"], "Self-registration pending approval")
            flash("Account created. An administrator will review your membership.", "ok")
            return redirect(url_for("auth.login"))

        for error in errors:
            flash(error, "bad")
    return render_template("auth/register.html", values=values)


@bp.post("/logout")
def logout():
    if g.current_user:
        security.audit("auth.logout", "user", g.current_user["id"], "Signed out")
    security.end_login_session()
    flash("Signed out.", "ok")
    return redirect(url_for("auth.login"))
