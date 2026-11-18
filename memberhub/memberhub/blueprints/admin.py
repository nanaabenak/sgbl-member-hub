"""Administrator dashboard: members, sessions, tasks, verification and reports."""
import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from .. import db, security
from ..validation import email as valid_email
from ..validation import integer, local_datetime, local_date, text, url as valid_url, username as valid_username

bp = Blueprint("admin", __name__, url_prefix="/admin")

SUBMISSION_TABLES = {
    "builder_center": ("builder_center_profiles", "Builder Center profile"),
    "skill_builder": ("skill_builder_submissions", "Skill Builder evidence"),
    "achievement": ("achievement_records", "Achievement"),
}


def _member_or_404(user_id: int):
    row = db.query_one(
        """SELECT u.*, mp.*, r.name AS role_name
             FROM users u JOIN member_profiles mp ON mp.user_id = u.id
             JOIN roles r ON r.id = u.role_id WHERE u.id = %s""",
        (user_id,),
    )
    if not row:
        abort(404)
    return row


def _session_or_404(session_id: int):
    row = db.query_one("SELECT * FROM club_sessions WHERE id = %s", (session_id,))
    if not row:
        abort(404)
    return row


def _task_or_404(task_id: int):
    row = db.query_one(
        """SELECT t.*, u.full_name AS creator_name,
                  (SELECT count(*) FROM task_assignments a WHERE a.task_id = t.id) AS assigned_count
             FROM tasks t LEFT JOIN member_profiles u ON u.user_id = t.created_by
            WHERE t.id = %s""",
        (task_id,),
    )
    if not row:
        abort(404)
    return row


def _members():
    return db.query(
        """SELECT u.id, u.username, u.email, u.is_active, u.last_login_at,
                  mp.full_name, mp.membership_status, mp.student_id, r.name AS role_name
             FROM users u JOIN member_profiles mp ON mp.user_id = u.id
             JOIN roles r ON r.id = u.role_id ORDER BY mp.full_name, u.username"""
    )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@bp.get("/dashboard")
@security.admin_required
def dashboard():
    stats = {
        "members": db.scalar("SELECT count(*) FROM users u JOIN roles r ON r.id=u.role_id WHERE r.name='member'"),
        "active_members": db.scalar("SELECT count(*) FROM member_profiles WHERE membership_status='active'"),
        "sessions_held": db.scalar("SELECT count(*) FROM club_sessions WHERE status='completed'"),
        "clicks": db.scalar("SELECT count(*) FROM meetup_clicks"),
        "unique_clicks": db.scalar("SELECT count(DISTINCT ip_hash) FROM meetup_clicks"),
        "confirmed_rsvps": db.scalar("SELECT count(*) FROM rsvp_records WHERE status='verified'"),
        "attendance_present": db.scalar("SELECT count(*) FROM attendance_records WHERE status='present'"),
        "attendance_records": db.scalar("SELECT count(*) FROM attendance_records"),
        "tasks_approved": db.scalar("SELECT count(*) FROM task_submissions WHERE status='approved'"),
        "tasks_submitted": db.scalar("SELECT count(*) FROM task_submissions WHERE status IN ('submitted','approved','rejected','corrections_requested')"),
        "pending_verifications": db.scalar(
            """SELECT
                 (SELECT count(*) FROM builder_center_profiles WHERE status='pending') +
                 (SELECT count(*) FROM skill_builder_submissions WHERE status='pending') +
                 (SELECT count(*) FROM achievement_records WHERE status='pending')"""
        ),
        "pending_tasks": db.scalar("SELECT count(*) FROM task_submissions WHERE status='submitted'"),
    }
    stats["attendance_pct"] = round(stats["attendance_present"] / stats["attendance_records"] * 100) if stats["attendance_records"] else 0
    stats["task_pct"] = round(stats["tasks_approved"] / stats["tasks_submitted"] * 100) if stats["tasks_submitted"] else 0

    recent_sessions = db.query(
        """SELECT s.*,
                  (SELECT count(*) FROM meetup_clicks c WHERE c.session_id=s.id) AS clicks,
                  (SELECT count(*) FROM rsvp_records r WHERE r.session_id=s.id AND r.status='verified') AS rsvps,
                  (SELECT count(*) FROM attendance_records a WHERE a.session_id=s.id AND a.status='present') AS attended
             FROM club_sessions s ORDER BY s.starts_at DESC LIMIT 6"""
    )
    pending = db.query(
        """SELECT 'builder_center' AS kind, b.id, mp.full_name, b.display_name AS title, b.submitted_at
             FROM builder_center_profiles b JOIN member_profiles mp ON mp.user_id=b.user_id WHERE b.status='pending'
            UNION ALL
            SELECT 'skill_builder', s.id, mp.full_name, s.course_name, s.submitted_at
             FROM skill_builder_submissions s JOIN member_profiles mp ON mp.user_id=s.user_id WHERE s.status='pending'
            UNION ALL
            SELECT 'achievement', a.id, mp.full_name, a.title, a.submitted_at
             FROM achievement_records a JOIN member_profiles mp ON mp.user_id=a.user_id WHERE a.status='pending'
            ORDER BY submitted_at LIMIT 6"""
    )
    activity = db.query(
        """SELECT a.action, a.created_at, a.details, a.target_type, coalesce(mp.full_name, u.username) AS actor
             FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id
             LEFT JOIN member_profiles mp ON mp.user_id=a.actor_id
            ORDER BY a.created_at DESC LIMIT 10"""
    )
    return render_template("admin/dashboard.html", stats=stats, recent_sessions=recent_sessions, pending=pending, activity=activity)


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------
@bp.get("/members")
@security.admin_required
def members():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    rows = db.query(
        """SELECT u.id, u.username, u.email, u.is_active, u.last_login_at, mp.full_name,
                  mp.membership_status, mp.student_id, mp.location, r.name AS role_name,
                  (SELECT count(*) FROM attendance_records a WHERE a.user_id=u.id AND a.status='present') AS attended,
                  (SELECT count(*) FROM task_submissions s WHERE s.user_id=u.id AND s.status='approved') AS tasks_done
             FROM users u JOIN member_profiles mp ON mp.user_id=u.id
             JOIN roles r ON r.id=u.role_id
            WHERE (%s = '' OR u.username ILIKE %s OR u.email ILIKE %s OR mp.full_name ILIKE %s)
              AND (%s = '' OR mp.membership_status = %s)
            ORDER BY mp.full_name, u.username""",
        (q, f"%{q}%", f"%{q}%", f"%{q}%", status, status),
    )
    return render_template("admin/members.html", members=rows, q=q, status=status)


