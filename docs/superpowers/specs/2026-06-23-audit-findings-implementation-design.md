# Sentinel Audit Findings Implementation Design

Date: 2026-06-23

Status: Approved for implementation.

Source audit: `docs/AUDIT_FINDINGS_2026-06-23.md`

Scope: All 7 findings — 3 high, 3 medium, 1 low.

---

## Decisions Made During Brainstorm

| Finding | Decision |
|---------|----------|
| Replace-mode subscriptions | Delete subscriptions for inactive tickers (not disable/archive) |
| Scorecard wiring | Both: call during evaluate + new maintenance endpoint |
| Auth/security | Cloudflare Access documented as hard gate; no app-level auth this cycle |
| Async backfill | SQLite `monitor_jobs` table with HTTP job-id + polling |
| Modularization | Split `http_api.py` only; `sqlite_store.py` and frontend deferred |

---

## Section 1: Data Integrity

### Finding 1 — Replace-mode subscription cleanup

**Problem:** Replace-mode import marks missing tickers `inactive` but leaves their subscriptions intact. Portfolio subscription counts include inactive ticker monitoring.

**Fix:**

- Add `delete_subscriptions_for_inactive_tickers(portfolio_id)` store method in `sqlite_store.py`. Deletes all subscription rows for tickers in the portfolio where `status = 'inactive'`.
- `persistent_service.py` replace-mode import path calls this method immediately after the import report is written and inactive tickers are set.
- `subscriptions.py` `create_subscriptions()` adds a guard asserting all incoming tickers are active, catching future regressions at the call site.

**Tests:**
- `tests/test_sqlite_persistence.py`: import AAPL + MSFT as investor → replace-import AAPL only → assert MSFT has 0 subscriptions, AAPL subscriptions unchanged.
- Verify portfolio subscription count equals active ticker count × subscription rules per ticker.

**Files touched:** `sqlite_store.py`, `persistent_service.py`, `subscriptions.py`, `tests/test_sqlite_persistence.py`

---

### Finding 2 — Scorecard stale exit wiring

**Problem:** `stale_exit_events()` in `scorecard.py` correctly identifies deferred (48h) and missed (7d) open exit alerts, but the persistent evaluate path never calls it. Discipline scorecard can understate methodology violations.

**Fix:**

**During evaluate:**
- `persistent_service.py` evaluate path calls `stale_exit_events()` scoped to the current portfolio's tickers after alert create/refresh/resolve completes.
- Results written via `write_scorecard_event(alert_id, event_kind, ...)` — idempotent, keyed on `(alert_id, event_kind)` to prevent duplicate events on re-runs.

**Maintenance endpoint:**
- New `POST /portfolios/{id}/maintenance/scorecard` endpoint in `http_api.py`.
- Sweeps all active tickers in the portfolio for stale exits regardless of when evaluate last ran.
- Returns `{ "deferred_written": N, "missed_written": N }`.
- Designed to be called by a Pi cron job (e.g., daily at market close).

**Tests:**
- `tests/test_sqlite_persistence.py`: create open exit alert, pass `now=alert_created_at + 49h` to `stale_exit_events()` → assert deferred event written. `stale_exit_events()` must accept an injectable `now` parameter (defaults to `datetime.utcnow()`) so tests are deterministic without real time passing.
- `tests/test_sqlite_persistence.py`: pass `now=alert_created_at + 8d` → assert missed event written.
- `tests/test_http_api.py`: call maintenance endpoint → returns counts, idempotent on second call.

**Files touched:** `persistent_service.py`, `sqlite_store.py`, `http_api.py`, `tests/test_sqlite_persistence.py`, `tests/test_http_api.py`

---

## Section 2: API Hardening

### Finding 4 — Invalid UUID → 400 (not 500)

**Problem:** Inline `UUID(value)` calls in the route dispatcher raise `ValueError` on bad input, which the HTTP wrapper maps to a generic 500 response. All other validation paths already return structured 400 responses.

