# Sentinel Operational Runbook

Last updated: 2026-06-23

## Current Source State

- Branch: `main`
- HEAD commit: `63f8bcf2eac5a27c6d61b6907105758e569a5916` (update to current after each deployment)
- Test suite: 179 tests passed, 1 skipped (as of 2026-06-23; count grows with new features)

## Running Locally

```powershell
# Windows — from repo root
python -m venv .venv
.venv\Scripts\activate
# no pip installs needed — stdlib only

$env:PYTHONPATH = "backend;."
python -m unittest discover -s tests          # full test suite
python scripts/validate_upload_package.py     # upload/secret scan
python scripts/run_dev_server.py              # dev server at http://127.0.0.1:8765
```

```bash
# Unix/Pi — from repo root
python3 -m venv .venv
source .venv/bin/activate

PYTHONPATH=backend:. python3 -m unittest discover -s tests
python3 scripts/validate_upload_package.py
python3 scripts/run_dev_server.py
```

## Pi Deployment

- Install path: `/opt/sentinel`
- Database: `/var/lib/sentinel/sentinel.sqlite3`
- Env file: `/etc/sentinel/sentinel.env`
- Service user: `sentinel`

```bash
# Install / update
sudo systemctl stop sentinel
sudo tar -xzf /tmp/sentinel-current.tar.gz -C /opt/sentinel
sudo bash /opt/sentinel/deploy/raspberry-pi/install.sh
sudo systemctl start sentinel
```

```bash
# Check health
curl -i http://127.0.0.1:8765/health
# Expected: HTTP/1.0 200 OK  {"ok": true}
```

```bash
# Service commands
sudo systemctl status sentinel
sudo systemctl restart sentinel
sudo journalctl -u sentinel -f
sudo journalctl -u sentinel -n 120 --no-pager
```

## Cloudflare Tunnel

- Tunnel name: `pi-ai`
- Tunnel ID: `8425f5a7-41f8-4c3a-96bd-9adaa35f7010`
- Public hostname: `sentinel1.ahaddashboards.uk`
- Local service: `http://127.0.0.1:8765`
- Configuration: dashboard-managed via Cloudflare Zero Trust → Networks → Tunnels → `pi-ai`

```bash
# Verify tunnel is live
curl -i https://sentinel1.ahaddashboards.uk/health
# Expected: HTTP 200  {"ok": true}

# Restart cloudflared after config change
sudo systemctl restart cloudflared
sleep 8
sudo systemctl status cloudflared --no-pager -l
```

⚠ **Cloudflare Access must be enabled for `sentinel1.ahaddashboards.uk` before sharing the URL publicly.** See [DEPLOYMENT.md](DEPLOYMENT.md) Security Gate section.

## Backup and Restore

```bash
# Backup
sudo /opt/sentinel/deploy/raspberry-pi/backup_database.sh
# Backups written to /var/backups/sentinel/

# Restore
sudo /opt/sentinel/deploy/raspberry-pi/restore_database.sh \
  /var/backups/sentinel/sentinel-YYYYMMDD-HHMMSS.sqlite3
```

## End-to-End Monitor Cycle

1. Open `https://sentinel1.ahaddashboards.uk/` in a browser.
2. Select your portfolio (or create one and import a CSV).
3. Click **Import & Run** → enter Massive API key → click **Save Portfolio And Run Monitor**.
4. Wait for the run to complete (progress shown inline).
5. Open **Holdings** to see ranked tickers.
6. Open a ticker to see its Bottom Line, chart, and alert queue.
7. Acknowledge any triggered exit alerts with a note.
8. Check **Settings & Activity** for run history and notification status.

## Known Limitations

- **Browser UX test skipped locally**: Chrome is not installed. Set `CHROME_BIN` to the Chrome executable path to enable the CDP browser test in `tests/test_browser_sidebar_ux.py`.
- **Python 3.14 deprecation warnings**: `datetime.utcnow()` emits warnings under Python 3.14. The Pi runs Python 3.13.5 so this is not an immediate risk.
- **Backfill is synchronous** (as of 2026-06-23; async job queue is planned).

## Open Product Decisions

- Single-user Pi-only beta vs. multi-user with app-level auth?
- Replace-mode inactive tickers: delete historical subscription records or keep for audit?
- Unattended daily Pi schedule vs. manual user-triggered monitor runs?
- ATR-based profit-lock buffer (currently fixed 1%).