@bp.post("/members")
@security.admin_required
def create_member():
    errors = []
    values = {
        "username": valid_username(request.form.get("username"), errors),
        "email": valid_email(request.form.get("email"), errors),
        "full_name": text(request.form.get("full_name"), "Full name", 120, True, errors),
        "student_id": text(request.form.get("student_id"), "Student ID", 40, errors=errors),
        "role": "admin" if request.form.get("role") == "admin" else "member",
        "membership_status": (request.form.get("membership_status") or "active").strip(),
    }
    if values["membership_status"] not in {"pending", "active", "inactive", "suspended"}:
        errors.append("Choose a valid membership status.")
    password = request.form.get("password") or ""
    if not security.strong_enough(password):
        errors.append("Password: at least 10 characters, with letters and numbers.")
    if db.query_one("SELECT 1 FROM users WHERE lower(username)=%s", (values["username"],)):
        errors.append("That username is already taken.")
    if db.query_one("SELECT 1 FROM users WHERE email=%s", (values["email"],)):
        errors.append("That email is already registered.")

    if not errors:
        role_id = db.scalar("SELECT id FROM roles WHERE name=%s", (values["role"],))
        user = db.execute(
            "INSERT INTO users (username, email, password_hash, role_id) VALUES (%s,%s,%s,%s) RETURNING id",
            (values["username"], values["email"], security.hash_password(password), role_id),
        )
        db.execute(
            """INSERT INTO member_profiles (user_id, full_name, student_id, membership_status, verified_at)
               VALUES (%s,%s,%s,%s, CASE WHEN %s='active' THEN now() ELSE NULL END)""",
            (user["id"], values["full_name"], values["student_id"], values["membership_status"], values["membership_status"]),
        )
        security.audit("admin.member_create", "user", user["id"], f"role={values['role']} status={values['membership_status']}")
        flash("Member created.", "ok")
        return redirect(url_for("admin.member_detail", user_id=user["id"]))
    for error in errors:
        flash(error, "bad")
    return redirect(url_for("admin.members"))


