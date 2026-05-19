# Sentinel V2 Audit And Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the V2 reliability foundation: import safety, setup lifecycle clarity, durable audit/run direction, and tests that catch the known UX/data regressions.

**Architecture:** Keep the current backend and sidebar frontend running while moving product-critical decisions into tested backend contracts. Frontend changes are targeted at workflow clarity and regression prevention; larger frontend modularization is a later V2 phase.

**Tech Stack:** Python standard library HTTP API, SQLite, Python `unittest`, vanilla HTML/CSS/JS in `frontend/sidebar.html`.

---

## File Structure

- Modify: `backend/sentinel_core/csv_import.py`
  - Preserve existing setup fields during merge/replace imports.
  - Reject non-positive numeric values.

- Modify: `tests/test_csv_import.py`
  - Add import preservation and numeric validation regression tests.

- Modify: `frontend/sidebar.html`
  - Fix saved-portfolio next action logic.
  - Fix chart marker suppression by rule id.
  - Keep missing stop/profit-lock entry visible where needed.

- Modify: `tests/test_frontend_sidebar_static.py`
  - Add guards for next-action branching and chart trigger marker dedupe behavior.

- Future create: backend run/audit schema files or migrations inside `backend/sentinel_core/sqlite_store.py`
  - Add durable run and alert event tables.

- Future modify: `backend/sentinel_core/persistent_service.py`
  - Add setup-data lifecycle resolution and server-owned monitor runs.

## Ticket V2-001: Log Audit Findings And Plan

Goal: create durable audit artifacts so findings, definitions of done, and implementation tickets are not lost.

Files:

- Create: `docs/V2_AUDIT_FINDINGS_2026-05-19.md`
- Create: `docs/superpowers/specs/2026-05-19-v2-audit-and-product-plan-design.md`
- Create: `docs/superpowers/plans/2026-05-19-v2-audit-and-testing-plan.md`

Definition of Done:

- Findings include severity, user impact, required fix, definition of done, and success criteria.
- Plan includes deployable tickets and testing expectations.

Success Criteria:

- Future work can be planned from the docs without relying on chat history.

Test:

- Manual file review.

## Ticket V2-002: Preserve Existing Setup Data During Imports

Goal: re-importing broker files must not erase stops, entries, shares, type, or notes that Sentinel already stores for an existing ticker.

Files:

- Modify: `tests/test_csv_import.py`
- Modify: `backend/sentinel_core/csv_import.py`

Definition of Done:

- Existing ticker re-import with only `ticker` preserves `type`, `shares`, `entry_price`, `entry_date`, `current_profit_lock`, `user_exit_price`, and `notes`.
- Existing ticker re-import with blank setup columns preserves existing setup values.
- Existing ticker re-import with explicit positive values updates those values.
- New ticker behavior is unchanged: blank setup fields remain blank.

Success Criteria:

- `PYTHONPATH=backend:. python3 -m unittest tests.test_csv_import` passes.
- Full test suite passes.

Implementation Steps:

- [x] Add failing test for ticker-only re-import preservation.
- [x] Add failing test for blank setup column preservation.
- [x] Add passing update test for explicit positive replacement.
- [x] Implement merge helper that preserves existing values when raw input is blank or absent.
- [x] Run targeted and full tests.

## Ticket V2-003: Reject Non-Positive Import Numbers

Goal: prevent invalid portfolio data from reaching alert evaluation.

Files:

- Modify: `tests/test_csv_import.py`
- Modify: `backend/sentinel_core/csv_import.py`

Definition of Done:

- `shares`, `entry_price`, and `current_profit_lock` reject zero and negative values when supplied.
- Row issues use stable codes: `invalid_shares`, `invalid_entry_price`, `invalid_current_profit_lock`.
- Invalid rows do not create or update tickers.

Success Criteria:

- Targeted CSV tests pass.
- Full suite passes.

Implementation Steps:

- [x] Add failing tests for zero and negative values.
- [x] Add domain validation after decimal parsing.
- [x] Add non-finite numeric validation for CSV and setup-data API.
- [x] Run targeted and full tests.

## Ticket V2-004: Fix Saved Portfolio Next Action

Goal: selecting a saved portfolio with tickers should never lead with "Load a portfolio file" just because the editor is empty.

Files:

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

Definition of Done:

- `renderNextAction()` considers saved portfolio detail before editor rows.
- Empty selected portfolio still prompts import/load.
- Saved portfolio with bars and alerts points to Review Alerts.
- Saved portfolio without bars points to Backfill Massive Data.

Success Criteria:

- Static test guards the branch order.
- Manual browser review confirms the global next action after selecting a saved portfolio.

Implementation Steps:

