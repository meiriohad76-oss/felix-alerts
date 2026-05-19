#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sentinel}"
SERVICE_USER="${SERVICE_USER:-sentinel}"
ENV_DIR="${ENV_DIR:-/etc/sentinel}"
DATA_DIR="${DATA_DIR:-/var/lib/sentinel}"
LOG_DIR="${LOG_DIR:-/var/log/sentinel}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/raspberry-pi/install.sh" >&2
  exit 1
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

mkdir -p "${APP_DIR}" "${ENV_DIR}" "${DATA_DIR}" "${LOG_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}" "${DATA_DIR}" "${LOG_DIR}"
chmod 750 "${DATA_DIR}" "${LOG_DIR}"

apt-get update
apt-get install -y python3 python3-venv python3-pip

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip

if [[ ! -f "${ENV_DIR}/sentinel.env" ]]; then
  cp "${APP_DIR}/deploy/raspberry-pi/env.example" "${ENV_DIR}/sentinel.env"
  chmod 640 "${ENV_DIR}/sentinel.env"
  chown root:"${SERVICE_USER}" "${ENV_DIR}/sentinel.env"
  echo "Created ${ENV_DIR}/sentinel.env. Edit it before starting Sentinel."
fi

cp "${APP_DIR}/deploy/raspberry-pi/sentinel.service" /etc/systemd/system/sentinel.service
systemctl daemon-reload
systemctl enable sentinel.service

echo "Install complete. Next:"
echo "  sudo nano ${ENV_DIR}/sentinel.env"
echo "  sudo systemctl start sentinel"
echo "  curl http://127.0.0.1:8765/health"
