# Sentinel Deployment

This document covers the manual GitHub upload package, Raspberry Pi deployment,
and Cloudflare Tunnel exposure path.

## 1. Manual GitHub Upload

The repository is prepared for manual upload. Before uploading:

1. Do not upload runtime files ignored by `.gitignore`: local SQLite databases,
   logs, PID files, `.env` files, caches, or editor metadata.
2. Confirm no secret values are present in source files:

   ```bash
   rg -n "MASSIVE_API_KEY=|SENTINEL_EMAIL_PASSWORD=|SENTINEL_TELEGRAM_BOT_TOKEN=|api[_-]?key|bot[_-]?token|password" .
   ```

   Expected result: only documentation/examples/placeholders, never a real key.

3. Run tests before upload:

   ```bash
   PYTHONPATH=backend:. python3 -m unittest discover -s tests
   python3 scripts/validate_upload_package.py
   ```

4. Upload source directories and files:
   `backend/`, `frontend/`, `scripts/`, `tests/`, `fixtures/`, `docs/`,
   `deploy/`, `README.md`, and `.gitignore`.

5. Do not upload:
   `sentinel_dev.sqlite3`, `sentinel_dev_server.log`,
   `.sentinel_dev_server.pid`, `.env`, `.venv/`, `__pycache__/`,
   or browser/test caches.

## 2. Raspberry Pi Deployment

Recommended target:

- Raspberry Pi OS Lite 64-bit.
- Python 3.11 or newer if available from the OS image.
- App path: `/opt/sentinel`.
- Database path: `/var/lib/sentinel/sentinel.sqlite3`.
- Environment file: `/etc/sentinel/sentinel.env`.
- Service user: `sentinel`.

### Install

On the Pi:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip
sudo mkdir -p /opt/sentinel
sudo chown "$USER":"$USER" /opt/sentinel
```

Copy or clone the project into `/opt/sentinel`, then run:

```bash
cd /opt/sentinel
sudo bash deploy/raspberry-pi/install.sh
sudo nano /etc/sentinel/sentinel.env
sudo systemctl start sentinel
sudo systemctl status sentinel
curl http://127.0.0.1:8765/health
```

The expected health response is:

```json
{
  "ok": true
}
```

### Environment

Use `deploy/raspberry-pi/env.example` as the template. Required for market data:

```bash
MASSIVE_API_KEY=...
```

Optional email alert delivery:

```bash
SENTINEL_EMAIL_HOST=smtp.example.com
SENTINEL_EMAIL_PORT=587
SENTINEL_EMAIL_FROM=sentinel@example.com
SENTINEL_EMAIL_USERNAME=sentinel@example.com
SENTINEL_EMAIL_PASSWORD=...
SENTINEL_EMAIL_TLS=1
```

Optional Telegram alert delivery:

```bash
SENTINEL_TELEGRAM_BOT_TOKEN=...
```

Portfolio-level recipients and Telegram chat id are configured inside the app
under Settings & Activity.

### Operations

```bash
sudo systemctl restart sentinel
sudo journalctl -u sentinel -f
sudo systemctl stop sentinel
```

Back up the SQLite database:

```bash
sudo systemctl stop sentinel
sudo cp /var/lib/sentinel/sentinel.sqlite3 "/var/lib/sentinel/sentinel-$(date +%F).sqlite3"
sudo systemctl start sentinel
```

## 3. Cloudflare Tunnel

Use Cloudflare Tunnel only after the Pi service is healthy locally.

### Install Cloudflared

Follow Cloudflare's Raspberry Pi package instructions, then authenticate:

```bash
cloudflared tunnel login
cloudflared tunnel create sentinel
```

Copy the generated credentials JSON to:

```bash
/etc/cloudflared/sentinel.json
```

Copy and edit the example config:

```bash
sudo mkdir -p /etc/cloudflared
sudo cp /opt/sentinel/deploy/cloudflare/config.example.yml /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml
```

Change:

```yaml
hostname: sentinel.example.com
```

to your Cloudflare hostname.

Create the DNS route:

```bash
cloudflared tunnel route dns sentinel sentinel.example.com
```

Install the tunnel service:

```bash
sudo cp /opt/sentinel/deploy/cloudflare/cloudflared.service /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
sudo systemctl status cloudflared
```

### Security Requirement

Do not expose Sentinel publicly without an access control decision. Recommended:

- Enable Cloudflare Access for the hostname.
- Restrict access to your email/account.
- Keep the app bound to `127.0.0.1:8765` on the Pi.
- Do not place Massive, email, or Telegram credentials in the repository.

### Smoke Test

```bash
curl https://sentinel.example.com/health
```

Expected:

```json
{
  "ok": true
}
```

## Remaining Deployment Decisions

- GitHub repository name and visibility.
- Raspberry Pi hostname and final install path if not `/opt/sentinel`.
- Production hostname, for example `sentinel.yourdomain.com`.
- Cloudflare Access policy: who can log in.
- Email SMTP provider and sender address.
- Telegram bot token and target chat id.