- [x] Add static regression guard for saved portfolio branch.
- [x] Reorder `renderNextAction()` logic.
- [x] Run frontend static tests and full suite.

## Ticket V2-005: Keep Current Watch Markers Visible On Chart

Goal: a historical alert must not hide a current watched/near-trigger chart marker for the same rule.

Files:

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

Definition of Done:

- Potential trigger markers are not filtered solely by `rule_id`.
- Exact duplicates can still be collapsed.
- Clean and detailed chart modes can both show current watch markers.

Success Criteria:

- Static test rejects `!alertRules.has(trigger.rule_id)` filtering.
- Browser review of a stock detail chart shows current alert/watch markers.

Implementation Steps:

- [x] Add static test for marker suppression logic.
- [x] Replace rule-only filter with duplicate-key logic.
- [x] Run frontend static tests and full suite.

## Ticket V2-006: Setup-Data Save Resolves Missing-Protection State

Goal: saving a stop/profit-lock level should immediately clear the missing protection action in the returned response.

Files:

- Modify: `tests/test_http_api.py`
- Modify: `backend/sentinel_core/persistent_service.py`
- Modify: `backend/sentinel_core/http_api.py`
- Modify: `backend/sentinel_core/sqlite_store.py` if explicit resolution helper is needed.

Definition of Done:

- Existing open T1/A1 setup alerts for the ticker are resolved or refreshed immediately after setup-data save.
- API response includes updated portfolio detail with no open missing-stop action for that ticker.
- Frontend no longer needs to compensate with local refresh timing.

Success Criteria:

- API test creates missing-stop alert, saves stop, and asserts missing-stop alert is no longer open.

Implementation Steps:

- [x] Add failing HTTP test for setup save lifecycle.
- [x] Implement backend lifecycle resolution or impacted ticker re-evaluation.
- [x] Update frontend setup save flow to use backend lifecycle response without a second evaluate request.
- [x] Run targeted HTTP tests and full suite.

## Ticket V2-011: Honor Routed Portfolio On Every Display

Goal: multi-portfolio URLs should activate the portfolio named in the URL before falling back to the remembered portfolio.

Files:

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

Definition of Done:

- `?view=holdings&portfolio=<id>` loads `<id>`, not the remembered portfolio.
- `?view=alerts&portfolio=<id>`, `?view=overview&portfolio=<id>`, and `?view=settings&portfolio=<id>` follow the same rule.
- Stock routes preserve both portfolio and ticker.

Success Criteria:

- Static regression test guards that `state.routePortfolioId` is considered before `loadActivePortfolioId()`.

Implementation Steps:

- [x] Add static test for route branch order.
- [x] Update `initializeApp()` to honor routed portfolio for all displays.
- [x] Run frontend static tests and full suite.

## Ticket V2-007: Durable Monitor Run Receipts

Goal: move monitor run status from browser-local memory into SQLite and backend responses.

Files:

- Modify: `backend/sentinel_core/sqlite_store.py`
- Modify: `backend/sentinel_core/persistent_service.py`
- Modify: `backend/sentinel_core/http_api.py`
- Modify: `tests/test_sqlite_persistence.py`
- Modify: `tests/test_http_api.py`
- Later modify: `frontend/sidebar.html`

Definition of Done:

- SQLite stores monitor run rows and per-ticker run item rows.
- Backend can return latest run receipt for a portfolio.
- Receipt includes status, started/completed timestamps, provider, ticker counts, bar success/failure counts, alert counts, and error messages.

Success Criteria:

- Refreshing the browser keeps latest run receipt visible.
- Massive timeout and partial data load are visible in the receipt.

Implementation Steps:

- [x] Add persistence tests for run receipt tables.
- [x] Add API test for latest run receipt.
- [x] Implement store methods and API response.
- [x] Wire frontend read-only display after backend tests pass.

## Ticket V2-008: Alert Event Log

Goal: capture the lifecycle of alerts so the product can explain what happened and what changed.

Files:

- Modify: `backend/sentinel_core/sqlite_store.py`
- Modify: `backend/sentinel_core/persistent_service.py`
- Modify: `tests/test_sqlite_persistence.py`
- Modify: `tests/test_alerts_service.py`

Definition of Done:

- Alert create, refresh, resolve, acknowledge, suppress, and notification attempt events are persisted.
- Events include event id, alert id, ticker, rule id, portfolio id, kind, timestamp, source, and payload.
- Stock detail can query events by ticker.

Success Criteria:

- A stock detail page can show a factual timeline from durable events.

Implementation Steps:

- [x] Add store tests for writing/querying events.
- [x] Add service tests for create/resolve/ack event writes.
- [x] Implement schema and service calls.