@bp.route("/members/<int:user_id>", methods=["GET", "POST"])
@security.admin_required
def member_detail(user_id: int):
    if request.method == "POST":
        errors = []
        action = request.form.get("action")
        if action == "profile":
            db.execute(
                """UPDATE member_profiles SET full_name=%s, student_id=%s, phone=%s, location=%s,
                          program=%s, bio=%s, github_username=%s, membership_status=%s
                    WHERE user_id=%s""",
                (
                    text(request.form.get("full_name"), "Full name", 120, True, errors),
                    text(request.form.get("student_id"), "Student ID", 40, errors=errors),
                    text(request.form.get("phone"), "Phone", 40, errors=errors),
                    text(request.form.get("location"), "Location", 80, errors=errors),
                    text(request.form.get("program"), "Programme", 120, errors=errors),
                    text(request.form.get("bio"), "Bio", 600, errors=errors),
                    text(request.form.get("github_username"), "GitHub username", 40, errors=errors),
                    (request.form.get("membership_status") or "pending").strip(),
                    user_id,
                ),
            )
            is_active = bool(request.form.get("is_active"))
            role_id = db.scalar("SELECT id FROM roles WHERE name=%s", ("admin" if request.form.get("role") == "admin" else "member",))
            db.execute("UPDATE users SET is_active=%s, role_id=%s WHERE id=%s", (is_active, role_id, user_id))
            security.audit("admin.member_update", "user", user_id, f"active={is_active} role_id={role_id}")
            flash("Member details updated.", "ok")
        elif action == "password":
            password = request.form.get("password") or ""
            if not security.strong_enough(password):
                errors.append("Password: at least 10 characters, with letters and numbers.")
            if not errors:
                db.execute("UPDATE users SET password_hash=%s WHERE id=%s", (security.hash_password(password), user_id))
                db.execute("DELETE FROM web_sessions WHERE user_id=%s", (user_id,))
                security.audit("admin.member_password_reset", "user", user_id)
                flash("Password reset. The member must sign in again.", "ok")
        for error in errors:
            flash(error, "bad")
        return redirect(url_for("admin.member_detail", user_id=user_id))

    member = _member_or_404(user_id)
    attendance = db.query(
        """SELECT a.*, s.title FROM attendance_records a JOIN club_sessions s ON s.id=a.session_id
            WHERE a.user_id=%s ORDER BY s.starts_at DESC""", (user_id,)
    )
    rsvps = db.query(
        """SELECT r.*, s.title FROM rsvp_records r JOIN club_sessions s ON s.id=r.session_id
            WHERE r.user_id=%s ORDER BY s.starts_at DESC""", (user_id,)
    )
    tasks = db.query(
        """SELECT s.status, s.submitted_at, s.reviewed_at, t.title FROM task_submissions s
             JOIN tasks t ON t.id=s.task_id WHERE s.user_id=%s ORDER BY s.updated_at DESC""", (user_id,)
    )
    verifications = db.query(
        """SELECT v.*, u.full_name AS reviewer FROM verification_records v
             LEFT JOIN member_profiles u ON u.user_id=v.reviewed_by
            WHERE v.user_id=%s ORDER BY v.created_at DESC""", (user_id,)
    )
    clicks = db.scalar("SELECT count(*) FROM meetup_clicks WHERE user_id=%s", (user_id,))
    return render_template(
        "admin/member_detail.html", member=member, attendance=attendance, rsvps=rsvps,
        tasks=tasks, verifications=verifications, clicks=clicks,
    )


# ---------------------------------------------------------------------------
# Sessions, Meetup tracking, RSVP and attendance
# ---------------------------------------------------------------------------
@bp.get("/sessions")
@security.admin_required
def sessions():
    rows = db.query(
        """SELECT s.*,
                  (SELECT count(*) FROM meetup_clicks c WHERE c.session_id=s.id) AS clicks,
                  (SELECT count(*) FROM rsvp_records r WHERE r.session_id=s.id AND r.status='verified') AS rsvps,
                  (SELECT count(*) FROM attendance_records a WHERE a.session_id=s.id AND a.status='present') AS attended
             FROM club_sessions s ORDER BY s.starts_at DESC"""
    )
    return render_template("admin/sessions.html", sessions=rows)


