"""Member-facing portal."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db, security
from ..validation import integer, text, url as valid_url, local_date

bp = Blueprint("member", __name__, url_prefix="/member")


def _profile():
    return db.query_one(
        """SELECT mp.*, u.username, u.email, u.last_login_at
             FROM member_profiles mp JOIN users u ON u.id = mp.user_id
            WHERE mp.user_id = %s""",
        (g.current_user["id"],),
    )


def _visible_task(task_id: int, user_id: int):
    return db.query_one(
        """SELECT t.*, s.status AS submission_status, s.note, s.evidence_url,
                  s.submitted_at, s.review_note, s.reviewed_at,
                  u.full_name AS reviewer_name
             FROM tasks t
             LEFT JOIN task_submissions s ON s.task_id = t.id AND s.user_id = %s
             LEFT JOIN member_profiles u ON u.user_id = s.reviewed_by
            WHERE t.id = %s AND t.status = 'published'
              AND (t.scope = 'all' OR EXISTS (
                    SELECT 1 FROM task_assignments a WHERE a.task_id = t.id AND a.user_id = %s))""",
        (user_id, task_id, user_id),
    )


@bp.get("/dashboard")
@security.login_required
def dashboard():
    uid = g.current_user["id"]
    profile = _profile()
    stats = {
        "upcoming": db.scalar("SELECT count(*) FROM club_sessions WHERE status = 'scheduled' AND starts_at > now()"),
        "my_tasks_open": db.scalar(
            """SELECT count(*) FROM tasks t
                 LEFT JOIN task_submissions s ON s.task_id = t.id AND s.user_id = %s
                WHERE t.status = 'published'
                  AND (t.scope = 'all' OR EXISTS (SELECT 1 FROM task_assignments a WHERE a.task_id = t.id AND a.user_id = %s))
                  AND coalesce(s.status, 'not_started') NOT IN ('approved')""",
            (uid, uid),
        ),
        "verifications_pending": db.scalar(
            """SELECT
                 (SELECT count(*) FROM builder_center_profiles WHERE user_id = %s AND status = 'pending') +
                 (SELECT count(*) FROM skill_builder_submissions WHERE user_id = %s AND status = 'pending') +
                 (SELECT count(*) FROM achievement_records WHERE user_id = %s AND status = 'pending')""",
            (uid, uid, uid),
        ),
        "my_clicks": db.scalar("SELECT count(*) FROM meetup_clicks WHERE user_id = %s", (uid,)),
    }
    held = db.scalar("SELECT count(*) FROM club_sessions WHERE status = 'completed'")
    present = db.scalar("SELECT count(*) FROM attendance_records WHERE user_id = %s AND status = 'present'", (uid,))
    stats["attendance_pct"] = round(present / held * 100) if held else 0

    sessions = db.query(
        """SELECT s.*, r.status AS rsvp_status, a.status AS attendance_status
             FROM club_sessions s
             LEFT JOIN rsvp_records r ON r.session_id = s.id AND r.user_id = %s AND r.status = 'verified'
             LEFT JOIN attendance_records a ON a.session_id = s.id AND a.user_id = %s
            WHERE s.status <> 'cancelled'
            ORDER BY (s.starts_at > now()) DESC, abs(extract(epoch from (s.starts_at - now()))) LIMIT 6""",
        (uid, uid),
    )
    tasks = db.query(
        """SELECT t.*, coalesce(s.status, 'not_started') AS submission_status
             FROM tasks t
             LEFT JOIN task_submissions s ON s.task_id = t.id AND s.user_id = %s
            WHERE t.status = 'published'
              AND (t.scope = 'all' OR EXISTS (SELECT 1 FROM task_assignments a WHERE a.task_id = t.id AND a.user_id = %s))
            ORDER BY coalesce(t.due_at, t.created_at) LIMIT 5""",
        (uid, uid),
    )
    activity = db.query(
        """SELECT 'task' AS kind, coalesce(t.title, 'Task') AS title, s.updated_at AS at, s.status AS detail
             FROM task_submissions s JOIN tasks t ON t.id = s.task_id WHERE s.user_id = %s
            UNION ALL
            SELECT 'verification', v.subject_type, v.created_at, v.status
             FROM verification_records v WHERE v.user_id = %s
            UNION ALL
            SELECT 'attendance', s.title, a.created_at, a.status
             FROM attendance_records a JOIN club_sessions s ON s.id = a.session_id WHERE a.user_id = %s
            ORDER BY at DESC LIMIT 8""",
        (uid, uid, uid),
    )
    return render_template("member/dashboard.html", profile=profile, stats=stats, sessions=sessions, tasks=tasks, activity=activity)


@bp.route("/profile", methods=["GET", "POST"])
@security.login_required
def profile():
    uid = g.current_user["id"]
    if request.method == "POST":
        errors = []
        values = {
            "full_name": text(request.form.get("full_name"), "Full name", 120, True, errors),
            "student_id": text(request.form.get("student_id"), "Student ID", 40, errors=errors),
            "phone": text(request.form.get("phone"), "Phone", 40, errors=errors),
            "location": text(request.form.get("location"), "Location", 80, errors=errors),
            "program": text(request.form.get("program"), "Programme", 120, errors=errors),
            "bio": text(request.form.get("bio"), "Bio", 600, errors=errors),
            "github_username": text(request.form.get("github_username"), "GitHub username", 40, errors=errors),
            "builder_id": text(request.form.get("builder_id"), "AWS Builder ID", 120, errors=errors),
            "builder_card_url": valid_url(request.form.get("builder_card_url"), "Builder Card URL", errors=errors),
            "builder_center_url": valid_url(request.form.get("builder_center_url"), "Builder Center URL", errors=errors),
        }
        if not errors:
            db.execute(
                """UPDATE member_profiles SET full_name=%s, student_id=%s, phone=%s, location=%s,
                          program=%s, bio=%s, github_username=%s, builder_id=%s,
                          builder_card_url=%s, builder_center_url=%s
                    WHERE user_id=%s""",
                (
                    values["full_name"], values["student_id"], values["phone"], values["location"],
                    values["program"], values["bio"], values["github_username"], values["builder_id"],
                    values["builder_card_url"], values["builder_center_url"], uid,
                ),
            )
            security.audit("member.profile_update", "member_profile", uid)
            flash("Profile updated.", "ok")
            return redirect(url_for("member.profile"))
        for error in errors:
            flash(error, "bad")

    profile = _profile()
    verifications = db.query(
        """SELECT 'builder_center' AS kind, b.status, b.reviewed_at, b.review_note, b.submitted_at
             FROM builder_center_profiles b WHERE b.user_id = %s
            UNION ALL
            SELECT 'skill_builder', s.status, s.reviewed_at, s.review_note, s.submitted_at
             FROM skill_builder_submissions s WHERE s.user_id = %s
            UNION ALL
            SELECT 'achievement', a.status, a.reviewed_at, a.review_note, a.submitted_at
             FROM achievement_records a WHERE a.user_id = %s
            ORDER BY submitted_at DESC LIMIT 10""",
        (uid, uid, uid),
    )
    return render_template("member/profile.html", profile=profile, verifications=verifications)


@bp.get("/sessions")
@security.login_required
def sessions():
    uid = g.current_user["id"]
    rows = db.query(
        """SELECT s.*, r.status AS rsvp_status, r.verified_at AS rsvp_verified_at,
                  a.status AS attendance_status,
                  (SELECT count(*) FROM meetup_clicks c WHERE c.session_id = s.id AND c.user_id = %s) AS my_clicks
             FROM club_sessions s
             LEFT JOIN rsvp_records r ON r.session_id = s.id AND r.user_id = %s AND r.status = 'verified'
             LEFT JOIN attendance_records a ON a.session_id = s.id AND a.user_id = %s
            WHERE s.status <> 'cancelled'
            ORDER BY (s.starts_at > now()) DESC, s.starts_at DESC""",
        (uid, uid, uid),
    )
    links = {row["id"]: db.query_one(
        "SELECT token FROM meetup_links WHERE session_id = %s AND kind = 'member' AND user_id = %s AND is_active",
        (row["id"], uid),
    ) for row in rows}
    return render_template("member/sessions.html", sessions=rows, links=links)


@bp.get("/sessions/<int:session_id>")
@security.login_required
def session_detail(session_id: int):
    uid = g.current_user["id"]
    session = db.query_one("SELECT * FROM club_sessions WHERE id = %s", (session_id,))
    if not session or session["status"] == "cancelled":
        abort(404)
    rsvp = db.query_one(
        "SELECT * FROM rsvp_records WHERE session_id = %s AND user_id = %s AND status = 'verified'",
        (session_id, uid),
    )
    attendance = db.query_one(
        "SELECT * FROM attendance_records WHERE session_id = %s AND user_id = %s", (session_id, uid)
    )
    member_link = db.query_one(
        "SELECT token FROM meetup_links WHERE session_id = %s AND user_id = %s AND kind = 'member' AND is_active",
        (session_id, uid),
    )
    clicks = db.query(
        """SELECT clicked_at, identified_by FROM meetup_clicks
            WHERE session_id = %s AND user_id = %s ORDER BY clicked_at DESC LIMIT 20""",
        (session_id, uid),
    )
    return render_template(
        "member/session_detail.html",
        session=session, rsvp=rsvp, attendance=attendance, member_link=member_link, clicks=clicks,
    )


@bp.get("/tasks")
@security.login_required
def tasks():
    uid = g.current_user["id"]
    rows = db.query(
        """SELECT t.*, coalesce(s.status, 'not_started') AS submission_status, s.submitted_at
             FROM tasks t LEFT JOIN task_submissions s ON s.task_id = t.id AND s.user_id = %s
            WHERE t.status = 'published'
              AND (t.scope = 'all' OR EXISTS (SELECT 1 FROM task_assignments a WHERE a.task_id = t.id AND a.user_id = %s))
            ORDER BY (t.due_at IS NULL), t.due_at, t.created_at DESC""",
        (uid, uid),
    )
    return render_template("member/tasks.html", tasks=rows)


@bp.route("/tasks/<int:task_id>", methods=["GET", "POST"])
@security.login_required
def task_detail(task_id: int):
    uid = g.current_user["id"]
    task = _visible_task(task_id, uid)
    if not task:
        abort(404)

    if request.method == "POST":
        action = request.form.get("action")
        errors = []
        evidence = valid_url(request.form.get("evidence_url"), "Evidence URL", errors=errors)
        note = text(request.form.get("note"), "Completion notes", 2000, errors=errors)

        if action in {"progress", "submit"}:
            if action == "submit" and not note and not evidence:
                errors.append("Add a completion note or an evidence link before submitting.")
            if task.get("submission_status") == "approved":
                errors.append("This task has already been approved.")
            if not errors:
                if action == "submit":
                    db.execute(
                        """INSERT INTO task_submissions (task_id, user_id, status, note, evidence_url, submitted_at)
                           VALUES (%s, %s, 'submitted', %s, %s, now())
                           ON CONFLICT (task_id, user_id) DO UPDATE SET
                             status='submitted', note=EXCLUDED.note, evidence_url=EXCLUDED.evidence_url,
                             submitted_at=now(), reviewed_by=NULL, reviewed_at=NULL, review_note=''""",
                        (task_id, uid, note, evidence),
                    )
                else:
                    db.execute(
                        """INSERT INTO task_submissions (task_id, user_id, status)
                           VALUES (%s, %s, 'in_progress')
                           ON CONFLICT (task_id, user_id) DO UPDATE SET status='in_progress'
                           WHERE task_submissions.status NOT IN ('approved', 'submitted')""",
                        (task_id, uid),
                    )
                security.audit("task." + action, "task", task_id, "Member task update")
                flash("Task marked in progress." if action == "progress" else "Evidence submitted for review.", "ok")
                return redirect(url_for("member.task_detail", task_id=task_id))
        for error in errors:
            flash(error, "bad")
    task = _visible_task(task_id, uid)
    return render_template("member/task_detail.html", task=task)


@bp.get("/learning")
@security.login_required
def learning():
    uid = g.current_user["id"]
    submissions = db.query(
        """SELECT 'builder_center' AS kind, b.id, b.display_name AS title, b.submitted_at, b.status,
                  b.review_note, b.reviewed_at, b.profile_url AS link
             FROM builder_center_profiles b WHERE b.user_id = %s
            UNION ALL
            SELECT 'skill_builder', s.id, s.course_name, s.submitted_at, s.status,
                  s.review_note, s.reviewed_at, coalesce(s.completion_url, s.evidence_url)
             FROM skill_builder_submissions s WHERE s.user_id = %s
            UNION ALL
            SELECT 'achievement', a.id, a.title, a.submitted_at, a.status,
                  a.review_note, a.reviewed_at, a.evidence_url
             FROM achievement_records a WHERE a.user_id = %s
            ORDER BY submitted_at DESC""",
        (uid, uid, uid),
    )
    decisions = db.query(
        """SELECT v.*, u.full_name AS reviewer_name FROM verification_records v
             LEFT JOIN member_profiles u ON u.user_id = v.reviewed_by
            WHERE v.user_id = %s ORDER BY v.created_at DESC LIMIT 12""",
        (uid,),
    )
    profile = _profile()
    return render_template("member/learning.html", submissions=submissions, decisions=decisions, profile=profile)


def _record_verification(subject_type: str, subject_id: int, user_id: int, status="pending", notes="Submitted for review"):
    db.execute(
        """INSERT INTO verification_records (subject_type, subject_id, user_id, status, notes)
           VALUES (%s, %s, %s, %s, %s)""",
        (subject_type, subject_id, user_id, status, notes),
    )


@bp.post("/learning/builder-center")
@security.login_required
def submit_builder_center():
    uid = g.current_user["id"]
    errors = []
    profile_url = valid_url(request.form.get("profile_url"), "Builder Center profile URL", True, errors)
    evidence_url = valid_url(request.form.get("evidence_url"), "Evidence URL", errors=errors)
    display_name = text(request.form.get("display_name"), "Display name", 120, errors=errors)
    builder_id = text(request.form.get("builder_id"), "AWS Builder ID", 120, errors=errors)
    notes = text(request.form.get("notes"), "Notes", 1000, errors=errors)
    if not errors:
        existing = db.query_one(
            "SELECT id FROM builder_center_profiles WHERE user_id = %s AND status IN ('pending', 'corrections_requested') ORDER BY id DESC LIMIT 1",
            (uid,),
        )
        if existing:
            db.execute(
                """UPDATE builder_center_profiles SET profile_url=%s, builder_id=%s, display_name=%s,
                          notes=%s, status='pending', reviewed_by=NULL, reviewed_at=NULL,
                          review_note='', submitted_at=now()
                    WHERE id=%s""",
                (profile_url, builder_id, display_name, notes, existing["id"]),
            )
            subject_id = existing["id"]
        else:
            subject_id = db.execute(
                """INSERT INTO builder_center_profiles
                     (user_id, profile_url, builder_id, display_name, notes, evidence_url)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (uid, profile_url, builder_id, display_name, notes, evidence_url),
            )["id"]
        _record_verification("builder_center", subject_id, uid)
        db.execute(
            """UPDATE member_profiles SET builder_center_url=%s, builder_id=%s WHERE user_id=%s""",
            (profile_url, builder_id, uid),
        )
        security.audit("learning.builder_center_submit", "builder_center", subject_id)
        flash("Builder Center profile submitted for verification.", "ok")
    else:
        for error in errors:
            flash(error, "bad")
    return redirect(url_for("member.learning"))


