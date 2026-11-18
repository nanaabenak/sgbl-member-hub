# SGBL Member Hub

A real Flask + PostgreSQL member portal and administrator dashboard for the AWS Student Builder Group. It sits beside the **existing, unchanged** Builder Card website (`../AWSBuildersBadge---UMaT/`) and reuses its green/grey/white palette, JetBrains Mono typography, pixel details, dark mode and responsive layout.

There is no demo or mock data in this application. Accounts, sessions, tasks, evidence and verification decisions are real records created through the UI or the bootstrap scripts.

---

## Contents

- [What is included](#what-is-included)
- [How the pieces fit together](#how-the-pieces-fit-together)
- [Requirements](#requirements)
- [Local development](#local-development)
- [First administrator and first member](#first-administrator-and-first-member)
- [Daily workflows](#daily-workflows)
- [Tracked Meetup links](#tracked-meetup-links)
- [Environment variables](#environment-variables)
- [Automated workflow tests](#automated-workflow-tests)
- [Deployment to one Amazon Linux EC2 instance](#deployment-to-one-amazon-linux-ec2-instance)
- [Restricted lab: User Data only](#restricted-lab-user-data-only)
- [Moving PostgreSQL to Amazon RDS](#moving-postgresql-to-amazon-rds)
- [Backup and restore](#backup-and-restore)
- [Security notes](#security-notes)
- [Troubleshooting](#troubleshooting)

---

## What is included

| Area | Member portal | Admin dashboard |
| --- | --- | --- |
| Profile | Full name, student ID, contact, programme, bio, **Builder ID**, **Builder Center URL**, **Builder Card link** | Create/edit members, set role, activate/disable, set membership status |
| Sessions | Session list, details, personal/aggregate Meetup links, RSVP and attendance status | Create sessions, Meetup URL/ID, per-member tracked links, reported RSVP count, verified RSVPs, attendance, cancels |
| Tasks | See assigned/published tasks, mark **in progress**, submit note + evidence URL, see approval status | Create tasks, assign to selected members/all members, publish, review submissions (approve/reject/corrections) |
| Learning | Submit Builder Center profile, Skill Builder course, certification/badge with evidence URL | Review each submission, leave decision notes, full verification history |
| Reports | — | Overview metrics and CSV exports for members, attendance, Meetup metrics, tasks and verifications |
| Audit | — | Searchable audit log of sign-ins, reviews, RSVP/attendance changes and admin actions |

Key files:

```text
memberhub/
├── migrations/001_init.sql          # Full PostgreSQL schema (idempotent)
├── memberhub/                       # Flask application package
│   ├── blueprints/                  # auth, member, admin, meetup routes
│   ├── templates/                   # Shared Builder Card-styled UI
│   └── static/                      # theme.css and app.js
├── scripts/
│   ├── init_db.py                   # Create DB + apply schema
│   ├── create_admin.py              # Bootstrap first administrator
│   ├── backup.sh / restore.sh       # pg_dump / pg_restore helpers
│   └── test_workflows.py            # 11 end-to-end tests against real PostgreSQL
├── deploy/
│   ├── deploy.sh                    # Single EC2 installer (Amazon Linux 2023)
│   ├── nginx.conf                   # Final HTTPS config (with /card/ alias)
│   ├── nginx-bootstrap.conf         # Temporary HTTP config used before certbot
│   ├── gunicorn_conf.py             # 127.0.0.1:8000, 3 gthread workers
│   └── memberhub.service            # systemd unit
├── .env.example
├── requirements.txt
└── wsgi.py
```

---

## How the pieces fit together

```text
Browser
   │  HTTPS :443
   ▼
Nginx ───────────────► Gunicorn (127.0.0.1:8000) ──► Flask ──► PostgreSQL
   │                                                        (local now,
   │ /card/                                                  RDS later)
   ▼
/opt/memberhub/builder-card/   ← copy of the original Builder Card site
```

- **Nginx** terminates TLS, serves `/card/` directly, and proxies everything else to Gunicorn.
- **Gunicorn** runs the Flask app with 3 gthread workers.
- **Flask** uses server-side sessions stored in PostgreSQL, CSRF tokens on every form, bcrypt password hashes and role-based access control.
- **PostgreSQL** is addressed only through `DATABASE_URL`. Switching to RDS is an environment change, not a code change.

---

## Requirements

### Local development

- Python 3.10+ (3.11/3.13 also fine)
- PostgreSQL server running locally, or a reachable PostgreSQL connection string
- `python3-venv` / `python3-pip`
- A browser

### Deployment

- One Amazon Linux 2023 EC2 instance
- Elastic IP (recommended) and a DNS A record pointing to it
- Security group inbound: SSH `22` from your IP, HTTP `80` and HTTPS `443` from `0.0.0.0/0`
- At least 2 GB RAM recommended for PostgreSQL + 3 Gunicorn workers

---

## Local development

Run every command below from this `memberhub/` directory.

### 1. Create a virtual environment and install dependencies

```bash
cd memberhub
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Create your `.env`

```bash
cp .env.example .env
```

Generate a real secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

For local work, use something like this in `.env`:

```dotenv
FLASK_CONFIG=development
SECRET_KEY=paste-the-generated-hex-here
DATABASE_URL=postgresql:///sgbl_member_hub
SESSION_COOKIE_SECURE=false
BEHIND_HTTPS_PROXY=false
SESSION_LIFETIME_SECONDS=43200
SESSION_IDLE_TIMEOUT_SECONDS=7200
CLUB_NAME=AWS Student Builder Group
BUILDER_CARD_URL=/card/
```

Notes:

- `postgresql:///sgbl_member_hub` connects over the local Unix socket using your current OS user. If that does not work, use `postgresql://your_db_user:your_password@localhost:5432/sgbl_member_hub`.
- Quote values containing special characters, e.g. `DATABASE_URL="postgresql://sgbl:p@ss word@localhost:5432/sgbl_member_hub"`.
- `BUILDER_CARD_URL=/card/` works behind the supplied Nginx config. For purely local Flask running, you can set it to the public URL of the existing Builder Card site instead.

### 3. Initialise the database

```bash
python3 scripts/init_db.py
```

This creates the database if needed and applies `migrations/001_init.sql`. It is safe to run again; it does **not** insert sample members.

### 4. Start the development server

```bash
flask --app wsgi:application run --debug
```

Open <http://127.0.0.1:5000/login>.

---

## First administrator and first member

### Create the first administrator

With the environment still active:

```bash
python3 scripts/create_admin.py
```

You will be prompted for username, email, full name and a temporary password. The password must be at least 10 characters and contain letters and numbers.

Non-interactive form (useful on a server):

```bash
ADMIN_USERNAME=admin1 \
ADMIN_EMAIL=admin1@example.com \
ADMIN_NAME="Ada Admin" \
ADMIN_PASSWORD="ChooseAStrongPassword1" \
python3 scripts/create_admin.py
```

If the username already exists, this script resets that user's password and promotes them to administrator. It also writes an `admin.bootstrap` audit entry.

### Add members

Two supported paths:

1. **Self-registration + approval** — a member visits `/register`, submits their details, and is created with `membership_status = pending`. An admin opens **Admin → Members**, selects the member, sets membership status to `active`, and checks **Account active**.
2. **Admin-created member** — an admin opens **Admin → Members → Create member** and enters the details directly.

Members cannot access `/admin/*` routes. A 403 page is shown if they try.

---

## Daily workflows

### Member

1. Sign in at `/login`.
2. Open **Profile** and add student ID, phone, programme, GitHub username, **Builder ID**, **Builder Center URL** and **Builder Card link**.
3. Open **Sessions** and use the tracked Meetup link for a session. Your personal link remembers which member clicked it.
4. Open **Tasks**, set a task to **In progress**, then submit a note and evidence URL. Watch for `Submitted`, `Approved`, `Rejected` or `Corrections requested`.
5. Open **Learning**, submit:
   - Builder Center profile URL + Builder ID,
   - Skill Builder course + completion URL + hours,
   - Certification or badge + issuer + date + evidence URL.
6. Check the status of each submission on the same page.

### Administrator

1. **Members** — review pending registrations, activate accounts, correct profile details, change roles and disable accounts.
2. **Sessions** — create a session with title, date/time, location, Meetup event ID and Meetup URL. Clicking **Create** generates the aggregate tracked link. Use **Create member link** to generate a secret per-member URL.
3. **RSVPs and attendance** — on a session detail page:
   - enter the **reported RSVP count** copied from Meetup,
   - add **verified individual RSVP records** for named members,
   - mark **actual attendance** (present/absent) after the event.
4. **Tasks** — create a task, assign it to selected members or all members, publish it, then approve/reject/request corrections on each submission.
5. **Verifications** — filter by kind or status, open a submission, approve/reject/request corrections and leave a review note. Every decision is appended to `verification_records`.
6. **Reports** — open `/admin/reports` and download CSVs for `members`, `attendance`, `meetup`, `tasks` and `verifications`.
7. **Audit** — open `/admin/audit` to review security-relevant actions.

---

## Tracked Meetup links

Two link shapes exist:

```text
/meetup/<session_id>                  aggregate link; identifies the clicker only if logged in
/meetup/<session_id>/u/<secret_token> member-specific link; identifies the member even when not logged in
```

Both return a `302` redirect to the session's `meetup_url` and write one row to `meetup_clicks`:

- session ID and link ID
- user ID when known
- `identified_by`: `anonymous`, `authenticated_member` or `member_link`
- a one-way hashed IP address (no raw IP is stored)

**A tracked click is never an RSVP and never attendance.** It does not create `rsvp_records`, `attendance_records`, and it does not change `meetup_rsvp_count`. Those are separate, administrator-controlled metrics:

| Metric | Source |
| --- | --- |
| Total clicks / unique clicks / identified clicks | `meetup_clicks` |
| Reported RSVPs | Admin-entered `club_sessions.meetup_rsvp_count` from Meetup |
| Verified RSVP records | Admin-entered rows in `rsvp_records` |
| Actual attendance | Admin-entered rows in `attendance_records` |

The `meetup.csv` export includes all four as separate columns.

---

## Environment variables

| Variable | Purpose | Production default in `.env.example` |
| --- | --- | --- |
| `FLASK_CONFIG` | `development`, `testing` or `production` | `production` |
| `SECRET_KEY` | CSRF/session signing secret | generate with `secrets.token_hex(32)` |
| `DATABASE_URL` | PostgreSQL DSN | `postgresql://sgbl:...@localhost:5432/sgbl_member_hub` |
| `SESSION_COOKIE_SECURE` | Send session cookie only over HTTPS | `true` |
| `BEHIND_HTTPS_PROXY` | Make Flask generate `https://` URLs | `true` |
| `SESSION_LIFETIME_SECONDS` | Absolute session lifetime | `43200` (12 h) |
| `SESSION_IDLE_TIMEOUT_SECONDS` | Idle timeout enforced by the app | `7200` (2 h) |
| `CLUB_NAME` | Name shown in the UI | `AWS Student Builder Group` |
| `BUILDER_CARD_URL` | Link to the existing Builder Card | `/card/` |
| `BACKUP_DIR` | Optional override for backup destination | `./backups` |
| `RETENTION_DAYS` | Optional local backup retention | `30` |

Keep `.env` out of version control and set permissions to `600` on a server.

---

## Automated workflow tests

The suite uses a **real throwaway PostgreSQL database** and Flask's test client, including CSRF tokens, separate admin/member sessions, RBAC, tracked redirects, task review, verification decisions, CSV exports and logout.

```bash
python3 scripts/test_workflows.py
```

Expected result:

```text
Ran 11 tests ... OK
```

Details:

- Default test DSN: `postgresql:///sgbl_member_hub_test`
- Override with `TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/other_test_db python3 scripts/test_workflows.py`
- **The test DB is dropped and recreated on every run.** Never point this at production.
- Test accounts are `admin1` / `AdminPass123` and `miamember` / `MemberPass123`, created only inside the test DB.

If database creation fails with a collation-version message, refresh the template database once:

```bash
psql -d postgres -c "ALTER DATABASE template1 REFRESH COLLATION VERSION;"
```

---

## Deployment to one Amazon Linux EC2 instance

### 1. Prepare the server

- Launch Amazon Linux 2023.
- Attach an Elastic IP.
- Open inbound ports `22` (your IP), `80` and `443`.
- Point a DNS A record such as `memberhub.club.example` at the Elastic IP.
- Copy this whole workspace to the instance, keeping the two folders as siblings:

```text
/home/ec2-user/School/AWS SBG/SGBL-Member-Hub/
├── AWSBuildersBadge---UMaT/
└── memberhub/
```

Example from your laptop:

```bash
scp -r "SGBL-Member-Hub" ec2-user@YOUR_PUBLIC_IP:~/
```

### 2. Run the deployment script

```bash
cd ~/SGBL-Member-Hub/memberhub
bash deploy/deploy.sh memberhub.club.example
```

The script:

1. Installs Python, Nginx, PostgreSQL server/contrib, rsync and curl.
2. Initialises local PostgreSQL if needed.
3. Creates the `sgbl` database role and `sgbl_member_hub` database with a generated password.
4. Creates the system user `sgbl`, copies the app to `/opt/memberhub`, and copies the sibling Builder Card folder to `/opt/memberhub/builder-card/`.
5. Creates a virtual environment and installs `requirements.txt`.
6. Writes `/opt/memberhub/.env` with a strong random `SECRET_KEY` and `chmod 600`.
7. Applies the database schema.
8. Installs and starts the `memberhub` systemd service and Nginx.
9. Installs the temporary HTTP bootstrap config if no certificate exists yet, or the final HTTPS config if one does.

The original Builder Card project in your workspace is **not modified**; only a copy is placed on the server.

### 3. Issue the TLS certificate

After DNS has propagated:

```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d memberhub.club.example
```

Certbot upgrades the bootstrap config to HTTPS while keeping the `/card/` alias and the Gunicorn proxy. Renewal is handled by the certbot timer.

If you need to rebuild the final HTTPS config manually after the certificate exists:

```bash
sudo cp /opt/memberhub/deploy/nginx.conf /etc/nginx/conf.d/memberhub.conf
sudo sed -i 's/memberhub.club.example/memberhub.club.example/g' /etc/nginx/conf.d/memberhub.conf
sudo nginx -t && sudo systemctl reload nginx
```

(Change the second `memberhub.club.example` to your real domain when editing by hand.)

### 4. Create the first administrator on the server

```bash
sudo -u sgbl /opt/memberhub/venv/bin/python /opt/memberhub/scripts/create_admin.py
```

Or non-interactively:

```bash
sudo -u sgbl env \
  ADMIN_USERNAME=admin1 \
  ADMIN_EMAIL=admin1@example.com \
  ADMIN_NAME="Ada Admin" \
  ADMIN_PASSWORD="ChooseAStrongPassword1" \
  /opt/memberhub/venv/bin/python /opt/memberhub/scripts/create_admin.py
```

### 5. Visit the site

- Member Hub: `https://memberhub.club.example/`
- Login: `https://memberhub.club.example/login`
- Existing Builder Card: `https://memberhub.club.example/card/`
- Health check: `https://memberhub.club.example/health`

### Useful service commands

```bash
sudo systemctl status memberhub
sudo systemctl restart memberhub
sudo journalctl -u memberhub -f
sudo tail -f /var/log/memberhub/error.log
sudo nginx -t && sudo systemctl reload nginx
```

On later code deployments, re-run `bash deploy/deploy.sh <domain>` from the `memberhub/` directory. It preserves `.env` and `backups/`, recreates the virtual environment, reloads the service files and restarts the service. The database password is reset consistently on each run so `.env` always matches the role.

---

## Restricted lab: User Data only

Some AWS training labs give you no key pair and no SSH. In that case the instance must pull everything itself at launch.

1. Create a **public** GitHub repository from the workspace root so it contains both `AWSBuildersBadge---UMaT/` and `memberhub/` as siblings. The root `.gitignore` excludes `.env`, virtual environments, backups, `__pycache__` and the original project's nested `.git` history.
2. Open `deploy/user_data.sh` and replace `REPO_URL` with your public repo URL.
3. Paste the whole file into **Task 1 → User Data** when launching the instance.
4. In **Task 3**, add an inbound rule for **port 80** from `0.0.0.0/0` (or your lab's required CIDR).
5. After boot, open the EC2 console → select the instance → **Monitor and troubleshoot → Get system log**. Look for lines beginning `MEMBERHUB_`. They contain the URL and the generated administrator password.

The User Data script installs PostgreSQL, clones the repo, creates the database and first admin, writes a generated `.env`, applies the schema, and starts Gunicorn on port `80` via systemd. It runs the app as the non-root `sgbl` user using `CAP_NET_BIND_SERVICE`. The Builder Card remains available at `/card/` on the same host because the Flask app serves the cloned sibling folder.

Because `SESSION_COOKIE_SECURE=false` and `BEHIND_HTTPS_PROXY=false` are set in this HTTP-only lab config, do **not** reuse those values for a real public deployment. Also treat the public repo as readable by anyone: never commit real credentials, member data or backups.

If you only need the original Builder Card and want to avoid PostgreSQL entirely, deploy just the static folder with Nginx instead:

```bash
#!/bin/bash
dnf -y install git nginx
git clone --depth 1 https://github.com/YOUR-ORG/YOUR-REPO.git /opt/site
mkdir -p /etc/nginx/conf.d
cat > /etc/nginx/conf.d/default.conf <<'EOF'
server {
    listen 80;
    root /opt/site/AWSBuildersBadge---UMaT;
    index index.html;
    location / { try_files $uri $uri/ =404; }
}
EOF
systemctl enable --now nginx
```

That static-only option loses the member portal, admin dashboard, tracked Meetup links and reports. The User Data hub option keeps all of them.

---

## Moving PostgreSQL to Amazon RDS

The application code does not change. Only the DSN does.

1. Create an RDS PostgreSQL instance in a private subnet.
2. Make sure the EC2 security group is allowed to reach the RDS security group on port `5432`.
3. Create the database and user in RDS, or grant the user `CREATEDB` if you want `init_db.py` to create it.
4. Create the schema:

```bash
sudo -u sgbl env \
  DATABASE_URL='postgresql://sgbl:PASSWORD@my-rds.xxxxxx.eu-west-1.rds.amazonaws.com:5432/sgbl_member_hub' \
  /opt/memberhub/venv/bin/python /opt/memberhub/scripts/init_db.py
```

5. Replace `DATABASE_URL` in `/opt/memberhub/.env` with the RDS URL and restart:

```bash
sudo systemctl restart memberhub
```

6. Take an RDS snapshot before and after the cutover. `scripts/backup.sh` also works against RDS if `pg_dump` is installed.

---

## Backup and restore

### Schedule a backup

```bash
bash scripts/backup.sh
```

This uses `pg_dump -Fc` and writes `./backups/memberhub-YYYYMMDD-HHMMSS.dump`. It keeps 30 days by default. Override with:

```bash
BACKUP_DIR=/var/backups/memberhub RETENTION_DAYS=60 bash scripts/backup.sh
```

Cron example on the EC2 instance:

```cron
0 2 * * * bash /opt/memberhub/scripts/backup.sh >> /var/log/memberhub/backup.log 2>&1
```

Copy backups somewhere outside the instance (for example S3) or rely on RDS snapshots. A local backup on the same EC2 instance does not protect against instance loss.

### Restore

Restoring **replaces all data** in the database pointed to by `DATABASE_URL`.

```bash
sudo systemctl stop memberhub
bash scripts/backup.sh                       # take a final pre-restore backup
bash scripts/restore.sh backups/memberhub-20261118-020000.dump
sudo systemctl start memberhub
```

The restore script asks you to type `RESTORE` before running `pg_restore --clean --if-exists`. Always rehearse the procedure on a staging database first.

---

## Security notes

- Passwords are hashed with **bcrypt**; plaintext passwords are never stored.
- Login sessions are server-side rows in `web_sessions`; the browser receives only an opaque, HttpOnly, SameSite=Lax cookie.
- Every POST form requires a CSRF token. Missing/invalid tokens return 403.
- Roles: `admin` and `member`. All `/admin/*` routes are decorated with `admin_required`; management actions also write audit logs.
- Failed logins are counted; five failures lock an account for 15 minutes.
- Validation is server-side in `memberhub/validation.py` in addition to HTML attributes.
- Production config forces `SESSION_COOKIE_SECURE=true`; Nginx adds HSTS; Flask sets `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options` and `Referrer-Policy`.
- Secrets live only in environment variables / `.env` (`chmod 600`), not in source code.
- Tracked-link IP addresses are stored as one-way hashes, and raw IPs are never written to the database.
- Keep PostgreSQL bound to localhost (or a private RDS subnet). Do not expose port 5432 publicly.
- Change the bootstrap admin password immediately after first login and invite members through the registration/approval flow.

---

## Troubleshooting

| Symptom | Things to check |
| --- | --- |
| `could not connect to server` | `DATABASE_URL`, `systemctl status postgresql`, pg_hba.conf, RDS security group |
| `password authentication failed` | Compare the role password with `.env`; re-run `deploy.sh` or `ALTER ROLE sgbl PASSWORD '...'` |
| POST returns 403 | CSRF token missing/expired — reload the form and try again |
| Member gets 403 on `/admin/...` | Expected: RBAC is working |
| `/card/` returns 404 | Confirm `/opt/memberhub/builder-card/index.html` exists and the Nginx alias points there |
| Nginx fails with missing certificate file | DNS is probably not pointed yet; use `deploy/nginx-bootstrap.conf`, run certbot, then reload Nginx |
| CSS/JS/fonts blocked | Do not add inline scripts — CSP uses `script-src 'self'`; external JS lives in `static/js/app.js` |
| `template database "template1" has a collation version mismatch` | Run `psql -d postgres -c "ALTER DATABASE template1 REFRESH COLLATION VERSION;"` once |
| Gunicorn will not start | `sudo journalctl -u memberhub -n 100`, `sudo tail -50 /var/log/memberhub/error.log`, check `/opt/memberhub/.env` |

---

**Status:** source, schema, scripts, tests and deployment artifacts are complete. Run `python3 scripts/test_workflows.py` before any production deployment, and complete the EC2/DNS/certbot steps above to make the hub live.