@bp.post("/sessions")
@security.admin_required
def create_session():
    errors = []
    title = text(request.form.get("title"), "Title", 160, True, errors)
    starts_at = local_datetime(request.form.get("starts_at"), "Start time", True, errors)
    ends_at = local_datetime(request.form.get("ends_at"), "End time", errors=errors)
    if starts_at and ends_at and ends_at <= starts_at:
        errors.append("End time must be after the start time.")
    meetup_url = valid_url(request.form.get("meetup_url"), "Meetup URL", errors=errors)
    if not errors:
        session_id = db.execute(
            """INSERT INTO club_sessions (title, description, starts_at, ends_at, location,
                                          meetup_url, meetup_event_id, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                title,
                text(request.form.get("description"), "Description", 2000, errors=errors),
                starts_at, ends_at,
                text(request.form.get("location"), "Location", 160, errors=errors),
                meetup_url,
                text(request.form.get("meetup_event_id"), "Meetup event ID", 80, errors=errors),
                g.current_user["id"],
            ),
        )["id"]
        db.execute("INSERT INTO meetup_links (session_id, kind) VALUES (%s, 'aggregate')", (session_id,))
        security.audit("admin.session_create", "club_session", session_id, title)
        flash("Session created with a tracked Meetup link.", "ok")
        return redirect(url_for("admin.session_detail", session_id=session_id))
    for error in errors:
        flash(error, "bad")
    return redirect(url_for("admin.sessions"))


@bp.route("/sessions/<int:session_id>", methods=["GET", "POST"])
@security.admin_required
def session_detail(session_id: int):
    if request.method == "POST":
        errors = []
        action = request.form.get("action")
        if action == "update":
            reported = integer(request.form.get("meetup_rsvp_count"), "Meetup RSVP count", errors=errors, minimum=0)
            starts_at = local_datetime(request.form.get("starts_at"), "Start time", True, errors)
            ends_at = local_datetime(request.form.get("ends_at"), "End time", errors=errors)
            db.execute(
                """UPDATE club_sessions SET title=%s, description=%s, starts_at=%s, ends_at=%s, location=%s,
                          meetup_url=%s, meetup_event_id=%s, status=%s
                    WHERE id=%s""",
                (
                    text(request.form.get("title"), "Title", 160, True, errors),
                    text(request.form.get("description"), "Description", 2000, errors=errors),
                    starts_at, ends_at,
                    text(request.form.get("location"), "Location", 160, errors=errors),
                    valid_url(request.form.get("meetup_url"), "Meetup URL", errors=errors),
                    text(request.form.get("meetup_event_id"), "Meetup event ID", 80, errors=errors),
                    (request.form.get("status") or "scheduled").strip(), session_id,
                ),
            )
            if reported is not None:
                db.execute(
                    """UPDATE club_sessions SET meetup_rsvp_count=%s,
                              rsvp_count_reported_at=CASE WHEN %s <> meetup_rsvp_count THEN now() ELSE rsvp_count_reported_at END
                        WHERE id=%s""",
                    (reported, reported, session_id),
                )
            security.audit("admin.session_update", "club_session", session_id)
            flash("Session details saved.", "ok")
        elif action == "member_link":
            uid = integer(request.form.get("user_id"), "Member", errors=errors, minimum=1)
            if uid and not db.query_one("SELECT 1 FROM member_profiles WHERE user_id=%s", (uid,)):
                errors.append("Member not found.")
            if uid and not errors:
                db.execute(
                    """INSERT INTO meetup_links (session_id, user_id, kind, token)
                       VALUES (%s, %s, 'member', %s)
                       ON CONFLICT (session_id, user_id, kind) DO UPDATE SET is_active=TRUE""",
                    (session_id, uid, security.new_token()),
                )
                security.audit("admin.meetup_link_create", "club_session", session_id, f"member={uid}")
                flash("Member-specific tracking link is ready.", "ok")
        elif action == "rsvp":
            uid = integer(request.form.get("user_id"), "Member", errors=errors, minimum=1)
            external_id = text(request.form.get("meetup_member_id"), "Meetup member ID", 80, errors=errors)
            if not uid and not external_id:
                errors.append("Choose a member or enter a Meetup member ID.")
            if uid:
                db.execute(
                    """INSERT INTO rsvp_records (session_id, user_id, status, source, verified_by, notes)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (session_id, user_id) DO UPDATE SET
                         status=EXCLUDED.status, source=EXCLUDED.source, verified_by=EXCLUDED.verified_by,
                         verified_at=now(), notes=EXCLUDED.notes""",
                    (session_id, uid, request.form.get("status", "verified"), request.form.get("source", "manual"),
                     g.current_user["id"], text(request.form.get("notes"), "Notes", 300, errors=errors)),
                )
            elif external_id and not errors:
                existing = db.query_one(
                    "SELECT id FROM rsvp_records WHERE session_id=%s AND meetup_member_id=%s",
                    (session_id, external_id),
                )
                if existing:
                    db.execute(
                        "UPDATE rsvp_records SET status=%s, source=%s, verified_by=%s, verified_at=now() WHERE id=%s",
                        (request.form.get("status", "verified"), request.form.get("source", "manual"), g.current_user["id"], existing["id"]),
                    )
                else:
                    db.execute(
                        """INSERT INTO rsvp_records (session_id, meetup_member_id, status, source, verified_by, notes)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (session_id, external_id, request.form.get("status", "verified"), request.form.get("source", "manual"),
                         g.current_user["id"], text(request.form.get("notes"), "Notes", 300, errors=errors)),
                    )
            security.audit("admin.rsvp_record", "club_session", session_id, f"user={uid} external={external_id}")
            flash("RSVP record saved.", "ok")
        elif action == "attendance":
            attendee_ids = [integer(v, "Attendee", errors=errors, minimum=1) for v in request.form.getlist("attendees")]
            attendee_ids = [v for v in attendee_ids if v]
            if request.form.get("mark_others_absent"):
                all_ids = {row["user_id"] for row in db.query("SELECT user_id FROM member_profiles")}
                absent_ids = all_ids - set(attendee_ids)
            else:
                absent_ids = []
            for uid in attendee_ids:
                db.execute(
                    """INSERT INTO attendance_records (session_id, user_id, status, checked_in_at, recorded_by)
                       VALUES (%s,%s,'present',now(),%s)
                       ON CONFLICT (session_id, user_id) DO UPDATE SET
                         status='present', checked_in_at=now(), recorded_by=EXCLUDED.recorded_by""",
                    (session_id, uid, g.current_user["id"]),
                )
            for uid in absent_ids:
                db.execute(
                    """INSERT INTO attendance_records (session_id, user_id, status, recorded_by)
                       VALUES (%s,%s,'absent',%s)
                       ON CONFLICT (session_id, user_id) DO UPDATE SET
                         status='absent', checked_in_at=NULL, recorded_by=EXCLUDED.recorded_by""",
                    (session_id, uid, g.current_user["id"]),
                )
            security.audit("admin.attendance_record", "club_session", session_id, f"present={len(attendee_ids)} absent={len(absent_ids)}")
            flash(f"Attendance saved: {len(attendee_ids)} present, {len(absent_ids)} absent.", "ok")
        for error in errors:
            flash(error, "bad")
        return redirect(url_for("admin.session_detail", session_id=session_id))

    club_session = _session_or_404(session_id)
    metrics = db.query_one(
        """SELECT count(*) AS total_clicks,
                  count(DISTINCT ip_hash) AS unique_clicks,
                  count(*) FILTER (WHERE user_id IS NOT NULL) AS identified_clicks,
                  count(*) FILTER (WHERE user_id IS NULL) AS anonymous_clicks
             FROM meetup_clicks WHERE session_id=%s""",
        (session_id,),
    )
    rsvps = db.query(
        """SELECT r.*, mp.full_name FROM rsvp_records r
             LEFT JOIN member_profiles mp ON mp.user_id=r.user_id
            WHERE r.session_id=%s ORDER BY r.verified_at DESC""", (session_id,)
    )
    attendance = db.query(
        """SELECT a.*, mp.full_name, u.username FROM attendance_records a
             JOIN member_profiles mp ON mp.user_id=a.user_id JOIN users u ON u.id=a.user_id
            WHERE a.session_id=%s ORDER BY mp.full_name""", (session_id,)
    )
    links = db.query(
        """SELECT l.*, mp.full_name, u.username FROM meetup_links l
             LEFT JOIN member_profiles mp ON mp.user_id=l.user_id
             LEFT JOIN users u ON u.id=l.user_id
            WHERE l.session_id=%s ORDER BY l.kind, mp.full_name""", (session_id,)
    )
    members = _members()
    present_ids = {a["user_id"] for a in attendance if a["status"] == "present"}
    return render_template(
        "admin/session_detail.html", club_session=club_session, metrics=metrics,
        rsvps=rsvps, attendance=attendance, links=links, members=members,
        present_ids=present_ids, base_url=request.host_url.rstrip("/"),
    )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
