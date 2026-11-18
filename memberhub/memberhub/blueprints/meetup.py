"""Tracked Meetup redirects.

A click is ALWAYS recorded as a click. It never creates an RSVP or attendance
record: those are separate, administrator-controlled metrics.
"""
from flask import Blueprint, abort, g, redirect, render_template

from .. import db, security

bp = Blueprint("meetup", __name__)


def _redirect(session, link, user_id, identified_by):
    db.execute(
        """INSERT INTO meetup_clicks (session_id, link_id, user_id, identified_by, ip_hash)
           VALUES (%s, %s, %s, %s, %s)""",
        (session["id"], link["id"], user_id, identified_by, security.hash_ip()),
    )
    response = redirect(session["meetup_url"], code=302)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@bp.get("/meetup/<int:session_id>")
def aggregate_redirect(session_id: int):
    session = db.query_one("SELECT * FROM club_sessions WHERE id = %s AND status <> 'cancelled'", (session_id,))
    if not session or not session["meetup_url"]:
        return render_template("meetup/unavailable.html", session=session), 404

    link = db.query_one(
        "SELECT * FROM meetup_links WHERE session_id = %s AND kind = 'aggregate' ORDER BY id LIMIT 1",
        (session_id,),
    )
    if not link:
        link = db.execute(
            "INSERT INTO meetup_links (session_id, kind) VALUES (%s, 'aggregate') RETURNING *",
            (session_id,),
        )

    user_id = g.current_user["id"] if g.current_user else None
    identified_by = "authenticated_member" if user_id else "anonymous"
    return _redirect(session, link, user_id, identified_by)


@bp.get("/meetup/<int:session_id>/u/<token>")
def member_redirect(session_id: int, token: str):
    session = db.query_one("SELECT * FROM club_sessions WHERE id = %s AND status <> 'cancelled'", (session_id,))
    if not session or not session["meetup_url"]:
        return render_template("meetup/unavailable.html", session=session), 404

    link = db.query_one(
        """SELECT * FROM meetup_links
            WHERE session_id = %s AND kind = 'member' AND token = %s AND is_active""",
        (session_id, token),
    )
    if not link or not link["user_id"]:
        abort(404)

    # The secret per-member link identifies the member even without a browser
    # login. If someone is logged in as a different member, prefer the link.
    return _redirect(session, link, link["user_id"], "member_link")
