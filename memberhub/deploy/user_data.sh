#!/bin/bash
# EC2 User Data for the restricted Builder Lab: no SSH, no key pair, HTTP only.
# Replace REPO_URL, then paste this entire file into User Data at launch.
set -euo pipefail

REPO_URL="https://github.com/nanaabenak/sgbl-member-hub.git"
APP_ROOT=/opt/memberhub-src
VENV=/opt/memberhub-venv
DB_NAME=sgbl_member_hub
DB_USER=sgbl
ADMIN_USERNAME=admin1
ADMIN_EMAIL=admin1@example.com
ADMIN_NAME="Ada Admin"
# Leave empty to generate a random password and print it in the boot log.
ADMIN_PASSWORD=""

echo "==> Installing packages"
dnf -y install git python3 python3-pip postgresql-server postgresql-contrib curl

echo "==> Preparing local PostgreSQL"
if [ ! -f /var/lib/pgsql/data/PG_VERSION ]; then
  postgresql-setup --initdb
fi
systemctl enable --now postgresql

DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN;
  END IF;
END
\$\$;
ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec
SQL

echo "==> Cloning the Member Hub + Builder Card from GitHub"
rm -rf "$APP_ROOT"
git clone --depth 1 "$REPO_URL" "$APP_ROOT"

if [ ! -f "$APP_ROOT/memberhub/wsgi.py" ] || [ ! -f "$APP_ROOT/AWSBuildersBadge---UMaT/index.html" ]; then
  echo "ERROR: repo must contain both memberhub/ and AWSBuildersBadge---UMaT/" >&2
  exit 1
fi

id -u "$DB_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_ROOT" --shell /sbin/nologin "$DB_USER"
chown -R "${DB_USER}:${DB_USER}" "$APP_ROOT"

echo "==> Installing Python dependencies"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$APP_ROOT/memberhub/requirements.txt"

SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
cat > "$APP_ROOT/memberhub/.env" <<ENV
FLASK_CONFIG=production
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
SESSION_COOKIE_SECURE=false
BEHIND_HTTPS_PROXY=false
SESSION_LIFETIME_SECONDS=43200
SESSION_IDLE_TIMEOUT_SECONDS=7200
CLUB_NAME=AWS Student Builder Group
BUILDER_CARD_URL=/card/
ENV
chmod 600 "$APP_ROOT/memberhub/.env"
chown "${DB_USER}:${DB_USER}" "$APP_ROOT/memberhub/.env"

echo "==> Applying database schema"
cd "$APP_ROOT/memberhub"
"$VENV/bin/python" scripts/init_db.py

if [ -z "$ADMIN_PASSWORD" ]; then
  ADMIN_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
fi
ADMIN_USERNAME="$ADMIN_USERNAME" \
ADMIN_EMAIL="$ADMIN_EMAIL" \
ADMIN_NAME="$ADMIN_NAME" \
ADMIN_PASSWORD="$ADMIN_PASSWORD" \
"$VENV/bin/python" scripts/create_admin.py

echo "==> Starting Gunicorn on port 80"
cat > /etc/systemd/system/memberhub.service <<'EOF'
[Unit]
Description=SGBL Member Hub (Builder Lab)
After=network.target postgresql.service

[Service]
Type=simple
User=sgbl
Group=sgbl
WorkingDirectory=/opt/memberhub-src/memberhub
EnvironmentFile=/opt/memberhub-src/memberhub/.env
ExecStart=/opt/memberhub-venv/bin/gunicorn --workers 2 --threads 2 --timeout 60 --bind 0.0.0.0:80 wsgi:application
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always
RestartSec=5
KillSignal=SIGQUIT

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now memberhub

# Printed to cloud-init output so you can read it from the EC2 console system log.
echo "MEMBERHUB_URL=http://$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4)/"
echo "MEMBERHUB_LOGIN=$ADMIN_USERNAME"
echo "MEMBERHUB_PASSWORD=$ADMIN_PASSWORD"
echo "MEMBERHUB_BUILDER_CARD=/card/ on the same host"
