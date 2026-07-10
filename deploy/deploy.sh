#!/bin/bash
# Zero-downtime deploy: pull latest code and restart services.
# Run as root or socialcredit user with sudo rights on the VPS.
set -e

APP_DIR="/opt/socialcredit"
APP_USER="socialcredit"

echo "=== Pulling latest code ==="
sudo -u $APP_USER git -C $APP_DIR pull

echo "=== Installing any new dependencies ==="
sudo -u $APP_USER $APP_DIR/venv/bin/pip install -q -r $APP_DIR/requirements.txt

echo "=== Restarting services ==="
systemctl restart socialcredit-gateway
systemctl restart socialcredit-scheduler
systemctl restart socialcredit-web

echo "=== Status ==="
systemctl status socialcredit-gateway --no-pager -l
systemctl status socialcredit-scheduler --no-pager -l
systemctl status socialcredit-web --no-pager -l

echo "=== Deploy complete ==="