@bp.get("/tasks")
@security.admin_required
def tasks():
    rows = db.query(
        """SELECT t.*, u.full_name AS creator_name,
                  (SELECT count(*) FROM task_assignments a WHERE a.task_id=t.id) AS assigned_count,
                  (SELECT count(*) FROM task_submissions s WHERE s.task_id=t.id AND s.status='submitted') AS awaiting,
                  (SELECT count(*) FROM task_submissions s WHERE s.task_id=t.id AND s.status='approved') AS approved
             FROM tasks t LEFT JOIN member_profiles u ON u.user_id=t.created_by
            ORDER BY t.created_at DESC"""
    )
    return render_template("admin/tasks.html", tasks=rows)


@bp.post("/tasks")
@security.admin_required
def create_task():
    errors = []
    due_at = local_datetime(request.form.get("due_at"), "Due date", errors=errors)
    title = text(request.form.get("title"), "Title", 160, True, errors)
    if not errors:
        task_id = db.execute(
            """INSERT INTO tasks (title, description, instructions, due_at, scope, status, created_by)
               VALUES (%s,%s,%s,%s,%s,'draft',%s) RETURNING id""",
            (title,
             text(request.form.get("description"), "Description", 2000, errors=errors),
             text(request.form.get("instructions"), "Instructions", 3000, errors=errors),
             due_at,
             "selected" if request.form.get("scope") == "selected" else "all",
             g.current_user["id"]),
        )["id"]
        security.audit("admin.task_create", "task", task_id, title)
        flash("Task created as a draft. Assign it, then publish.", "ok")
        return redirect(url_for("admin.task_detail", task_id=task_id))
    for error in errors:
        flash(error, "bad")
    return redirect(url_for("admin.tasks"))


