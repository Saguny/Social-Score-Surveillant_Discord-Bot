#!/bin/bash
# Run as root on a fresh Debian/Ubuntu VPS.
# Usage: bash setup.sh
set -e

DOMAIN="YOUR_DOMAIN_HERE"
APP_DIR="/opt/socialcredit"
APP_USER="socialcredit"

echo "=== Installing system packages ==="
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv python3-dev \
    postgresql postgresql-contrib redis-server nginx certbot python3-certbot-nginx \
    git build-essential libpq-dev

echo "=== Creating app user ==="
id -u $APP_USER &>/dev/null || useradd -r -s /bin/bash -d $APP_DIR $APP_USER

echo "=== Setting up app directory ==="
mkdir -p $APP_DIR
chown $APP_USER:$APP_USER $APP_DIR

echo "=== Cloning repo ==="
# Replace with your actual repo URL
sudo -u $APP_USER git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git $APP_DIR

echo "=== Creating virtualenv and installing deps ==="
sudo -u $APP_USER python3 -m venv $APP_DIR/venv
sudo -u $APP_USER $APP_DIR/venv/bin/pip install -U pip
sudo -u $APP_USER $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt

echo "=== Setting up Postgres ==="
sudo -u postgres psql -c "CREATE USER socialcredit WITH PASSWORD 'CHANGE_ME';" || true
sudo -u postgres psql -c "CREATE DATABASE socialcredit OWNER socialcredit;" || true

echo "=== Enabling Redis ==="
systemctl enable --now redis-server

echo "=== Copying .env ==="
echo "IMPORTANT: Copy your .env file to $APP_DIR/.env then run:"
echo "  chown $APP_USER:$APP_USER $APP_DIR/.env && chmod 600 $APP_DIR/.env"

echo "=== Installing systemd services ==="
cp $APP_DIR/deploy/socialcredit-gateway.service   /etc/systemd/system/
cp $APP_DIR/deploy/socialcredit-scheduler.service /etc/systemd/system/
cp $APP_DIR/deploy/socialcredit-web.service       /etc/systemd/system/
systemctl daemon-reload
systemctl enable socialcredit-gateway socialcredit-scheduler socialcredit-web

echo "=== Setting up nginx ==="
cp $APP_DIR/deploy/nginx.conf /etc/nginx/sites-available/socialcredit
sed -i "s/YOUR_DOMAIN_HERE/$DOMAIN/g" /etc/nginx/sites-available/socialcredit
ln -sf /etc/nginx/sites-available/socialcredit /etc/nginx/sites-enabled/socialcredit
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "=== Obtaining SSL cert ==="
certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m YOUR_EMAIL_HERE

echo ""
echo "=== Done! ==="
echo "Next steps:"
echo "  1. Copy .env to $APP_DIR/.env"
echo "  2. Restore Postgres dump: psql -U socialcredit socialcredit < dump.sql"
echo "  3. systemctl start socialcredit-gateway socialcredit-scheduler socialcredit-web"
echo "  4. journalctl -u socialcredit-gateway -f   # to tail logs"
