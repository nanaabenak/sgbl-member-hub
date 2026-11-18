"""SGBL Member Hub application factory."""
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, g, render_template, request, send_from_directory, session

from . import db, security
from .config import config_from_env


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or config_from_env())

    @app.before_request
    def _load_user_and_csrf():
        security.load_current_user()
        security.check_csrf()

    @app.after_request
    def _security_headers(response):
        if app.config.get("SESSION_COOKIE_SECURE") or request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https:; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    @app.teardown_appcontext
    def _close_db(exc=None):
        db.close_db(exc)

    @app.context_processor
    def _template_globals():
        user = getattr(g, "current_user", None)
        return {
            "csrf_token": security.csrf_token,
            "current_user": user,
            "is_admin": bool(user and user["role_name"] == "admin"),
            "club_name": app.config["CLUB_NAME"],
            "card_url": app.config["BUILDER_CARD_URL"],
            "now_utc": lambda: datetime.now(timezone.utc),
        }

    @app.template_filter("dt")
    def _format_dt(value, fmt="%d %b %Y, %H:%M"):
        if not value:
            return "—"
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.strftime(fmt)

    @app.template_filter("pct")
    def _pct(part, total):
        return round((float(part) / float(total)) * 100) if total else 0

    @app.errorhandler(403)
    def _forbidden(error):
        return render_template("errors/403.html", message=error.description), 403

    @app.errorhandler(404)
    def _not_found(error):
        return render_template("errors/404.html"), 404

    @app.get("/health")
    def health():
        return {"ok": True, "service": "sgbl-member-hub"}, 200

    # In production Nginx serves /card/ directly from a copy of the original
    # Builder Card site. This alias makes the same link work in local dev.
    builder_card_dir = Path(__file__).resolve().parents[2] / "AWSBuildersBadge---UMaT"

    @app.get("/card/")
    @app.get("/card/<path:filename>")
    def builder_card(filename="index.html"):
        if not builder_card_dir.is_dir():
            abort(404)
        return send_from_directory(builder_card_dir, filename)

    from .blueprints import admin, auth, meetup, member

    app.register_blueprint(auth.bp)
    app.register_blueprint(member.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(meetup.bp)

    return app
