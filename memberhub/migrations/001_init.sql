-- SGBL Member Hub - initial schema (PostgreSQL)
-- Idempotent: safe to re-run. Applied by scripts/init_db.py.

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Roles and permissions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE CHECK (name IN ('member', 'admin')),
  description TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO roles (name, description) VALUES
  ('member', 'Club member - access to the member portal'),
  ('admin', 'Club administrator - full dashboard access')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS permissions (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT ''
);

INSERT INTO permissions (name, description) VALUES
  ('member.portal', 'View the member portal'),
  ('admin.dashboard', 'View the administration dashboard'),
  ('admin.members', 'Manage members'),
  ('admin.sessions', 'Manage sessions and attendance'),
  ('admin.tasks', 'Manage tasks and submissions'),
  ('admin.verifications', 'Review verification submissions'),
  ('admin.reports', 'View and export reports')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS role_permissions (
  role_id       INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Users, web sessions and member profiles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id              SERIAL PRIMARY KEY,
  username        TEXT NOT NULL UNIQUE,
  email           TEXT NOT NULL UNIQUE,
  password_hash   TEXT NOT NULL,
  role_id         INTEGER NOT NULL REFERENCES roles(id),
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until    TIMESTAMPTZ,
  last_login_at   TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT users_username_format CHECK (username ~ '^[A-Za-z0-9._-]{3,32}$'),
  CONSTRAINT users_email_basic CHECK (email = lower(email) AND position('@' in email) > 1)
);

DROP TRIGGER IF EXISTS users_updated ON users;
CREATE TRIGGER users_updated BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS web_sessions (
  id          SERIAL PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sid_hash    TEXT NOT NULL UNIQUE,
  csrf_token  TEXT NOT NULL,
  ip_hash     TEXT,
  user_agent  TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS web_sessions_user_idx ON web_sessions(user_id);

CREATE TABLE IF NOT EXISTS member_profiles (
  user_id           INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  full_name         TEXT NOT NULL,
  student_id        TEXT NOT NULL DEFAULT '',
  phone             TEXT NOT NULL DEFAULT '',
  location          TEXT NOT NULL DEFAULT '',
  program           TEXT NOT NULL DEFAULT '',
  bio               TEXT NOT NULL DEFAULT '',
  github_username   TEXT NOT NULL DEFAULT '',
  builder_card_url  TEXT NOT NULL DEFAULT '',
  builder_center_url TEXT NOT NULL DEFAULT '',
  builder_id        TEXT NOT NULL DEFAULT '',
  membership_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (membership_status IN ('pending', 'active', 'inactive', 'suspended')),
  joined_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  verified_at       TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS member_profiles_updated ON member_profiles;
CREATE TRIGGER member_profiles_updated BEFORE UPDATE ON member_profiles FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS member_profiles_status_idx ON member_profiles(membership_status);

-- ---------------------------------------------------------------------------
-- Club sessions, Meetup tracking, RSVP and attendance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS club_sessions (
  id                SERIAL PRIMARY KEY,
  title             TEXT NOT NULL,
  description       TEXT NOT NULL DEFAULT '',
  starts_at         TIMESTAMPTZ NOT NULL,
  ends_at           TIMESTAMPTZ,
  location          TEXT NOT NULL DEFAULT '',
  meetup_url        TEXT NOT NULL DEFAULT '',
  meetup_event_id   TEXT NOT NULL DEFAULT '',
  -- Aggregate count reported by Meetup. Never derived from clicks.
  meetup_rsvp_count INTEGER NOT NULL DEFAULT 0 CHECK (meetup_rsvp_count >= 0),
  rsvp_count_reported_at TIMESTAMPTZ,
  status            TEXT NOT NULL DEFAULT 'scheduled'
    CHECK (status IN ('scheduled', 'completed', 'cancelled')),
  created_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS club_sessions_updated ON club_sessions;
CREATE TRIGGER club_sessions_updated BEFORE UPDATE ON club_sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS meetup_links (
  id         SERIAL PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES club_sessions(id) ON DELETE CASCADE,
  user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('aggregate', 'member')),
  token      TEXT UNIQUE,
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT meetup_links_kind_user CHECK (kind <> 'member' OR user_id IS NOT NULL),
  CONSTRAINT meetup_links_unique_member UNIQUE (session_id, user_id, kind)
);
CREATE INDEX IF NOT EXISTS meetup_links_session_idx ON meetup_links(session_id);

CREATE TABLE IF NOT EXISTS meetup_clicks (
  id            BIGSERIAL PRIMARY KEY,
  session_id    INTEGER NOT NULL REFERENCES club_sessions(id) ON DELETE CASCADE,
  link_id       INTEGER NOT NULL REFERENCES meetup_links(id) ON DELETE CASCADE,
  -- Set only when the click is identifiable (member link or logged-in member).
  user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
  identified_by TEXT NOT NULL DEFAULT 'anonymous'
    CHECK (identified_by IN ('anonymous', 'member_link', 'authenticated_member')),
  ip_hash       TEXT NOT NULL,
  clicked_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS meetup_clicks_session_idx ON meetup_clicks(session_id);
CREATE INDEX IF NOT EXISTS meetup_clicks_user_idx ON meetup_clicks(user_id);

CREATE TABLE IF NOT EXISTS rsvp_records (
  id             SERIAL PRIMARY KEY,
  session_id     INTEGER NOT NULL REFERENCES club_sessions(id) ON DELETE CASCADE,
  user_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
  meetup_member_id TEXT NOT NULL DEFAULT '',
  status         TEXT NOT NULL DEFAULT 'verified'
    CHECK (status IN ('verified', 'cancelled')),
  source         TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'import')),
  verified_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  verified_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes          TEXT NOT NULL DEFAULT '',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT rsvp_one_member UNIQUE (session_id, user_id),
  CONSTRAINT rsvp_identity_required CHECK (user_id IS NOT NULL OR meetup_member_id <> '')
);
CREATE INDEX IF NOT EXISTS rsvp_records_session_idx ON rsvp_records(session_id);

CREATE TABLE IF NOT EXISTS attendance_records (
  id           SERIAL PRIMARY KEY,
  session_id   INTEGER NOT NULL REFERENCES club_sessions(id) ON DELETE CASCADE,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status       TEXT NOT NULL DEFAULT 'present'
    CHECK (status IN ('present', 'absent', 'excused')),
  checked_in_at TIMESTAMPTZ,
  recorded_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  notes        TEXT NOT NULL DEFAULT '',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, user_id)
);
DROP TRIGGER IF EXISTS attendance_records_updated ON attendance_records;
CREATE TRIGGER attendance_records_updated BEFORE UPDATE ON attendance_records FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Tasks and submissions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
  id           SERIAL PRIMARY KEY,
  title        TEXT NOT NULL,
  description  TEXT NOT NULL DEFAULT '',
  instructions TEXT NOT NULL DEFAULT '',
  due_at       TIMESTAMPTZ,
  scope        TEXT NOT NULL DEFAULT 'all' CHECK (scope IN ('all', 'selected')),
  status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'closed')),
  created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS tasks_updated ON tasks;
