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
- Bind address: `HOST=127.0.0.1`.

Do not expose port 8765 directly on the LAN. Cloudflare Tunnel should connect
to the local service at `127.0.0.1:8765`; Cloudflare Access is the external
access control layer.

### Install

On the Pi:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip sqlite3
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
HOST=127.0.0.1
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
sudo /opt/sentinel/deploy/raspberry-pi/backup_database.sh
```

Restore from a known-good backup:

```bash
sudo /opt/sentinel/deploy/raspberry-pi/restore_database.sh /var/backups/sentinel/sentinel-YYYYMMDD-HHMMSS.sqlite3
```

## ⚠ Security Gate — Required Before Public Exposure

Sentinel has no app-level authentication. All API endpoints that create portfolios, import data, evaluate alerts, save setup values, configure notifications, and acknowledge alerts are **unprotected at the application layer**.

**This is safe only if Cloudflare Access is correctly configured for the public hostname.**

Without Cloudflare Access, anyone who knows the URL can read and modify your portfolio data.

### Enabling Cloudflare Access

1. Open [Cloudflare Zero Trust](https://one.dash.cloudflare.com/).
2. Go to **Access → Applications → Add an application**.
3. Choose **Self-hosted**.
4. Set the application domain to `sentinel1.ahaddashboards.uk` (or your hostname).
5. Under **Policies**, add an **Allow** policy restricted to your email address.
6. Save. Cloudflare Access will now challenge any browser visit with a login page.

### Verifying Access Is Active

Open `https://sentinel1.ahaddashboards.uk/` in a **private browser window** (to bypass cached auth). You should see a Cloudflare Access login prompt — not the Sentinel dashboard directly.

If you see the dashboard without a login prompt, Access is not active. Do not share the URL until this is confirmed.

## 3. Cloudflare Tunnel

Use Cloudflare Tunnel only after the Pi service is healthy locally.

The production Pi currently uses an existing Cloudflare-managed tunnel rather
than a Sentinel-created tunnel:

- Tunnel name: `pi-ai`
- Tunnel ID: `8425f5a7-41f8-4c3a-96bd-9adaa35f7010`
- Public hostname: `sentinel1.ahaddashboards.uk`
- Local Sentinel service: `http://127.0.0.1:8765`

Important: this tunnel receives a remote configuration from the Cloudflare Zero
Trust dashboard. When cloudflared logs `Updated to new configuration`, that
remote dashboard configuration is authoritative. Editing
`/etc/cloudflared/config.yml` alone will not publish a new hostname for this
tunnel.

### Existing Dashboard-Managed Tunnel

Use this path for the current Pi.

1. Open Cloudflare Zero Trust.
2. Go to `Networks -> Tunnels`.
3. Open the existing `pi-ai` tunnel.
4. Add or edit a public hostname:
   - Subdomain: `sentinel1`
   - Domain: `ahaddashboards.uk`
   - Service type: `HTTP`
   - Service URL: `127.0.0.1:8765`
5. Save the hostname.
6. Restart cloudflared on the Pi:

```bash
sudo systemctl restart cloudflared
sleep 8
sudo systemctl status cloudflared --no-pager -l
```

Smoke test:

```bash
curl -i https://sentinel1.ahaddashboards.uk/health
curl -i https://sentinel1.ahaddashboards.uk/ | head -n 20
```

Expected:

- `/health` returns HTTP 200 and `{"ok": true}`.
- `/` returns HTTP 200 and the Sentinel HTML.

`curl -I` sends a HEAD request. Sentinel supports HEAD for health and static
routes, so it should return headers without a body after the HEAD-support build
is deployed.

If the public hostname returns 404 but local Sentinel works, inspect the
cloudflared logs:

```bash
sudo journalctl -u cloudflared -n 120 --no-pager
```

If the logs show a remote config that does not include
`sentinel1.ahaddashboards.uk`, update the hostname in the Cloudflare dashboard.

### New Locally Managed Tunnel

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

These items are resolved for the current production Pi deployment:

- **GitHub repository**: `https://github.com/meiriohad76-oss/felix-alerts` (public).
- **Pi install path**: `/opt/sentinel` (confirmed).
- **Production hostname**: `sentinel1.ahaddashboards.uk` (Cloudflare tunnel `pi-ai`).
- **Cloudflare Access**: must be configured before sharing the public URL — see Security Gate section above.
- **Email SMTP**: not yet configured. Set `SENTINEL_EMAIL_HOST`, `SENTINEL_EMAIL_PORT`, `SENTINEL_EMAIL_FROM`, `SENTINEL_EMAIL_USERNAME`, `SENTINEL_EMAIL_PASSWORD` in `/etc/sentinel/sentinel.env`.
- **Telegram**: not yet configured. Set `SENTINEL_TELEGRAM_BOT_TOKEN` in `/etc/sentinel/sentinel.env`; configure chat id in app Settings.