**Fix:**

- Add `_parse_uuid(value, field_name) -> UUID` private helper in `http_api.py`.
- On `ValueError`, raises `ApiError(HTTPStatus.BAD_REQUEST, f"Invalid {field_name}: must be a valid UUID")`.
- Replace all inline `UUID(...)` calls in the dispatcher with this helper: portfolio id, alert id, user id, and any ticker route UUID params.

**Tests:**
- `tests/test_http_api.py`: request with malformed portfolio id → 400 with stable error message.
- Request with malformed alert id → 400.
- Request with malformed user id → 400.
- Valid UUIDs continue to work correctly.

**Files touched:** `http_api.py`, `tests/test_http_api.py`

---

### Finding 6 — Async backfill via SQLite job queue

**Problem:** Backfill and evaluate block the HTTP request for the full run duration. Large portfolios, slow networks, or Pi resource constraints can cause browser/Cloudflare timeouts mid-run.

**Fix:**

**Schema — `monitor_jobs` table:**
```
job_id          TEXT PRIMARY KEY
portfolio_id    TEXT NOT NULL
kind            TEXT NOT NULL   -- 'backfill' | 'evaluate' | 'full_run'
status          TEXT NOT NULL   -- 'queued' | 'running' | 'done' | 'failed'
created_at      TEXT NOT NULL
started_at      TEXT
completed_at    TEXT
tickers_total   INTEGER
tickers_done    INTEGER
tickers_failed  INTEGER
error           TEXT
```

**API changes:**
- `POST /portfolios/{id}/backfill` enqueues a job and returns `{ "job_id": "...", "status": "queued" }` immediately.
- `POST /portfolios/{id}/evaluate` enqueues a job and returns the same shape.
- New `GET /jobs/{job_id}` returns current job row as JSON.

**Worker:**
- Single daemon thread started at server startup (`threading.Thread(daemon=True)`).
- Polls `monitor_jobs` for `status = 'queued'` rows, processes one at a time.
- Updates job row with `running` → `done`/`failed` and progress counts as it goes.
- SQLite WAL mode ensures safe concurrent reads during writes.

**Frontend:**
- After starting a run, poll `GET /jobs/{job_id}` every 2 seconds until status is `done` or `failed`.
- On completion, refresh portfolio detail as today.
- Show inline progress: "Running… N/M tickers done".

**Tests:**
- `tests/test_sqlite_persistence.py`: enqueue job → assert row exists with `queued` status.
- `tests/test_http_api.py`: POST backfill → returns job_id → GET /jobs/{id} returns status.
- Partial failure: some tickers fail → job status is `done`, `tickers_failed > 0`, error field populated.

**Files touched:** `sqlite_store.py`, `persistent_service.py`, `http_api.py`, `api_jobs.py` (new), `frontend/sidebar.html`, `tests/test_sqlite_persistence.py`, `tests/test_http_api.py`

---

## Section 3: Docs & Security

### Finding 3 — Cloudflare Access as hard deployment gate

**Problem:** Cloudflare Access is the only thing standing between the public internet and unprotected state-changing API endpoints. This is not documented as a hard prerequisite.

**Fix:**

- New **"⚠ Security Gate"** section in `docs/DEPLOYMENT.md`, placed immediately before the Cloudflare Tunnel instructions. Clearly states:
  - Without Cloudflare Access, all endpoints (portfolio create, import, evaluate, setup save, notifications) are publicly writable.
  - Steps to enable Cloudflare Access for the hostname.
  - How to verify Access is active (attempt to visit hostname in a private browser → expect login prompt).
- `scripts/validate_upload_package.py` gains a check that `docs/DEPLOYMENT.md` contains the string `Security Gate` — fails with a warning if it has been removed.

**Files touched:** `docs/DEPLOYMENT.md`, `scripts/validate_upload_package.py`

---

