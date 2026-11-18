#!/bin/bash
# Restricted Builder Lab: static Builder Card only.
# No SSH, no database, no Python app server. Paste this entire file into User Data.
set -euo pipefail

REPO="nanaabenak/sgbl-member-hub"
BRANCH="main"

echo "==> Installing nginx and download tools"
dnf -y install nginx curl tar

echo "==> Downloading the repository"
mkdir -p /opt/builder-card
curl -fsSL "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" \
  -o /tmp/sgbl-member-hub.tar.gz
tar -xzf /tmp/sgbl-member-hub.tar.gz -C /opt/builder-card --strip-components=1

SRC="/opt/builder-card/AWSBuildersBadge---UMaT"
if [ ! -f "$SRC/index.html" ] || [ ! -d "$SRC/libs" ]; then
  echo "ERROR: Builder Card files not found in $SRC" >&2
  exit 1
fi

echo "==> Publishing Builder Card to nginx"
rm -rf /usr/share/nginx/html/*
cp -a "$SRC"/. /usr/share/nginx/html/

echo "==> Starting nginx on port 80"
systemctl enable --now nginx
systemctl reload nginx

PUBLIC_IP="$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
echo "BUILDER_CARD_URL=http://${PUBLIC_IP}/"
echo "FILES_SERVED_FROM=/usr/share/nginx/html/index.html"
