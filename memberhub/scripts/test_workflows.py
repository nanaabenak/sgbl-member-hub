#!/usr/bin/env python3
"""End-to-end workflow tests against a real PostgreSQL database.

Creates a throwaway database (sgbl_member_hub_test by default), then walks
the full admin + member journey through Flask's test client, including CSRF,
RBAC, tracked redirects, task review, verification and CSV reports.

Usage:
    python3 scripts/test_workflows.py
"""
import os
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
from psycopg2.extras import RealDictCursor

BASE_DIR = Path(__file__).resolve().parent.parent
TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql:///sgbl_member_hub_test")
os.environ["DATABASE_URL"] = TEST_URL
os.environ["SECRET_KEY"] = "workflow-test-secret-key-not-for-production"
os.environ["FLASK_CONFIG"] = "testing"
sys.path.insert(0, str(BASE_DIR))

from memberhub import create_app  # noqa: E402
from memberhub.config import TestingConfig  # noqa: E402
from memberhub.security import hash_password  # noqa: E402


def maintenance_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:  # local socket connection: postgresql:///dbname
        return f"{parsed.scheme}:///postgres"
    return urlunparse(parsed._replace(path="/postgres"))


def reset_database(url: str) -> None:
    name = urlparse(url).path.lstrip("/")
    conn = psycopg2.connect(maintenance_url(url))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid <> pg_backend_pid()",
                (name,),
            )
            cur.execute(f"DROP DATABASE IF EXISTS {name}")
            cur.execute(f"CREATE DATABASE {name}")
    finally:
        conn.close()

    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute((BASE_DIR / "migrations" / "001_init.sql").read_text(encoding="utf-8"))
            cur.execute(
                """INSERT INTO users (username, email, password_hash, role_id)
                   VALUES ('admin1', 'admin1@example.com', %s, (SELECT id FROM roles WHERE name='admin'))
                   RETURNING id""",
                (hash_password("AdminPass123"),),
            )
            admin_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO member_profiles (user_id, full_name, membership_status, verified_at)
                   VALUES (%s, 'Ada Admin', 'active', now())""",
                (admin_id,),
            )
    finally:
        conn.close()


def rows(sql: str, params=None):
    conn = psycopg2.connect(TEST_URL)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def one(sql: str, params=None):
    result = rows(sql, params)
    return result[0] if result else None


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_database(TEST_URL)
        cls.app = create_app(TestingConfig)
        cls.app.testing = True
        cls.admin = cls.app.test_client()
        cls.member = cls.app.test_client()
        cls.anon = cls.app.test_client()
        cls.session_id = None
        cls.task_id = None
        cls.member_id = None

    # -- helpers -----------------------------------------------------------
    def token_from(self, client, path: str) -> str:
        response = client.get(path)
        self.assertEqual(response.status_code, 200, f"GET {path} failed: {response.status_code}")
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match, f"No CSRF token on {path}")
        return match.group(1)

    def post(self, client, path: str, data: dict, form_page: str):
        data = dict(data)
        data["csrf_token"] = self.token_from(client, form_page)
        return client.post(path, data=data)

    def login(self, client, identity: str, password: str):
        result = self.post(client, "/login", {"identity": identity, "password": password}, "/login")
        self.assertEqual(result.status_code, 302, f"Login failed for {identity}: {result.get_data(as_text=True)[:400]}")

    # -- tests -------------------------------------------------------------
    def test_01_health_and_csrf(self):
        self.assertEqual(self.anon.get("/health").status_code, 200)
        response = self.anon.post("/login", data={"identity": "admin1", "password": "AdminPass123"})
        self.assertEqual(response.status_code, 403, "POST without a CSRF token must be rejected")

    def test_02_admin_login_and_rbac(self):
        self.login(self.admin, "admin1", "AdminPass123")
        self.assertEqual(self.admin.get("/admin/dashboard").status_code, 200)
        self.assertIn("Club overview", self.admin.get("/admin/dashboard").get_data(as_text=True))

    def test_03_member_registration_activation_and_login(self):
        response = self.post(self.member, "/register", {
            "full_name": "Mia Mensah",
            "username": "miamember",
            "email": "mia@example.com",
            "student_id": "STU-204",
            "location": "Accra",
            "password": "MemberPass123",
            "confirm": "MemberPass123",
            "terms": "1",
        }, "/register")
        self.assertEqual(response.status_code, 302)
        member = one("SELECT id FROM users WHERE username='miamember'")
        self.assertIsNotNone(member)
        self.__class__.member_id = member["id"]
        self.assertEqual(one("SELECT membership_status FROM member_profiles WHERE user_id=%s", (member["id"],))["membership_status"], "pending")

        activation = self.post(self.admin, f"/admin/members/{member['id']}", {
            "action": "profile", "full_name": "Mia Mensah", "student_id": "STU-204",
            "phone": "0240000000", "location": "Accra", "program": "Computer Science",
            "github_username": "miamember", "membership_status": "active",
            "role": "member", "is_active": "1", "bio": "Backend builder",
        }, f"/admin/members/{member['id']}")
        self.assertEqual(activation.status_code, 302)
        self.login(self.member, "miamember", "MemberPass123")
        self.assertEqual(self.member.get("/member/dashboard").status_code, 200)
        self.assertEqual(self.member.get("/admin/dashboard").status_code, 403, "members must not reach admin routes")

    def test_04_profile_update(self):
        result = self.post(self.member, "/member/profile", {
            "full_name": "Mia Mensah", "student_id": "STU-204", "phone": "0240000000",
            "location": "Accra", "program": "Computer Science", "bio": "I build serverless things.",
            "github_username": "miamember", "builder_id": "miamember-123",
            "builder_card_url": "https://example.github.io/builder-card/",
            "builder_center_url": "https://builder.aws.com/miamember",
        }, "/member/profile")
        self.assertEqual(result.status_code, 302)
        profile = one("SELECT * FROM member_profiles WHERE user_id=%s", (self.member_id,))
        self.assertEqual(profile["builder_id"], "miamember-123")
        self.assertEqual(profile["membership_status"], "active")

    def test_05_session_and_tracked_links(self):
        result = self.post(self.admin, "/admin/sessions", {
            "title": "Session 4 — Serverless",
            "description": "Building with Lambda.",
            "starts_at": "2027-01-15T18:00",
            "ends_at": "2027-01-15T20:00",
            "location": "MainLab",
            "meetup_event_id": "evt-123",
            "meetup_url": "https://www.meetup.com/example/events/123/",
        }, "/admin/sessions")
        self.assertEqual(result.status_code, 302)
        session = one("SELECT * FROM club_sessions WHERE title='Session 4 — Serverless'")
        self.__class__.session_id = session["id"]
        self.assertIsNotNone(one("SELECT id FROM meetup_links WHERE session_id=%s AND kind='aggregate'", (session["id"],)))

        link = self.post(self.admin, f"/admin/sessions/{session['id']}", {
            "action": "member_link", "user_id": str(self.member_id),
        }, f"/admin/sessions/{session['id']}")
        self.assertEqual(link.status_code, 302)
        member_link = one("SELECT * FROM meetup_links WHERE session_id=%s AND user_id=%s AND kind='member'", (session["id"], self.member_id))
        self.assertIsNotNone(member_link)
        self.__class__.member_token = member_link["token"]

    def test_06_clicks_are_not_rsvps_or_attendance(self):
        sid = self.session_id
        target = "https://www.meetup.com/example/events/123/"
        admin_click = self.admin.get(f"/meetup/{sid}")
        self.assertEqual(admin_click.status_code, 302)
        self.assertEqual(admin_click.headers["Location"], target)

        member_click = self.member.get(f"/meetup/{sid}/u/{self.member_token}")
        self.assertEqual(member_click.status_code, 302)
        anon_click = self.anon.get(f"/meetup/{sid}")
        self.assertEqual(anon_click.status_code, 302)

        clicks = rows("SELECT * FROM meetup_clicks WHERE session_id=%s ORDER BY id", (sid,))
        self.assertEqual(len(clicks), 3)
        self.assertEqual(sum(1 for c in clicks if c["identified_by"] == "member_link"), 1)
        self.assertEqual(sum(1 for c in clicks if c["user_id"] is None), 1)
        self.assertEqual(one("SELECT count(*) AS n FROM rsvp_records WHERE session_id=%s", (sid,))["n"], 0)
        self.assertEqual(one("SELECT count(*) AS n FROM attendance_records WHERE session_id=%s", (sid,))["n"], 0)
        self.assertEqual(one("SELECT meetup_rsvp_count FROM club_sessions WHERE id=%s", (sid,))["meetup_rsvp_count"], 0)

    def test_07_rsvp_and_attendance_are_separate(self):
        sid = self.session_id
        rsvp = self.post(self.admin, f"/admin/sessions/{sid}", {
            "action": "rsvp", "user_id": str(self.member_id), "status": "verified",
            "source": "manual", "notes": "Confirmed on Meetup",
        }, f"/admin/sessions/{sid}")
        self.assertEqual(rsvp.status_code, 302)

        reported = self.post(self.admin, f"/admin/sessions/{sid}", {
            "action": "update", "title": "Session 4 — Serverless",
            "starts_at": "2027-01-15T18:00", "ends_at": "2027-01-15T20:00",
            "location": "MainLab", "meetup_event_id": "evt-123",
            "meetup_url": "https://www.meetup.com/example/events/123/",
            "meetup_rsvp_count": "9", "status": "scheduled", "description": "Building with Lambda.",
        }, f"/admin/sessions/{sid}")
        self.assertEqual(reported.status_code, 302)
        self.assertEqual(one("SELECT meetup_rsvp_count FROM club_sessions WHERE id=%s", (sid,))["meetup_rsvp_count"], 9)

        attendance = self.post(self.admin, f"/admin/sessions/{sid}", {
            "action": "attendance", "attendees": str(self.member_id), "mark_others_absent": "1",
        }, f"/admin/sessions/{sid}")
        self.assertEqual(attendance.status_code, 302)
        self.assertEqual(one("SELECT status FROM attendance_records WHERE session_id=%s AND user_id=%s", (sid, self.member_id))["status"], "present")
        self.assertEqual(one("SELECT count(*) AS n FROM rsvp_records WHERE session_id=%s", (sid,))["n"], 1)
        self.assertIn("verified", self.member.get(f"/member/sessions/{sid}").get_data(as_text=True))

    def test_08_task_lifecycle(self):
        created = self.post(self.admin, "/admin/tasks", {
            "title": "Deploy a Lambda function",
            "description": "Create and deploy a small function.",
            "instructions": "Push a repository link as evidence.",
            "due_at": "2027-02-01T17:00", "scope": "selected",
        }, "/admin/tasks")
        self.assertEqual(created.status_code, 302)
        task = one("SELECT * FROM tasks WHERE title='Deploy a Lambda function'")
        self.__class__.task_id = task["id"]

        assigned = self.post(self.admin, f"/admin/tasks/{task['id']}", {
            "action": "assign", "scope": "selected", "user_ids": str(self.member_id),
        }, f"/admin/tasks/{task['id']}")
        self.assertEqual(assigned.status_code, 302)
        published = self.post(self.admin, f"/admin/tasks/{task['id']}", {"action": "publish"}, f"/admin/tasks/{task['id']}")
        self.assertEqual(published.status_code, 302)
        self.assertEqual(one("SELECT status FROM tasks WHERE id=%s", (task["id"],))["status"], "published")

        self.assertIn("Deploy a Lambda function", self.member.get("/member/tasks").get_data(as_text=True))
        progress = self.post(self.member, f"/member/tasks/{task['id']}", {"action": "progress"}, f"/member/tasks/{task['id']}")
        self.assertEqual(progress.status_code, 302)
        self.assertEqual(one("SELECT status FROM task_submissions WHERE task_id=%s AND user_id=%s", (task["id"], self.member_id))["status"], "in_progress")

        submitted = self.post(self.member, f"/member/tasks/{task['id']}", {
            "action": "submit", "note": "Deployed and tested the function.",
            "evidence_url": "https://github.com/miamember/lambda-demo",
        }, f"/member/tasks/{task['id']}")
        self.assertEqual(submitted.status_code, 302)
        sub = one("SELECT * FROM task_submissions WHERE task_id=%s AND user_id=%s", (task["id"], self.member_id))
        self.assertEqual(sub["status"], "submitted")

        review = self.post(self.admin, f"/admin/tasks/{task['id']}", {
            "action": "review", "submission_id": str(sub["id"]),
            "decision": "approved", "review_note": "Great work.",
        }, f"/admin/tasks/{task['id']}")
        self.assertEqual(review.status_code, 302)
        self.assertEqual(one("SELECT status FROM task_submissions WHERE id=%s", (sub["id"],))["status"], "approved")

    def test_09_learning_submissions_and_verification(self):
        bc = self.post(self.member, "/member/learning/builder-center", {
            "profile_url": "https://builder.aws.com/miamember",
            "builder_id": "miamember-123", "display_name": "Mia Mensah",
            "notes": "My public builder profile",
        }, "/member/learning")
        self.assertEqual(bc.status_code, 302)
        sb = self.post(self.member, "/member/learning/skill-builder", {
            "course_name": "AWS Cloud Practitioner Essentials",
            "completion_url": "https://skillbuilder.aws/learn/courses/example",
            "hours": "6.5", "notes": "Completed the course",
        }, "/member/learning")
        self.assertEqual(sb.status_code, 302)
        ach = self.post(self.member, "/member/learning/achievements", {
            "category": "certification", "title": "AWS Certified Cloud Practitioner",
            "issuer": "AWS", "earned_at": "2026-06-01",
            "evidence_url": "https://www.credly.com/badges/example",
        }, "/member/learning")
        self.assertEqual(ach.status_code, 302)

        self.assertEqual(one("SELECT count(*) AS n FROM builder_center_profiles WHERE user_id=%s", (self.member_id,))["n"], 1)
        self.assertEqual(one("SELECT count(*) AS n FROM verification_records WHERE user_id=%s", (self.member_id,))["n"], 3)

        self.assertEqual(self.admin.get("/admin/verifications").status_code, 200)
        bc_row = one("SELECT * FROM builder_center_profiles WHERE user_id=%s", (self.member_id,))
        decision = self.post(self.admin, f"/admin/verifications/builder_center/{bc_row['id']}", {
            "decision": "approved", "review_note": "Profile matches the member.",
        }, f"/admin/verifications/builder_center/{bc_row['id']}")
        self.assertEqual(decision.status_code, 302)
        self.assertEqual(one("SELECT status FROM builder_center_profiles WHERE id=%s", (bc_row["id"],))["status"], "approved")

        sb_row = one("SELECT * FROM skill_builder_submissions WHERE user_id=%s", (self.member_id,))
        corrections = self.post(self.admin, f"/admin/verifications/skill_builder/{sb_row['id']}", {
            "decision": "corrections_requested", "review_note": "Please add a dated certificate link.",
        }, f"/admin/verifications/skill_builder/{sb_row['id']}")
        self.assertEqual(corrections.status_code, 302)
        self.assertIn("corrections_requested", one("SELECT status FROM skill_builder_submissions WHERE id=%s", (sb_row["id"],))["status"])
        self.assertGreaterEqual(one("SELECT count(*) AS n FROM verification_records WHERE user_id=%s", (self.member_id,))["n"], 4)

    def test_10_reports_and_audit(self):
        for name in ["members", "attendance", "meetup", "tasks", "verifications"]:
            response = self.admin.get(f"/admin/reports/{name}.csv")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/csv", response.headers["Content-Type"])
        meetup_csv = self.admin.get("/admin/reports/meetup.csv").get_data(as_text=True)
        self.assertIn("Session 4 — Serverless", meetup_csv)
        header = meetup_csv.splitlines()[0]
        for label in ["Total clicks", "Reported RSVPs", "Verified RSVP records", "Actual attendance"]:
            self.assertIn(label, header)
        self.assertEqual(self.admin.get("/admin/audit").status_code, 200)
        self.assertGreater(one("SELECT count(*) AS n FROM audit_logs")["n"], 10)

    def test_11_logout(self):
        for client, protected in [(self.admin, "/admin/dashboard"), (self.member, "/member/dashboard")]:
            self.post(client, "/logout", {}, protected)
            response = client.get(protected)
            self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main(verbosity=2)