### Finding 5 — Docs drift / new Runbook

**Problem:** `HANDOFF_2026-05-21.md` states stale commit hashes and test counts. No single current operational reference exists.

**Fix:**

- `docs/HANDOFF_2026-05-21.md`: prepend `> **Historical handoff** — current operational state is in [RUNBOOK.md](RUNBOOK.md).` No other content changes.
- New `docs/RUNBOOK.md` — single operational reference:
  - Current source state: commit, branch, test count
  - Running locally: venv setup, test command, dev server command
  - Pi deployment: install path, service commands, health check URL
  - Cloudflare tunnel: hostname, how to verify
  - Backup/restore: commands with example output
  - End-to-end monitor cycle: step-by-step from import to alert review
  - Known limitations: browser test needs Chrome, Python 3.14 deprecation warnings
  - Open product decisions
- `docs/DEPLOYMENT.md` remaining "TBD" items for hostname and Pi path are resolved to their known values (`sentinel1.ahaddashboards.uk`, `/opt/sentinel`).

**Files touched:** `docs/RUNBOOK.md` (new), `docs/HANDOFF_2026-05-21.md`, `docs/DEPLOYMENT.md`

---

## Section 4: Modularization

### Finding 7 — Split `http_api.py` by route domain

**Problem:** `http_api.py` is 1,422 lines handling all routes, validation, static serving, and middleware. Changes to any route risk unintended side effects in others.

**Fix:**

Split into focused handler modules, all in `backend/sentinel_core/`:

| File | Responsibility |
|------|---------------|
| `api_portfolios.py` | Portfolio CRUD, import, CSV/XLSX upload, setup-data, maintenance/scorecard |
| `api_market_data.py` | Backfill endpoint (enqueues job) |
| `api_alerts.py` | Alert list, acknowledge, suppress |
| `api_notifications.py` | Notification settings, delivery status |
| `api_jobs.py` | `GET /jobs/{id}` polling |
| `http_api.py` (shrunk) | Request dispatcher, `_parse_uuid`, shared `ApiError`/response helpers, static file serving — delegates to sub-modules after route matching |

**Interface contract:**

Each sub-module exposes:
```python
def handle(path, method, params, body, service) -> (status, headers, body)
```

The main dispatcher matches the route prefix and delegates. No behavior changes — purely structural.

**Verification:** All existing `test_http_api.py` tests pass unchanged after the split, since they test the public HTTP surface, not internal file structure.

**Files touched:** `http_api.py` (refactored), `api_portfolios.py` (new), `api_market_data.py` (new), `api_alerts.py` (new), `api_notifications.py` (new), `api_jobs.py` (new)

---

## Implementation Order

Follow the audit's recommended priority sequence:

1. **Finding 1** — Replace-mode subscription cleanup (data integrity regression)
2. **Finding 2** — Scorecard stale exit wiring (silent behavioral gap)
3. **Finding 5** — Docs update + RUNBOOK.md (low-risk, unblocks operational clarity)
4. **Finding 3** — Cloudflare Access security gate in DEPLOYMENT.md
5. **Finding 4** — UUID → 400 API hardening
6. **Finding 6** — Async backfill job queue
7. **Finding 7** — `http_api.py` modular split (last, after all behavioral changes are in)

---

## Test Strategy

- Every behavioral finding has a failing test written first, then the fix.
- Structural finding (7) has no behavior change — existing tests serve as the regression suite.
- Full suite (`175 tests + new`) must pass after each finding is implemented before moving to the next.
- `scripts/validate_upload_package.py` passes throughout.

---

## Out of Scope This Cycle

- `sqlite_store.py` split (deferred)
- Frontend JS modularization (deferred)
- App-level session auth (Cloudflare Access is sufficient for single-user beta)
- Python 3.14 `datetime.utcnow()` deprecation cleanup (non-blocking, separate pass)
- Browser/Chrome test setup (separate ops task)