@bp.post("/learning/skill-builder")
@security.login_required
def submit_skill_builder():
    uid = g.current_user["id"]
    errors = []
    course_name = text(request.form.get("course_name"), "Course name", 160, True, errors)
    completion_url = valid_url(request.form.get("completion_url"), "Completion URL", errors=errors)
    evidence_url = valid_url(request.form.get("evidence_url"), "Evidence URL", errors=errors)
    notes = text(request.form.get("notes"), "Notes", 1000, errors=errors)
    hours = text(request.form.get("hours"), "Hours", 10, errors=errors)
    if not completion_url and not evidence_url:
        errors.append("Provide a completion URL or evidence URL.")
    if not errors:
        subject_id = db.execute(
            """INSERT INTO skill_builder_submissions
                 (user_id, course_name, completion_url, evidence_url, hours, notes)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (uid, course_name, completion_url, evidence_url, hours or None, notes),
        )["id"]
        _record_verification("skill_builder", subject_id, uid)
        security.audit("learning.skill_builder_submit", "skill_builder", subject_id)
        flash("Skill Builder evidence submitted for verification.", "ok")
    else:
        for error in errors:
            flash(error, "bad")
    return redirect(url_for("member.learning"))


@bp.post("/learning/achievements")
@security.login_required
def submit_achievement():
    uid = g.current_user["id"]
    errors = []
    category = (request.form.get("category") or "").strip()
    if category not in {"certification", "badge"}:
        errors.append("Choose certification or badge.")
    title = text(request.form.get("title"), "Title", 160, True, errors)
    issuer = text(request.form.get("issuer"), "Issuer", 120, errors=errors)
    evidence_url = valid_url(request.form.get("evidence_url"), "Evidence URL", True, errors)
    earned_at = local_date(request.form.get("earned_at"), "Date earned", errors=errors)
    notes = text(request.form.get("notes"), "Notes", 1000, errors=errors)
    if not errors:
        subject_id = db.execute(
            """INSERT INTO achievement_records
                 (user_id, category, title, issuer, evidence_url, earned_at, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (uid, category, title, issuer, evidence_url, earned_at, notes),
        )["id"]
        _record_verification("achievement", subject_id, uid)
        security.audit("learning.achievement_submit", "achievement", subject_id)
        flash("Achievement submitted for verification.", "ok")
    else:
        for error in errors:
            flash(error, "bad")
    return redirect(url_for("member.learning"))