@bp.route("/tasks/<int:task_id>", methods=["GET", "POST"])
@security.admin_required
def task_detail(task_id: int):
    if request.method == "POST":
        errors = []
        action = request.form.get("action")
        task = _task_or_404(task_id)
        if action == "publish":
            if task["scope"] == "selected" and task["assigned_count"] == 0:
                errors.append("Assign at least one member before publishing.")
            if not errors:
                db.execute("UPDATE tasks SET status='published' WHERE id=%s", (task_id,))
                security.audit("admin.task_publish", "task", task_id)
                flash("Task published to member dashboards.", "ok")
        elif action == "close":
            db.execute("UPDATE tasks SET status='closed' WHERE id=%s", (task_id,))
            security.audit("admin.task_close", "task", task_id)
            flash("Task closed.", "ok")
        elif action == "assign":
            scope = "selected" if request.form.get("scope") == "selected" else "all"
            db.execute("UPDATE tasks SET scope=%s WHERE id=%s", (scope, task_id))
            if scope == "selected":
                ids = [integer(v, "Member", errors=errors, minimum=1) for v in request.form.getlist("user_ids")]
                ids = [v for v in ids if v]
                db.execute("DELETE FROM task_assignments WHERE task_id=%s", (task_id,))
                for uid in ids:
                    db.execute("INSERT INTO task_assignments (task_id, user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (task_id, uid))
                security.audit("admin.task_assign", "task", task_id, f"{len(ids)} members")
                flash(f"Assigned to {len(ids)} members.", "ok")
            else:
                db.execute("DELETE FROM task_assignments WHERE task_id=%s", (task_id,))
                security.audit("admin.task_assign", "task", task_id, "all members")
                flash("Task is visible to all members.", "ok")
        elif action == "review":
            sub_id = integer(request.form.get("submission_id"), "Submission", errors=errors, minimum=1)
            decision = (request.form.get("decision") or "").strip()
            if decision not in {"approved", "rejected", "corrections_requested"}:
                errors.append("Choose approve, reject or request corrections.")
            if sub_id and not db.query_one("SELECT 1 FROM task_submissions WHERE id=%s AND task_id=%s", (sub_id, task_id)):
                errors.append("Submission not found for this task.")
            if not errors:
                note = text(request.form.get("review_note"), "Review note", 1000, errors=errors)
                db.execute(
                    """UPDATE task_submissions SET status=%s, reviewed_by=%s, reviewed_at=now(), review_note=%s
                        WHERE id=%s""",
                    (decision, g.current_user["id"], note, sub_id),
                )
                security.audit("admin.task_review", "task_submission", sub_id, decision)
                flash("Review decision saved.", "ok")
        for error in errors:
            flash(error, "bad")
        return redirect(url_for("admin.task_detail", task_id=task_id))

    task = _task_or_404(task_id)
    submissions = db.query(
        """SELECT s.*, mp.full_name, u.username, rv.full_name AS reviewer_name
             FROM task_submissions s JOIN member_profiles mp ON mp.user_id=s.user_id
             JOIN users u ON u.id=s.user_id
             LEFT JOIN member_profiles rv ON rv.user_id=s.reviewed_by
            WHERE s.task_id=%s ORDER BY s.status, mp.full_name""", (task_id,)
    )
    assigned = db.query(
        """SELECT a.user_id, mp.full_name, u.username FROM task_assignments a
             JOIN member_profiles mp ON mp.user_id=a.user_id JOIN users u ON u.id=a.user_id
            WHERE a.task_id=%s ORDER BY mp.full_name""", (task_id,)
    )
    return render_template("admin/task_detail.html", task=task, submissions=submissions, assigned=assigned, members=_members())


# ---------------------------------------------------------------------------
# Verification management
# ---------------------------------------------------------------------------
@bp.get("/verifications")
@security.admin_required
def verifications():
    kind = (request.args.get("kind") or "").strip()
    status = (request.args.get("status") or "").strip()
    parts = []
    for key, (table, label) in SUBMISSION_TABLES.items():
        if kind and kind != key:
            continue
        title_expr = {
            "builder_center": "display_name",
            "skill_builder": "course_name",
            "achievement": "title",
        }[key]
        parts.append(
            f"""SELECT '{key}' AS kind, s.id, s.user_id, mp.full_name, u.username,
                       s.{title_expr} AS title, s.status, s.submitted_at, s.reviewed_at,
                       coalesce(rv.full_name, '') AS reviewer_name
                  FROM {table} s JOIN member_profiles mp ON mp.user_id=s.user_id
                  JOIN users u ON u.id=s.user_id
                  LEFT JOIN member_profiles rv ON rv.user_id=s.reviewed_by"""
        )
    where = " WHERE (%s = '' OR q.status = %s) ORDER BY q.submitted_at"
    sql = "SELECT * FROM (" + " UNION ALL ".join(parts) + ") q" + where
    rows = db.query(sql, (status, status))
    return render_template("admin/verifications.html", rows=rows, kind=kind, status=status)


def _submission(kind: str, submission_id: int):
    if kind not in SUBMISSION_TABLES:
        abort(404)
    table = SUBMISSION_TABLES[kind][0]
    return db.query_one(
        f"""SELECT s.*, mp.full_name, u.username, u.email, rv.full_name AS reviewer_name
              FROM {table} s JOIN member_profiles mp ON mp.user_id=s.user_id
              JOIN users u ON u.id=s.user_id
              LEFT JOIN member_profiles rv ON rv.user_id=s.reviewed_by
             WHERE s.id=%s""",
        (submission_id,),
    )


@bp.route("/verifications/<kind>/<int:submission_id>", methods=["GET", "POST"])
@security.admin_required
def verification_detail(kind: str, submission_id: int):
    if kind not in SUBMISSION_TABLES:
        abort(404)
    if request.method == "POST":
        errors = []
        decision = (request.form.get("decision") or "").strip()
        if decision not in {"approved", "rejected", "corrections_requested"}:
            errors.append("Choose approve, reject or request corrections.")
        note = text(request.form.get("review_note"), "Review note", 1000, errors=errors)
        if not errors:
            table = SUBMISSION_TABLES[kind][0]
            db.execute(
                """UPDATE """ + table + """ SET status=%s, reviewed_by=%s, reviewed_at=now(), review_note=%s
                    WHERE id=%s""",
                (decision, g.current_user["id"], note, submission_id),
            )
            db.execute(
                """INSERT INTO verification_records (subject_type, subject_id, user_id, status, reviewed_by, reviewed_at, notes)
                   SELECT %s, %s, user_id, %s, %s, now(), %s FROM """ + table + """ WHERE id=%s""",
                (kind, submission_id, decision, g.current_user["id"], note, submission_id),
            )
            security.audit("admin.verification_review", kind, submission_id, decision)
            flash("Verification decision recorded.", "ok")
        for error in errors:
            flash(error, "bad")
        return redirect(url_for("admin.verification_detail", kind=kind, submission_id=submission_id))

    submission = _submission(kind, submission_id)
    if not submission:
        abort(404)
    history = db.query(
        """SELECT v.*, mp.full_name AS reviewer FROM verification_records v
             LEFT JOIN member_profiles mp ON mp.user_id=v.reviewed_by
            WHERE v.subject_type=%s AND v.subject_id=%s ORDER BY v.created_at DESC""",
        (kind, submission_id),
    )
    return render_template("admin/verification_detail.html", kind=kind, submission=submission, history=history, label=SUBMISSION_TABLES[kind][1])


# ---------------------------------------------------------------------------
# Reports and audit log
# ---------------------------------------------------------------------------
@bp.get("/reports")
@security.admin_required
def reports():
    return render_template("admin/reports.html")


def _csv_response(filename: str, headers: list, rows: list):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)
    writer.writerows(rows)
    response = Response(out.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/reports/<name>.csv")
@security.admin_required
def export_csv(name: str):
    reports_map = {
        "members": "member engagement",
        "attendance": "session attendance",
        "meetup": "Meetup engagement",
        "tasks": "task completion",
        "verifications": "learning verification",
    }
    if name not in reports_map:
        abort(404)

    if name == "members":
        headers = ["Username", "Name", "Email", "Membership", "Role", "Sessions attended", "RSVPs verified", "Meetup clicks", "Tasks approved", "Verifications approved"]
        rows = [list(r.values()) for r in db.query(
            """SELECT u.username, mp.full_name, u.email, mp.membership_status, r.name,
                      (SELECT count(*) FROM attendance_records a WHERE a.user_id=u.id AND a.status='present'),
                      (SELECT count(*) FROM rsvp_records v WHERE v.user_id=u.id AND v.status='verified'),
                      (SELECT count(*) FROM meetup_clicks c WHERE c.user_id=u.id),
                      (SELECT count(*) FROM task_submissions s WHERE s.user_id=u.id AND s.status='approved'),
                      (SELECT count(*) FROM verification_records vr WHERE vr.user_id=u.id AND vr.status='approved')
                 FROM users u JOIN member_profiles mp ON mp.user_id=u.id
                 JOIN roles r ON r.id=u.role_id ORDER BY mp.full_name"""
        )]
    elif name == "attendance":
        headers = ["Session", "Starts", "Status", "Reported RSVPs", "Verified RSVPs", "Total clicks", "Present", "Absent", "Attendance %"]
        rows = [list(r.values()) for r in db.query(
            """SELECT s.title, s.starts_at::text, s.status, s.meetup_rsvp_count,
                      (SELECT count(*) FROM rsvp_records r WHERE r.session_id=s.id AND r.status='verified'),
                      (SELECT count(*) FROM meetup_clicks c WHERE c.session_id=s.id),
                      (SELECT count(*) FROM attendance_records a WHERE a.session_id=s.id AND a.status='present'),
                      (SELECT count(*) FROM attendance_records a WHERE a.session_id=s.id AND a.status='absent'),
                      CASE WHEN (SELECT count(*) FROM attendance_records a WHERE a.session_id=s.id)=0 THEN 0
                           ELSE round(100.0*(SELECT count(*) FROM attendance_records a WHERE a.session_id=s.id AND a.status='present') /
                                      (SELECT count(*) FROM attendance_records a WHERE a.session_id=s.id)) END
                 FROM club_sessions s ORDER BY s.starts_at DESC"""
        )]
    elif name == "meetup":
        headers = ["Session", "Meetup event ID", "Total clicks", "Unique clicks (IP hash)", "Identified member clicks", "Anonymous clicks", "Reported RSVPs", "Verified RSVP records", "Actual attendance"]
        rows = [list(r.values()) for r in db.query(
            """SELECT s.title, s.meetup_event_id,
                      (SELECT count(*) FROM meetup_clicks c WHERE c.session_id=s.id),
                      (SELECT count(DISTINCT ip_hash) FROM meetup_clicks c WHERE c.session_id=s.id),
                      (SELECT count(*) FROM meetup_clicks c WHERE c.session_id=s.id AND c.user_id IS NOT NULL),
                      (SELECT count(*) FROM meetup_clicks c WHERE c.session_id=s.id AND c.user_id IS NULL),
                      s.meetup_rsvp_count,
                      (SELECT count(*) FROM rsvp_records r WHERE r.session_id=s.id AND r.status='verified'),
                      (SELECT count(*) FROM attendance_records a WHERE a.session_id=s.id AND a.status='present')
                 FROM club_sessions s ORDER BY s.starts_at DESC"""
        )]
    elif name == "tasks":
        headers = ["Task", "Status", "Due", "Assigned", "In progress", "Submitted", "Approved", "Rejected", "Corrections requested"]
        rows = [list(r.values()) for r in db.query(
            """SELECT t.title, t.status, coalesce(t.due_at::text, ''),
                      (SELECT count(*) FROM task_assignments a WHERE a.task_id=t.id) +
                        CASE WHEN t.scope='all' THEN (SELECT count(*) FROM member_profiles) ELSE 0 END,
                      (SELECT count(*) FROM task_submissions s WHERE s.task_id=t.id AND s.status='in_progress'),
                      (SELECT count(*) FROM task_submissions s WHERE s.task_id=t.id AND s.status='submitted'),
                      (SELECT count(*) FROM task_submissions s WHERE s.task_id=t.id AND s.status='approved'),
                      (SELECT count(*) FROM task_submissions s WHERE s.task_id=t.id AND s.status='rejected'),
                      (SELECT count(*) FROM task_submissions s WHERE s.task_id=t.id AND s.status='corrections_requested')
                 FROM tasks t ORDER BY t.created_at DESC"""
        )]
    else:
        headers = ["Member", "Type", "Title", "Status", "Submitted", "Reviewed by", "Reviewed at", "Note"]
        rows = [list(r.values()) for r in db.query(
            """SELECT mp.full_name, v.subject_type, v.subject_id::text, v.status, v.created_at::text,
                      coalesce(rv.full_name, ''), coalesce(v.reviewed_at::text, ''), v.notes
                 FROM verification_records v JOIN member_profiles mp ON mp.user_id=v.user_id
                 LEFT JOIN member_profiles rv ON rv.user_id=v.reviewed_by
                ORDER BY v.created_at DESC"""
        )]

    security.audit("admin.report_export", "report", name, reports_map[name])
    return _csv_response(f"sgbl-{name}-{datetime.now(timezone.utc):%Y%m%d}.csv", headers, rows)


@bp.get("/audit")
@security.admin_required
def audit_log():
    rows = db.query(
        """SELECT a.*, coalesce(mp.full_name, u.username, 'system') AS actor
             FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id
             LEFT JOIN member_profiles mp ON mp.user_id=a.actor_id
            ORDER BY a.created_at DESC LIMIT 200"""
    )
    return render_template("admin/audit.html", rows=rows)