## Ticket V2-009: Backend-Owned Holdings Scores

Goal: remove core urgency/sell/bearish score invention from the frontend.

Files:

- Create or modify: `backend/sentinel_core/scorecard.py`
- Modify: `backend/sentinel_core/serialization.py`
- Modify: `tests/test_scorecard.py`
- Later modify: `frontend/sidebar.html`

Definition of Done:

- Backend returns row scores with value, label, reason, and component breakdown.
- Holdings sort uses backend rank.
- Frontend renders scores without recomputing action priority.

Success Criteria:

- Mixed portfolio test produces differentiated ranks and reasons.
- Equal scores include identical component reasons.

Implementation Steps:

- [x] Add backend score/API tests for differentiated setup issue and triggered sell rows.
- [x] Implement score payload.
- [x] Expose score payload in portfolio detail serialization.
- [x] Replace frontend score logic after backend payload exists, with fallback retained for older payloads.

## Ticket V2-010: Browser-Level Critical Flow Tests

Goal: prevent UX regressions that static string tests cannot catch.

Files:

- Create: `tests/browser/` or equivalent local browser test harness after tool decision.
- Modify: `README.md` with the chosen command.

Definition of Done:

- Automated test opens local app, selects/loads portfolio, routes to stock detail, verifies chart SVG exists, verifies setup panel visibility, and verifies next action text.
- Test can run locally without real Massive by using stored or mocked API responses.

Success Criteria:

- Hiding missing stop setup, breaking chart rendering, or losing stock detail routing fails the browser test.

Implementation Steps:

- [x] Pick browser test tool for this repo: Node + Chrome DevTools Protocol, no Playwright/Selenium dependency.
- [x] Add smoke test for routed portfolio, stock detail route, and chart SVG rendering.
- [x] Add measured UX checks for tooltip readability, chart marker overlap, marker lanes, and marker hover tooltip sizing.
- [x] Add README command.

## Ticket V2-012: External Triggered-Alert Notifications

Goal: push newly triggered actionable alerts to email and Telegram while keeping Sentinel's in-app log, alert event log, and user-facing explanations consistent.

Files:

- Modify: `backend/sentinel_core/notifications.py`
- Modify: `backend/sentinel_core/persistent_service.py`
- Modify: `backend/sentinel_core/sqlite_store.py`
- Modify: `backend/sentinel_core/http_api.py`
- Modify: `frontend/sidebar.html`
- Modify: `tests/test_notifications.py`
- Modify: `tests/test_sqlite_persistence.py`
- Modify: `tests/test_http_api.py`
- Create or modify: deployment/env documentation for email SMTP/API and Telegram bot credentials.

Definition of Done:

- Users can configure notification channels per portfolio: in-app only, email, Telegram, or both external channels.
- Email delivery sends the existing server-generated alert explanation, rule rationale, evidence summary, recommended action, and required disclaimer.
- Telegram delivery sends a concise alert summary with ticker, rule, severity, what triggered, and recommended action, plus a link or instruction to open the stock detail page.
- External notifications are sent only for new actionable triggered alerts, not for passive watches, historical resolved alerts, or setup items after they are resolved.
- Delivery attempts are durable: queued, sent, failed, retry count, provider response/error, and timestamp are stored.
- Alert event log records `notification_queued`, `notification_sent`, and `notification_failed` with channel and provider payload metadata.
- Secrets are never stored in frontend code or committed files. Email credentials and Telegram bot token are loaded from environment or a local ignored config file.
- UI clearly shows notification channel status, last delivery result, and actionable setup instructions when credentials or chat id are missing.
- No email or Telegram message implies automatic trading or broker order placement.

Success Criteria:

- A test alert creates separate durable notification records for `email` and `telegram` when both channels are enabled.
- Mock email provider receives the full alert explanation and disclaimer.
- Mock Telegram provider receives a concise, readable message under Telegram message length limits.
- Failed provider delivery does not fail the monitor run; it records a failed notification event and visible status.
- Duplicate monitor runs do not resend the same deduped alert unless a new alert lifecycle event is created.
- Full test suite and browser smoke tests pass with external providers mocked.

Implementation Steps:

- [x] Define notification settings model: portfolio channel preferences, email recipients, Telegram chat id, and enabled flags.
- [x] Add SQLite persistence for notification settings and delivery attempt metadata or extend `notification_log` safely.
- [x] Add provider interfaces: `EmailProvider` and `TelegramProvider`, with deterministic mock providers for tests.
- [x] Implement email delivery using the existing `render_alert_email()` output.
- [x] Implement Telegram message rendering with concise plain-English alert summaries.
- [x] Queue/send external notifications from the alert creation path without blocking rule evaluation on provider failures.
- [x] Persist delivery events into the alert event log.
- [x] Add settings UI for channel enablement, recipient/chat-id entry, and credential status.
- [x] Add backend API routes for notification settings.
- [x] Add tests for queued/sent/failed email and Telegram delivery, missing provider credential status, and UI status copy.