CREATE TRIGGER tasks_updated BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS task_assignments (
  id          SERIAL PRIMARY KEY,
  task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, user_id)
);

CREATE TABLE IF NOT EXISTS task_submissions (
  id           SERIAL PRIMARY KEY,
  task_id      INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status       TEXT NOT NULL DEFAULT 'not_started'
    CHECK (status IN ('not_started', 'in_progress', 'submitted', 'approved', 'rejected', 'corrections_requested')),
  note         TEXT NOT NULL DEFAULT '',
  evidence_url TEXT NOT NULL DEFAULT '',
  submitted_at TIMESTAMPTZ,
  reviewed_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at  TIMESTAMPTZ,
  review_note  TEXT NOT NULL DEFAULT '',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, user_id)
);
DROP TRIGGER IF EXISTS task_submissions_updated ON task_submissions;
CREATE TRIGGER task_submissions_updated BEFORE UPDATE ON task_submissions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX IF NOT EXISTS task_submissions_status_idx ON task_submissions(status);

-- ---------------------------------------------------------------------------
-- Learning and achievement submissions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS builder_center_profiles (
  id          SERIAL PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  profile_url TEXT NOT NULL DEFAULT '',
  builder_id  TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  evidence_url TEXT NOT NULL DEFAULT '',
  notes       TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'approved', 'rejected', 'corrections_requested')),
  reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at TIMESTAMPTZ,
  review_note TEXT NOT NULL DEFAULT '',
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS builder_center_profiles_updated ON builder_center_profiles;
CREATE TRIGGER builder_center_profiles_updated BEFORE UPDATE ON builder_center_profiles FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS skill_builder_submissions (
  id           SERIAL PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_name  TEXT NOT NULL,
  completion_url TEXT NOT NULL DEFAULT '',
  evidence_url TEXT NOT NULL DEFAULT '',
  hours        NUMERIC(6,2),
  notes        TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'approved', 'rejected', 'corrections_requested')),
  reviewed_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at  TIMESTAMPTZ,
  review_note  TEXT NOT NULL DEFAULT '',
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS skill_builder_submissions_updated ON skill_builder_submissions;
CREATE TRIGGER skill_builder_submissions_updated BEFORE UPDATE ON skill_builder_submissions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS achievement_records (
  id           SERIAL PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category     TEXT NOT NULL CHECK (category IN ('certification', 'badge')),
  title        TEXT NOT NULL,
  issuer       TEXT NOT NULL DEFAULT '',
  evidence_url TEXT NOT NULL DEFAULT '',
  earned_at    DATE,
  notes        TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'approved', 'rejected', 'corrections_requested')),
  reviewed_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at  TIMESTAMPTZ,
  review_note  TEXT NOT NULL DEFAULT '',
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS achievement_records_updated ON achievement_records;
CREATE TRIGGER achievement_records_updated BEFORE UPDATE ON achievement_records FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS verification_records (
  id           BIGSERIAL PRIMARY KEY,
  subject_type TEXT NOT NULL CHECK (subject_type IN ('builder_center', 'skill_builder', 'achievement')),
  subject_id   INTEGER NOT NULL,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status       TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'corrections_requested')),
  reviewed_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at  TIMESTAMPTZ,
  notes        TEXT NOT NULL DEFAULT '',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS verification_records_subject_idx ON verification_records(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS verification_records_status_idx ON verification_records(status);

-- ---------------------------------------------------------------------------
-- Audit log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
  id          BIGSERIAL PRIMARY KEY,
  actor_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action      TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT '',
  target_id   TEXT NOT NULL DEFAULT '',
  details     TEXT NOT NULL DEFAULT '',
  ip_hash     TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_logs_created_idx ON audit_logs(created_at DESC);
