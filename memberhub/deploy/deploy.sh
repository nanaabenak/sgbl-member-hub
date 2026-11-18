#!/usr/bin/env bash
# Amazon Linux 2023 deployment for a single EC2 instance.
# Run as ec2-user with sudo:  bash deploy/deploy.sh your.domain.example
set -euo pipefail

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
  echo "Usage: bash deploy/deploy.sh <your-domain.example>" >&2
  exit 1
fi

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR=/opt/memberhub
SERVICE_USER=sgbl
DB_NAME=sgbl_member_hub
DB_USER=sgbl
LOG_DIR=/var/log/memberhub

echo "==> Installing system packages"
sudo dnf install -y python3 python3-pip nginx postgresql-server postgresql-contrib rsync curl

echo "==> Initialising local PostgreSQL if needed"
if [ ! -f /var/lib/pgsql/data/PG_VERSION ]; then
  sudo postgresql-setup --initdb
fi
sudo systemctl enable --now postgresql

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

echo "==> Creating application user and directories"
id -u "$SERVICE_USER" >/dev/null 2>&1 || sudo useradd --system --home-dir "$APP_DIR" --shell /sbin/nologin "$SERVICE_USER"
sudo mkdir -p "$APP_DIR" "$LOG_DIR"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR" "$LOG_DIR"

echo "==> Copying application (the existing Builder Card goes to $APP_DIR/builder-card)"
sudo rsync -a --delete --exclude '.git' --exclude 'backups' --exclude '.env' "$SRC/" "$APP_DIR/"
if [ -d "$SRC/../AWSBuildersBadge---UMaT" ]; then
  sudo rsync -a --delete "$SRC/../AWSBuildersBadge---UMaT/" "$APP_DIR/builder-card/"
fi
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

echo "==> Python virtual environment"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
sudo -u "$SERVICE_USER" tee "$APP_DIR/.env" >/dev/null <<ENV
FLASK_CONFIG=production
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
SESSION_COOKIE_SECURE=true
BEHIND_HTTPS_PROXY=true
SESSION_LIFETIME_SECONDS=43200
SESSION_IDLE_TIMEOUT_SECONDS=7200
CLUB_NAME=AWS Student Builder Group
BUILDER_CARD_URL=/card/
ENV
sudo chmod 600 "$APP_DIR/.env"

echo "==> Database schema"
cd "$APP_DIR"
sudo -u "$SERVICE_USER" env DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}" \
  "$APP_DIR/venv/bin/python" scripts/init_db.py

echo "==> Systemd service"
sudo cp "$APP_DIR/deploy/memberhub.service" /etc/systemd/system/memberhub.service
sudo systemctl daemon-reload
sudo systemctl enable --now memberhub

echo "==> Nginx"
# Use the HTTPS config only when a certificate already exists. Otherwise start
# with a safe HTTP bootstrap config; certbot will upgrade it after DNS is live.
CERT_FILE="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
if [ -f "$CERT_FILE" ]; then
  NGINX_CONFIG=nginx.conf
else
  NGINX_CONFIG=nginx-bootstrap.conf
fi
sudo cp "$APP_DIR/deploy/$NGINX_CONFIG" /etc/nginx/conf.d/memberhub.conf
sudo sed -i "s/memberhub.club.example/${DOMAIN}/g" /etc/nginx/conf.d/memberhub.conf
sudo nginx -t && sudo systemctl enable --now nginx

echo "==> Almost done"
if [ ! -f "$CERT_FILE" ]; then
  echo "1. Point DNS A record ${DOMAIN} at this instance's public IP."
  echo "2. Issue a certificate: sudo dnf install -y certbot python3-certbot-nginx && sudo certbot --nginx -d ${DOMAIN}"
else
  echo "1. HTTPS certificate already present for ${DOMAIN}."
fi
echo "3. Create the first administrator:"
echo "   sudo -u ${SERVICE_USER} ${APP_DIR}/venv/bin/python ${APP_DIR}/scripts/create_admin.py"
echo "4. Visit https://${DOMAIN}/  (Builder Card: https://${DOMAIN}/card/)"