## Ticket OPS-001: Prepare Manual GitHub Upload Package

Goal: prepare the project so the user can manually upload it to GitHub without accidentally publishing secrets, local databases, generated caches, or temporary files.

Owner: user performs the final GitHub upload manually; implementation work prepares and verifies the package.

Files:

- Create or modify: `.gitignore`
- Create or modify: `README.md`
- Create or modify: `docs/DEPLOYMENT.md`
- Review: local workspace root

Definition of Done:

- `.gitignore` excludes local databases, logs, PID files, environment files, caches, generated test output, and OS/editor metadata.
- `README.md` explains local setup, test command, server command, and required environment variables.
- `docs/DEPLOYMENT.md` links to Raspberry Pi and Cloudflare Tunnel instructions once those tickets are implemented.
- No Massive API key or other secret appears in tracked/source files.
- The user has a short manual checklist for creating the GitHub repository and uploading the files.

Success Criteria:

- Running a secret/residue scan finds no API keys, demo portfolios, local SQLite files, logs, or temporary assets in the upload set.
- A fresh clone can run `PYTHONPATH=backend:. python3 -m unittest discover -s tests`.

Implementation Steps:

- [x] Add/update `.gitignore`.
- [x] Add GitHub manual upload checklist to `README.md` and `docs/DEPLOYMENT.md`.
- [x] Add upload package validator script.
- [x] Run residue/secret scan over the workspace.
- [x] Run full tests from the prepared workspace.
- [ ] Provide the user with the final list of files/folders to upload manually.

## Ticket OPS-002: Raspberry Pi Deployment

Goal: deploy Sentinel as a persistent local service on a Raspberry Pi.

Files:

- Create: `docs/DEPLOYMENT.md`
- Create: `deploy/raspberry-pi/sentinel.service`
- Create: `deploy/raspberry-pi/env.example`
- Create: `deploy/raspberry-pi/install.sh` if we decide to automate setup

Definition of Done:

- Raspberry Pi OS setup instructions are documented.
- Python version and system package requirements are documented.
- App directory, virtual environment, database path, log path, and environment file paths are defined.
- `MASSIVE_API_KEY` is loaded from an environment file and is never committed.
- A `systemd` service starts the Sentinel server on boot and restarts on failure.
- Backup/restore steps for `sentinel_dev.sqlite3` or the production SQLite database are documented.

Success Criteria:

- On the Raspberry Pi, `systemctl status sentinel` shows the service running.
- `curl http://127.0.0.1:8765/health` returns `{"ok": true}`.
- The app survives a Pi reboot and still serves the dashboard.
- Full test suite or a documented Pi smoke-test subset passes.

Implementation Steps:

- [x] Decide default Pi runtime path, database path, and service user.
- [x] Create `systemd` unit file.
- [x] Create environment file template.
- [x] Document install and update procedure.
- [x] Document database backup procedure.
- [ ] Test on Raspberry Pi hardware before installing as `systemd`.

## Ticket OPS-003: Cloudflare Domain And Tunnel

Goal: expose the Raspberry Pi Sentinel service through a Cloudflare-managed domain using Cloudflare Tunnel without opening router ports.

Files:

- Modify: `docs/DEPLOYMENT.md`
- Create: `deploy/cloudflare/config.example.yml`
- Create: `deploy/cloudflare/cloudflared.service` if a custom unit is needed

Definition of Done:

- Cloudflare domain/DNS prerequisites are documented.
- Cloudflare Tunnel setup is documented for the Pi.
- Tunnel maps the chosen hostname to `http://127.0.0.1:8765`.
- Access policy/security requirements are documented before exposing the app outside the local network.
- Tunnel credentials are stored outside the repository.
- Rollback/disable instructions are documented.

Success Criteria:

- Visiting the Cloudflare hostname loads Sentinel.
- `/health` works through the tunnel.
- The Cloudflare tunnel reconnects after Pi reboot.
- The app is not publicly open without an explicit access/security decision.

Implementation Steps:

- [ ] Choose hostname/subdomain.
- [ ] Install and authenticate `cloudflared` on the Pi.
- [ ] Create tunnel and DNS route.
- [x] Configure ingress template to local Sentinel server.
- [ ] Add Cloudflare Access or equivalent protection decision.
- [ ] Test external access and reboot persistence.
