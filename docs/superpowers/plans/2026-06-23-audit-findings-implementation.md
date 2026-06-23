# Sentinel Audit Findings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 7 findings from `docs/AUDIT_FINDINGS_2026-06-23.md` — data integrity, scorecard lifecycle, docs/security, API hardening, async backfill, and modularisation.

**Architecture:** Python stdlib HTTP server + SQLite + vanilla HTML/JS frontend. No new runtime dependencies. Tasks are ordered so each delivers a testable result; Task 7 (modularisation) runs last after all behavioural changes are in.

**Tech Stack:** Python 3.11+, `sqlite3`, `threading`, `unittest`, vanilla JS in `frontend/sidebar.html`. Run tests with `python -m unittest discover -s tests` from repo root with `PYTHONPATH=backend;.` (Windows) or `PYTHONPATH=backend:.` (Unix).

## Global Constraints

- No new third-party packages — stdlib only.
- Full test suite must pass after every task before moving to the next.
- `scripts/validate_upload_package.py` must pass throughout.
- Every behavioural task uses TDD: failing test first, then implementation.
- Commit after each task with a descriptive message ending with `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`.
- Working directory for all commands: repo root `c:\Users\meiri\felix alets`.
- Python command on this machine: `python` (not `python3`).
- Set `PYTHONPATH=backend;.` before running tests on Windows.

---

## File Map

| Task | Files Modified | Files Created |
|------|---------------|---------------|
| 1 | `backend/sentinel_core/persistent_service.py`, `backend/sentinel_core/subscriptions.py`, `tests/test_sqlite_persistence.py` | — |
| 2 | `backend/sentinel_core/sqlite_store.py`, `backend/sentinel_core/persistent_service.py`, `backend/sentinel_core/http_api.py`, `tests/test_sqlite_persistence.py`, `tests/test_http_api.py` | — |
| 3 | `docs/HANDOFF_2026-05-21.md`, `docs/DEPLOYMENT.md` | `docs/RUNBOOK.md` |
| 4 | `docs/DEPLOYMENT.md`, `scripts/validate_upload_package.py` | — |
| 5 | `backend/sentinel_core/http_api.py`, `tests/test_http_api.py` | — |
| 6 | `backend/sentinel_core/sqlite_store.py`, `backend/sentinel_core/persistent_service.py`, `backend/sentinel_core/http_api.py`, `frontend/sidebar.html`, `tests/test_sqlite_persistence.py`, `tests/test_http_api.py` | — |
| 7 | `backend/sentinel_core/http_api.py` | `backend/sentinel_core/api_market_data.py`, `backend/sentinel_core/api_alerts.py`, `backend/sentinel_core/api_notifications.py`, `backend/sentinel_core/api_jobs.py` |

---

## Task 1: Fix Replace-mode Subscription Leak

**Goal:** When a replace-mode import marks tickers inactive, delete their subscriptions so no inactive ticker is monitored.

**Files:**
- Modify: `tests/test_sqlite_persistence.py`
- Modify: `backend/sentinel_core/persistent_service.py`
- Modify: `backend/sentinel_core/subscriptions.py`

**Interfaces:**
- Produces: `persistent_service.import_csv(..., mode="replace")` returns subscriptions only for active tickers.

- [ ] **Step 1.1: Write the failing regression test**

Add to `tests/test_sqlite_persistence.py` (after existing imports, inside a new or existing `SQLiteStoreTests` class):

```python
def test_replace_mode_import_deletes_subscriptions_for_inactive_tickers(self):
    from sentinel_core.persistent_service import PersistentSentinelWorkspace
    from sentinel_core.sqlite_store import SQLiteStore
    from uuid import uuid4

    store = SQLiteStore.in_memory()
    workspace = PersistentSentinelWorkspace(store)
    user_id = uuid4()
    portfolio = workspace.create_portfolio(user_id=user_id, name="Test")
    pid = portfolio.portfolio_id

    # Import AAPL and MSFT in merge mode (default)
    workspace.import_csv(
        user_id=user_id,
        portfolio_id=pid,
        csv_text="ticker\nAAPL\nMSFT\n",
    )
    subs_before = store.list_subscriptions(pid)
    msft_before = [s for s in subs_before if s.ticker == "MSFT"]
    self.assertGreater(len(msft_before), 0, "MSFT should have subscriptions after initial import")

    # Replace-import with AAPL only — MSFT becomes inactive
    workspace.import_csv(
        user_id=user_id,
        portfolio_id=pid,
        csv_text="ticker\nAAPL\n",
        mode="replace",
    )
    subs_after = store.list_subscriptions(pid)
    aapl_after = [s for s in subs_after if s.ticker == "AAPL"]
    msft_after = [s for s in subs_after if s.ticker == "MSFT"]

    self.assertGreater(len(aapl_after), 0, "AAPL subscriptions must be preserved")
    self.assertEqual(len(msft_after), 0, "MSFT subscriptions must be deleted when ticker goes inactive")
```

- [ ] **Step 1.2: Run the test to confirm it fails**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_sqlite_persistence.SQLiteStoreTests.test_replace_mode_import_deletes_subscriptions_for_inactive_tickers -v
```

Expected: `FAIL` — MSFT still has subscriptions after replace-mode import.

- [ ] **Step 1.3: Add active-ticker guard to `subscriptions.py`**

Open `backend/sentinel_core/subscriptions.py`. In `create_subscriptions_for_portfolio`, add a guard at the top of the function, before `existing_list = list(existing)`:

```python
def create_subscriptions_for_portfolio(
    tickers: Iterable[PortfolioTickerView],
    *,
    created_from_import_id: Optional[UUID] = None,
    existing: Iterable[AlertSubscription] = (),
) -> List[AlertSubscription]:
    tickers_list = list(tickers)
    inactive = [t.ticker for t in tickers_list if t.status != "active"]
    if inactive:
        raise ValueError(
            "create_subscriptions_for_portfolio received inactive tickers: %s. "
            "Filter to active tickers before calling." % ", ".join(sorted(inactive))
        )
    existing_list = list(existing)
    # ... rest of function unchanged
```

- [ ] **Step 1.4: Fix `import_csv` in `persistent_service.py`**

Open `backend/sentinel_core/persistent_service.py`. In `import_csv`, change the subscriptions call to pass only active tickers:

Find this block (around line 50):
```python
        self.store.save_tickers(report.tickers)
        subscriptions = create_subscriptions_for_portfolio(
            report.tickers,
            created_from_import_id=report.import_id,
            existing=self.store.list_subscriptions(portfolio_id),
        )
        self.store.replace_subscriptions(portfolio_id, subscriptions)
        return report, tuple(subscriptions)
```

Replace with:
```python
        self.store.save_tickers(report.tickers)
        active_tickers = [t for t in report.tickers if t.status == "active"]
        subscriptions = create_subscriptions_for_portfolio(
            active_tickers,
            created_from_import_id=report.import_id,
            existing=self.store.list_subscriptions(portfolio_id),
        )
        self.store.replace_subscriptions(portfolio_id, subscriptions)
        return report, tuple(subscriptions)
```

- [ ] **Step 1.5: Run targeted test to verify it passes**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_sqlite_persistence.SQLiteStoreTests.test_replace_mode_import_deletes_subscriptions_for_inactive_tickers -v
```

Expected: `OK`

- [ ] **Step 1.6: Run full test suite**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: all tests pass (≥175 tests).

- [ ] **Step 1.7: Commit**

```
git add backend/sentinel_core/persistent_service.py backend/sentinel_core/subscriptions.py tests/test_sqlite_persistence.py
git commit -m "fix: delete subscriptions for inactive tickers on replace-mode import

Replace-mode CSV import now passes only active tickers to
create_subscriptions_for_portfolio. Inactive tickers (those removed
from the file) have their subscriptions deleted via the existing
replace_subscriptions path.

Added active-ticker guard in create_subscriptions_for_portfolio to
catch future callers passing inactive tickers at the call site.

Closes finding 1 from AUDIT_FINDINGS_2026-06-23.md.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Wire Scorecard Stale Exit Events

**Goal:** Open exit alerts older than 48 h are marked deferred; older than 7 d are missed. This runs during `evaluate_portfolio` and via a dedicated maintenance endpoint.

**Files:**
- Modify: `backend/sentinel_core/sqlite_store.py`
- Modify: `backend/sentinel_core/persistent_service.py`
- Modify: `backend/sentinel_core/http_api.py`
- Modify: `tests/test_sqlite_persistence.py`
- Modify: `tests/test_http_api.py`

**Interfaces:**
- Consumes: `scorecard.stale_exit_events(alerts, now=...)` — already exists, already accepts injectable `now`.
- Produces: `SQLiteStore.save_scorecard_event_if_not_exists(event) -> bool` — new idempotent write.
- Produces: `POST /portfolios/{id}/maintenance/scorecard` → `{"deferred_written": N, "missed_written": N}`.

- [ ] **Step 2.1: Write failing test for idempotent scorecard event save**

Add to `tests/test_sqlite_persistence.py`:

```python
def test_save_scorecard_event_if_not_exists_is_idempotent(self):
    from sentinel_core.sqlite_store import SQLiteStore
    from sentinel_core.models import ScorecardEvent
    from datetime import datetime
    from uuid import uuid4

    store = SQLiteStore.in_memory()
    user_id = uuid4()
    portfolio_id = uuid4()
    alert_id = uuid4()
    event = ScorecardEvent(
        event_id=uuid4(),
        user_id=user_id,
        portfolio_id=portfolio_id,
        portfolio_ticker_id=uuid4(),
        ticker="AAPL",
        alert_id=alert_id,
        kind="deferred",
        rule_id="P1",
        occurred_at=datetime(2026, 6, 23, 12, 0, 0),
        note="Exit alert open for 2 days, 1:00:00",
    )

    written_first = store.save_scorecard_event_if_not_exists(event)
    self.assertTrue(written_first, "First call should write the event")

    # Second call with same alert_id + kind — must not write again
    duplicate = ScorecardEvent(
        event_id=uuid4(),  # different event_id, same (alert_id, kind)
        user_id=user_id,
        portfolio_id=portfolio_id,
        portfolio_ticker_id=uuid4(),
        ticker="AAPL",
        alert_id=alert_id,
        kind="deferred",
        rule_id="P1",
        occurred_at=datetime(2026, 6, 23, 13, 0, 0),
        note="duplicate",
    )
    written_second = store.save_scorecard_event_if_not_exists(duplicate)
    self.assertFalse(written_second, "Second call with same (alert_id, kind) must be a no-op")
```

- [ ] **Step 2.2: Run to confirm it fails**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_sqlite_persistence.SQLiteStoreTests.test_save_scorecard_event_if_not_exists_is_idempotent -v
```

Expected: `FAIL` with `AttributeError: 'SQLiteStore' object has no attribute 'save_scorecard_event_if_not_exists'`.

- [ ] **Step 2.3: Add `save_scorecard_event_if_not_exists` to `sqlite_store.py`**

Open `backend/sentinel_core/sqlite_store.py`. After the existing `save_scorecard_event` method (around line 1099), add:

```python
    def save_scorecard_event_if_not_exists(self, event: ScorecardEvent) -> bool:
        """Write event only if no event with the same (alert_id, kind) exists.

        Returns True if the event was written, False if already present.
        This prevents duplicate deferred/missed events on repeated evaluate runs.
        """
        with self._lock:
            existing = self.conn.execute(
                "SELECT 1 FROM scorecard_events WHERE alert_id = ? AND kind = ?",
                (str(event.alert_id), event.kind),
            ).fetchone()
            if existing is not None:
                return False
            self.save_scorecard_event(event)
            return True
```

- [ ] **Step 2.4: Run idempotency test to confirm it passes**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_sqlite_persistence.SQLiteStoreTests.test_save_scorecard_event_if_not_exists_is_idempotent -v
```

Expected: `OK`

- [ ] **Step 2.5: Write failing test for scorecard wiring in evaluate path**

Add to `tests/test_sqlite_persistence.py`:

```python
def test_evaluate_portfolio_writes_deferred_scorecard_event_for_stale_exit_alert(self):
    from sentinel_core.persistent_service import PersistentSentinelWorkspace
    from sentinel_core.sqlite_store import SQLiteStore
    from sentinel_core.models import AlertRecord, RuleResult, AlertExplanation
    from datetime import datetime, timedelta, date
    from uuid import uuid4
    import unittest.mock as mock

    store = SQLiteStore.in_memory()
    workspace = PersistentSentinelWorkspace(store)
    user_id = uuid4()
    portfolio = workspace.create_portfolio(user_id=user_id, name="Test")
    pid = portfolio.portfolio_id

    # Import a ticker so evaluate has something to work with
    workspace.import_csv(
        user_id=user_id,
        portfolio_id=pid,
        csv_text="ticker,type\nAAPL,investor\n",
    )

    # Directly inject a stale open exit alert (created 49 hours ago)
    ticker_obj = store.list_tickers(pid)[0]
    stale_time = datetime.utcnow() - timedelta(hours=49)
    result = RuleResult(
        user_id=user_id,
        portfolio_id=pid,
        portfolio_ticker_id=ticker_obj.portfolio_ticker_id,
        ticker="AAPL",
        rule_id="P1",
        kind="exit",
        severity="critical",
        triggered=True,
        state_active=True,
        suggested_action="Exit position",
        payload={},
        dedupe_key="P1:AAPL:exit",
    )
    explanation = AlertExplanation(
        rule_id="P1",
        title="SMA150 exit",
        what_triggered="Price crossed below SMA150",
        rule_rationale="Investor exit rule",
        evidence={},
        recommended_action="Exit position",
        source_section="P1",
    )
    alert = AlertRecord(
        alert_id=uuid4(),
        result=result,
        explanation=explanation,
        status="new",
        created_at=stale_time,
    )
    store.save_alert(alert)

    # Run evaluate with no market data — it will resolve the manually inserted alert
    # but stale scorecard wiring should still fire on the open alerts found before resolve
    # Use a mock provider that returns no bars
    from sentinel_core.market_data import InMemoryMarketDataProvider
    # evaluate_portfolio uses store.list_alerts which includes our stale alert
    # The stale exit check runs after alert resolution, so we check scorecard_events
    workspace.evaluate_portfolio(portfolio_id=pid, asof=date.today())

    # Scorecard events table should have a 'deferred' event for our stale alert
    rows = store.conn.execute(
        "SELECT kind FROM scorecard_events WHERE alert_id = ?",
        (str(alert.alert_id),),
    ).fetchall()
    kinds = {row["kind"] for row in rows}
    self.assertIn("deferred", kinds, "evaluate_portfolio must write a deferred scorecard event for stale exit alerts")
```

- [ ] **Step 2.6: Run to confirm it fails**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_sqlite_persistence.SQLiteStoreTests.test_evaluate_portfolio_writes_deferred_scorecard_event_for_stale_exit_alert -v
```

Expected: `FAIL` — no deferred event written.

- [ ] **Step 2.7: Wire stale exit events into `evaluate_portfolio` in `persistent_service.py`**

Open `backend/sentinel_core/persistent_service.py`.

First, add `stale_exit_events` to the import from `.scorecard`:

Find:
```python
from .scorecard import acknowledge_alert
```

Replace with:
```python
from .scorecard import acknowledge_alert, stale_exit_events
```

Then, in `evaluate_portfolio`, after the line `self.store.save_alerts(created)` (around line 210) and before `notification_settings = ...`, add:

```python
            # Wire stale exit scorecard events — deferred (48 h) and missed (7 d)
            all_open_alerts = [
                a for a in self.store.list_alerts(portfolio_id)
                if a.status in {"new", "sent"} and a.result.kind == "exit"
            ]
            for stale_event in stale_exit_events(all_open_alerts):
                self.store.save_scorecard_event_if_not_exists(stale_event)
```

- [ ] **Step 2.8: Run evaluate stale-exit test to confirm it passes**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_sqlite_persistence.SQLiteStoreTests.test_evaluate_portfolio_writes_deferred_scorecard_event_for_stale_exit_alert -v
```

Expected: `OK`

- [ ] **Step 2.9: Write failing test for the maintenance endpoint**

Add to `tests/test_http_api.py` (inside the existing `HttpApiTests` class). The test pattern in this file is: create a `create_server(db_path=":memory:", port=0)`, start it in a thread, make real HTTP calls via `request(server, ...)`, then shut down. For state injection we use `SentinelApi.handle()` directly with a controlled workspace.

```python
def test_maintenance_scorecard_endpoint_returns_counts_and_is_idempotent(self):
    import threading
    from datetime import datetime, timedelta
    from uuid import uuid4
    from sentinel_core.sqlite_store import SQLiteStore
    from sentinel_core.persistent_service import PersistentSentinelWorkspace
    from sentinel_core.http_api import SentinelApi
    from sentinel_core.models import AlertRecord, RuleResult, AlertExplanation
    from http import HTTPStatus

    # Set up a controlled workspace
    store = SQLiteStore.in_memory()
    workspace = PersistentSentinelWorkspace(store)
    api = SentinelApi(workspace)
    user_id = uuid4()

    # Create portfolio via API
    status, body = api.handle("POST", "/portfolios", {}, {"name": "Test", "user_id": str(user_id)})
    portfolio_id = body["portfolio"]["portfolio_id"]

    # Inject a stale open exit alert (49 hours old)
    ticker_id = uuid4()
    stale_time = datetime.utcnow() - timedelta(hours=49)
    result = RuleResult(
        user_id=user_id,
        portfolio_id=portfolio_id,
        portfolio_ticker_id=ticker_id,
        ticker="AAPL",
        rule_id="P1",
        kind="exit",
        severity="critical",
        triggered=True,
        state_active=True,
        suggested_action="Exit",
        payload={},
        dedupe_key="P1:AAPL:exit",
    )
    explanation = AlertExplanation(
        rule_id="P1", title="P1", what_triggered="x",
        rule_rationale="r", evidence={}, recommended_action="a", source_section="P1",
    )
    alert = AlertRecord(
        alert_id=uuid4(), result=result, explanation=explanation,
        status="new", created_at=stale_time,
    )
    store.save_alert(alert)

    # Call maintenance endpoint
    status, resp = api.handle(
        "POST", "/portfolios/%s/maintenance/scorecard" % portfolio_id, {}, {}
    )
    self.assertEqual(status, HTTPStatus.OK)
    self.assertEqual(resp["deferred_written"], 1)
    self.assertEqual(resp["missed_written"], 0)

    # Second call must be idempotent
    status2, resp2 = api.handle(
        "POST", "/portfolios/%s/maintenance/scorecard" % portfolio_id, {}, {}
    )
    self.assertEqual(resp2["deferred_written"], 0)
    self.assertEqual(resp2["missed_written"], 0)
```

- [ ] **Step 2.10: Run to confirm it fails**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_http_api.HttpApiTests.test_maintenance_scorecard_endpoint_returns_counts_and_is_idempotent -v
```

Expected: `FAIL` — route not found.

- [ ] **Step 2.11: Add maintenance scorecard endpoint to `http_api.py`**

Open `backend/sentinel_core/http_api.py`.

First, add `stale_exit_events` to the import from `.scorecard` in the imports section. Find the existing import block and add it. Currently there is no direct import of scorecard in http_api.py — add it near the top:

```python
from .scorecard import stale_exit_events
```

Then, in the `handle` method of `SentinelApi`, find the route for the report:
```python
        match = re.fullmatch(r"/portfolios/([^/]+)/report", path)
        if method == "GET" and match:
```

Insert a new route **before** this block:

```python
        match = re.fullmatch(r"/portfolios/([^/]+)/maintenance/scorecard", path)
        if method == "POST" and match:
            portfolio_id = UUID(match.group(1))
            return HTTPStatus.OK, self.maintenance_scorecard(portfolio_id)

```

Then add the `maintenance_scorecard` method to `SentinelApi` (after the `test_notification_settings` method):

```python
    def maintenance_scorecard(self, portfolio_id: UUID) -> dict:
        """Sweep open exit alerts and write deferred/missed scorecard events.

        Idempotent: safe to call from a daily cron job on the Pi.
        Returns counts of newly written events only (not skipped duplicates).
        """
        open_exit_alerts = [
            a for a in self.workspace.store.list_alerts(portfolio_id)
            if a.status in {"new", "sent"} and a.result.kind == "exit"
        ]
        events = stale_exit_events(open_exit_alerts)
        deferred_written = 0
        missed_written = 0
        for event in events:
            written = self.workspace.store.save_scorecard_event_if_not_exists(event)
            if written:
                if event.kind == "deferred":
                    deferred_written += 1
                elif event.kind == "missed":
                    missed_written += 1
        return {"deferred_written": deferred_written, "missed_written": missed_written}
```

- [ ] **Step 2.12: Run maintenance endpoint test**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_http_api.HttpApiTests.test_maintenance_scorecard_endpoint_returns_counts_and_is_idempotent -v
```

Expected: `OK`

- [ ] **Step 2.13: Run full test suite**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2.14: Commit**

```
git add backend/sentinel_core/sqlite_store.py backend/sentinel_core/persistent_service.py backend/sentinel_core/http_api.py tests/test_sqlite_persistence.py tests/test_http_api.py
git commit -m "feat: wire scorecard stale exit events into evaluate and maintenance endpoint

- SQLiteStore.save_scorecard_event_if_not_exists: idempotent write keyed
  on (alert_id, kind) — prevents duplicate deferred/missed events on
  repeated evaluate runs.
- evaluate_portfolio now calls stale_exit_events() on all open exit alerts
  after each run and writes new deferred/missed events.
- POST /portfolios/{id}/maintenance/scorecard: sweep endpoint for Pi cron.
  Returns {deferred_written, missed_written}. Safe to call repeatedly.

Closes finding 2 from AUDIT_FINDINGS_2026-06-23.md.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Refresh Docs — RUNBOOK.md and Handoff

**Goal:** Create a current operational runbook; label the May handoff as historical; resolve known-open items in DEPLOYMENT.md.

**Files:**
- Create: `docs/RUNBOOK.md`
- Modify: `docs/HANDOFF_2026-05-21.md`
- Modify: `docs/DEPLOYMENT.md`

No tests needed — docs only. Run validate_upload_package.py at the end.

- [ ] **Step 3.1: Prepend historical label to `docs/HANDOFF_2026-05-21.md`**

Open `docs/HANDOFF_2026-05-21.md`. Insert this block at the very top (before `# Felix Alerts Project Handoff`):

```markdown
> **Historical handoff** — this document reflects the state of the project on 2026-05-21.
> Current operational state, commit, and test counts are in [RUNBOOK.md](RUNBOOK.md).

```

- [ ] **Step 3.2: Create `docs/RUNBOOK.md`**

Create the file with the following content (update the commit hash from `git rev-parse HEAD` before writing):

```markdown
# Sentinel Operational Runbook

Last updated: 2026-06-23

## Current Source State

- Branch: `main`
- HEAD commit: `734feec78ecf02e06a84df0101bf1a17050359c2` (update to current after each deployment)
- Test suite: 175 tests passed, 1 skipped (as of 2026-06-23; count grows with new features)

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
```

- [ ] **Step 3.3: Resolve open items in `docs/DEPLOYMENT.md`**

In `docs/DEPLOYMENT.md`, find the `## Remaining Deployment Decisions` section at the bottom (lines 268-276) and replace it:

```markdown
## Remaining Deployment Decisions

These items are resolved for the current production Pi deployment:

- **GitHub repository**: `https://github.com/meiriohad76-oss/felix-alerts` (public).
- **Pi install path**: `/opt/sentinel` (confirmed).
- **Production hostname**: `sentinel1.ahaddashboards.uk` (Cloudflare tunnel `pi-ai`).
- **Cloudflare Access**: must be configured before sharing the public URL — see Security Gate section above.
- **Email SMTP**: not yet configured. Set `SENTINEL_EMAIL_HOST`, `SENTINEL_EMAIL_PORT`, `SENTINEL_EMAIL_FROM`, `SENTINEL_EMAIL_USERNAME`, `SENTINEL_EMAIL_PASSWORD` in `/etc/sentinel/sentinel.env`.
- **Telegram**: not yet configured. Set `SENTINEL_TELEGRAM_BOT_TOKEN` in `/etc/sentinel/sentinel.env`; configure chat id in app Settings.
```

- [ ] **Step 3.4: Validate upload package still passes**

```
$env:PYTHONPATH="backend;."
python scripts/validate_upload_package.py
```

Expected: `Upload package validation passed.`

- [ ] **Step 3.5: Commit**

```
git add docs/RUNBOOK.md docs/HANDOFF_2026-05-21.md docs/DEPLOYMENT.md
git commit -m "docs: add RUNBOOK.md, label historical handoff, resolve DEPLOYMENT open items

- docs/RUNBOOK.md: single operational reference with current commit,
  test count, Pi commands, Cloudflare tunnel details, and known limits.
- docs/HANDOFF_2026-05-21.md: prepended historical-handoff notice.
- docs/DEPLOYMENT.md: resolved all open deployment decision items with
  known production values.

Closes finding 5 from AUDIT_FINDINGS_2026-06-23.md.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Cloudflare Access Security Gate in DEPLOYMENT.md

**Goal:** Document Cloudflare Access as a mandatory deployment gate; add a validator check that prevents removing it accidentally.

**Files:**
- Modify: `docs/DEPLOYMENT.md`
- Modify: `scripts/validate_upload_package.py`

- [ ] **Step 4.1: Add Security Gate section to `docs/DEPLOYMENT.md`**

Open `docs/DEPLOYMENT.md`. Find `## 3. Cloudflare Tunnel` (around line 131). Insert the following block **immediately before** that heading:

```markdown
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

```

- [ ] **Step 4.2: Add validator check to `scripts/validate_upload_package.py`**

Open `scripts/validate_upload_package.py`. After the `scan_secrets` function (around line 96), add a new function:

```python
def check_deployment_doc_security_gate() -> list[str]:
    """Warn if the Security Gate section has been removed from DEPLOYMENT.md."""
    deployment_md = ROOT / "docs" / "DEPLOYMENT.md"
    if not deployment_md.exists():
        return ["docs/DEPLOYMENT.md not found — security gate cannot be verified"]
    text = deployment_md.read_text(encoding="utf-8")
    if "Security Gate" not in text:
        return [
            "docs/DEPLOYMENT.md is missing the 'Security Gate' section. "
            "Add the Cloudflare Access prerequisite before publishing."
        ]
    return []
```

Then in `main()`, after `findings = scan_secrets(files)` and its error block, add:

```python
    security_warnings = check_deployment_doc_security_gate()
    if security_warnings:
        print("Upload package validation warning:", file=sys.stderr)
        for warning in security_warnings:
            print("  " + warning, file=sys.stderr)
        # Warn only — do not fail the validation, since this is a docs check
```

- [ ] **Step 4.3: Run validate_upload_package.py to confirm it passes**

```
python scripts/validate_upload_package.py
```

Expected: `Upload package validation passed.` with no security warning (because we just added the section).

- [ ] **Step 4.4: Run full test suite**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 4.5: Commit**

```
git add docs/DEPLOYMENT.md scripts/validate_upload_package.py
git commit -m "docs: add Cloudflare Access security gate prerequisite

- DEPLOYMENT.md: new 'Security Gate' section before Cloudflare Tunnel
  instructions. Documents that Cloudflare Access is mandatory before
  public exposure, with setup steps and verification instructions.
- validate_upload_package.py: warns if Security Gate section is missing
  from DEPLOYMENT.md, catching future accidental removal.

Closes finding 3 from AUDIT_FINDINGS_2026-06-23.md.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: UUID Parse Errors Return 400

**Goal:** Malformed UUID route parameters return HTTP 400 with a stable error message instead of a generic 500.

**Files:**
- Modify: `backend/sentinel_core/http_api.py`
- Modify: `tests/test_http_api.py`

**Interfaces:**
- Produces: `_parse_uuid(value: str, field_name: str) -> UUID` — private helper in `http_api.py`.

- [ ] **Step 5.1: Write failing tests for UUID validation**

Add to `tests/test_http_api.py` (inside `HttpApiTests`). Tests use the real HTTP server (`create_server` + `request`) so UUID parsing happens through the full HTTP layer:

```python
def test_malformed_portfolio_id_returns_400(self):
    import threading
    server = create_server(db_path=":memory:", port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        status, data = request(server, "GET", "/portfolios/not-a-uuid")
        self.assertEqual(status, 400)
        self.assertIn("portfolio_id", data.get("error", ""))
    finally:
        server.shutdown()
        server.server_close()

def test_malformed_alert_id_returns_400(self):
    import threading
    server = create_server(db_path=":memory:", port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        # First create a portfolio to get a valid portfolio_id
        _, portfolio_data = request(server, "POST", "/portfolios", {"name": "Test"})
        pid = portfolio_data["portfolio"]["portfolio_id"]
        status, data = request(
            server,
            "POST",
            "/portfolios/%s/alerts/not-a-uuid/ack" % pid,
            {"ack_kind": "placed"},
        )
        self.assertEqual(status, 400)
        self.assertIn("alert_id", data.get("error", ""))
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 5.2: Run to confirm they fail**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_http_api.HttpApiTests.test_malformed_portfolio_id_returns_400 tests.test_http_api.HttpApiTests.test_malformed_alert_id_returns_400 -v
```

Expected: `FAIL` — returns 500 (or error dict has wrong key).

- [ ] **Step 5.3: Add `_parse_uuid` helper to `http_api.py`**

Open `backend/sentinel_core/http_api.py`. After the existing `_parse_limited_int` function (around line 109), add:

```python
def _parse_uuid(value: str, field_name: str) -> UUID:
    """Parse a UUID string, raising ApiError 400 on invalid input.

    Use this for all route, query, and body UUID parameters instead of
    calling UUID() directly — UUID() raises ValueError which maps to 500.
    """
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "Invalid %s: must be a valid UUID" % field_name,
        ) from exc
```

- [ ] **Step 5.4: Replace inline `UUID(...)` calls in `handle()` with `_parse_uuid`**

In `SentinelApi.handle()`, replace every `UUID(match.group(1))` and `UUID(match.group(2))` with the appropriate `_parse_uuid` call. Here are all the locations and their replacements:

```python
# /portfolios GET — user_id from query string
user_id = UUID(query.get("user_id", [str(DEFAULT_USER_ID)])[0])
# → replace with:
user_id = _parse_uuid(query.get("user_id", [str(DEFAULT_USER_ID)])[0], "user_id")

# /portfolios/{id} GET
return HTTPStatus.OK, self.portfolio_detail(UUID(match.group(1)))
# → replace with:
return HTTPStatus.OK, self.portfolio_detail(_parse_uuid(match.group(1), "portfolio_id"))

# /portfolios/{id}/preview POST
return HTTPStatus.OK, self.preview_csv(UUID(match.group(1)), body)
# → replace with:
return HTTPStatus.OK, self.preview_csv(_parse_uuid(match.group(1), "portfolio_id"), body)

# /portfolios/{id}/import POST
return HTTPStatus.OK, self.import_csv(UUID(match.group(1)), body)
# → replace with:
return HTTPStatus.OK, self.import_csv(_parse_uuid(match.group(1), "portfolio_id"), body)

# /portfolios/{id}/tickers/{ticker} GET
return HTTPStatus.OK, self.ticker_detail(UUID(match.group(1)), unquote(match.group(2)))
# → replace with:
return HTTPStatus.OK, self.ticker_detail(_parse_uuid(match.group(1), "portfolio_id"), unquote(match.group(2)))

# /portfolios/{id}/tickers/{ticker}/classify POST
return HTTPStatus.OK, self.classify_ticker(UUID(match.group(1)), unquote(match.group(2)), body)
# → replace with:
return HTTPStatus.OK, self.classify_ticker(_parse_uuid(match.group(1), "portfolio_id"), unquote(match.group(2)), body)

# /portfolios/{id}/tickers/{ticker}/setup-data POST
return HTTPStatus.OK, self.update_ticker_setup_data(UUID(match.group(1)), unquote(match.group(2)), body)
# → replace with:
return HTTPStatus.OK, self.update_ticker_setup_data(_parse_uuid(match.group(1), "portfolio_id"), unquote(match.group(2)), body)

# /portfolios/{id}/tickers/classify-unknown POST
return HTTPStatus.OK, self.classify_unknown_tickers(UUID(match.group(1)), body)
# → replace with:
return HTTPStatus.OK, self.classify_unknown_tickers(_parse_uuid(match.group(1), "portfolio_id"), body)

# /portfolios/{id}/backfill-online POST
return HTTPStatus.OK, self.backfill_online(UUID(match.group(1)), body)
# → replace with:
return HTTPStatus.OK, self.backfill_online(_parse_uuid(match.group(1), "portfolio_id"), body)

# /portfolios/{id}/backfill-massive POST
return HTTPStatus.OK, self.backfill_massive(UUID(match.group(1)), body)
# → replace with:
return HTTPStatus.OK, self.backfill_massive(_parse_uuid(match.group(1), "portfolio_id"), body)

# /portfolios/{id}/evaluate POST
return HTTPStatus.OK, self.evaluate(UUID(match.group(1)), body)
# → replace with:
return HTTPStatus.OK, self.evaluate(_parse_uuid(match.group(1), "portfolio_id"), body)

# /portfolios/{id}/runs/latest GET
run = self.workspace.store.latest_monitor_run(UUID(match.group(1)))
# → replace with:
run = self.workspace.store.latest_monitor_run(_parse_uuid(match.group(1), "portfolio_id"))

# /portfolios/{id}/runs GET
return HTTPStatus.OK, {"runs": self.workspace.store.list_monitor_runs(UUID(match.group(1)))}
# → replace with:
return HTTPStatus.OK, {"runs": self.workspace.store.list_monitor_runs(_parse_uuid(match.group(1), "portfolio_id"))}

# /portfolios/{id}/alerts GET
portfolio_id = UUID(match.group(1))  (in alerts block)
# → replace with:
portfolio_id = _parse_uuid(match.group(1), "portfolio_id")

# /portfolios/{id}/alert-events GET
portfolio_id = UUID(match.group(1))  (in alert-events block)
# → replace with:
portfolio_id = _parse_uuid(match.group(1), "portfolio_id")

# /portfolios/{id}/notification-settings GET/POST
return HTTPStatus.OK, self.notification_settings(UUID(match.group(1)))
return HTTPStatus.OK, self.save_notification_settings(UUID(match.group(1)), body)
# → replace with _parse_uuid(match.group(1), "portfolio_id") in both

# /portfolios/{id}/notification-settings/test POST
return HTTPStatus.OK, self.test_notification_settings(UUID(match.group(1)))
# → replace with _parse_uuid(match.group(1), "portfolio_id")

# /portfolios/{id}/notifications GET
portfolio_id = UUID(match.group(1))  (in notifications block)
# → replace with:
portfolio_id = _parse_uuid(match.group(1), "portfolio_id")

# /portfolios/{id}/alerts/{alert_id}/ack POST
return HTTPStatus.OK, self.acknowledge(UUID(match.group(1)), UUID(match.group(2)), body)
# → replace with:
return HTTPStatus.OK, self.acknowledge(
    _parse_uuid(match.group(1), "portfolio_id"),
    _parse_uuid(match.group(2), "alert_id"),
    body,
)

# /portfolios/{id}/report GET
portfolio_id = UUID(match.group(1))  (in report block)
# → replace with:
portfolio_id = _parse_uuid(match.group(1), "portfolio_id")

# /portfolios/{id}/maintenance/scorecard POST (added in Task 2)
portfolio_id = UUID(match.group(1))
# → replace with:
portfolio_id = _parse_uuid(match.group(1), "portfolio_id")
```

Also fix `create_portfolio` method body (not in `handle`, but in the method itself):
```python
def create_portfolio(self, body: dict) -> dict:
    user_id = UUID(body.get("user_id", str(DEFAULT_USER_ID)))
    # → replace with:
    user_id = _parse_uuid(body.get("user_id", str(DEFAULT_USER_ID)), "user_id")
```

- [ ] **Step 5.5: Run UUID validation tests**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_http_api.HttpApiTests.test_malformed_portfolio_id_returns_400 tests.test_http_api.HttpApiTests.test_malformed_alert_id_returns_400 -v
```

Expected: `OK`

- [ ] **Step 5.6: Run full test suite**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 5.7: Commit**

```
git add backend/sentinel_core/http_api.py tests/test_http_api.py
git commit -m "fix: malformed UUID route params return 400 instead of 500

Added _parse_uuid(value, field_name) helper that raises ApiError 400
on invalid UUID input. Replaced all inline UUID(...) calls in the
SentinelApi.handle() dispatcher and create_portfolio body parser.

Closes finding 4 from AUDIT_FINDINGS_2026-06-23.md.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Async Backfill via SQLite Job Queue

**Goal:** Backfill and evaluate endpoints return a job_id immediately; a background worker thread processes jobs; clients poll `GET /jobs/{id}`.

**Files:**
- Modify: `backend/sentinel_core/sqlite_store.py`
- Modify: `backend/sentinel_core/persistent_service.py`
- Modify: `backend/sentinel_core/http_api.py`
- Modify: `frontend/sidebar.html`
- Modify: `tests/test_sqlite_persistence.py`
- Modify: `tests/test_http_api.py`

**Interfaces:**
- Produces: `SQLiteStore.enqueue_job(portfolio_id, kind, params) -> dict` with keys `job_id, status, created_at`.
- Produces: `SQLiteStore.dequeue_next_job() -> dict | None` — picks oldest queued job atomically.
- Produces: `SQLiteStore.get_job(job_id) -> dict | None`.
- Produces: `SQLiteStore.update_job(job_id, *, status, tickers_done, tickers_failed, error)`.
- Produces: `GET /jobs/{job_id}` → job dict.

- [ ] **Step 6.1: Add `monitor_jobs` table to schema in `sqlite_store.py`**

Open `backend/sentinel_core/sqlite_store.py`. At the end of the `SCHEMA` string (just before the closing `"""`), add:

```sql
CREATE TABLE IF NOT EXISTS monitor_jobs (
  job_id TEXT PRIMARY KEY,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',
  created_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  tickers_total INTEGER NOT NULL DEFAULT 0,
  tickers_done INTEGER NOT NULL DEFAULT 0,
  tickers_failed INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT ''
);
```

Also update `init_schema` to call `_ensure_column` for any existing DBs that lack the table (the `CREATE TABLE IF NOT EXISTS` handles this, but the existing `_ensure_column` pattern handles column additions). The table itself will be created fresh.

- [ ] **Step 6.2: Write failing test for job enqueue and get**

Add to `tests/test_sqlite_persistence.py`:

```python
def test_monitor_job_enqueue_and_get(self):
    from sentinel_core.sqlite_store import SQLiteStore
    from uuid import uuid4

    store = SQLiteStore.in_memory()
    user_id = uuid4()
    # Need a portfolio for the FK constraint
    from sentinel_core.models import Portfolio
    pid = uuid4()
    store.save_portfolio(Portfolio(portfolio_id=pid, user_id=user_id, name="Test"))

    job = store.enqueue_job(pid, kind="backfill_massive", params={"api_key": "test", "lookback": 250})
    self.assertEqual(job["status"], "queued")
    self.assertIn("job_id", job)

    fetched = store.get_job(job["job_id"])
    self.assertIsNotNone(fetched)
    self.assertEqual(fetched["status"], "queued")
    self.assertEqual(fetched["kind"], "backfill_massive")
    self.assertEqual(fetched["portfolio_id"], pid)

def test_monitor_job_dequeue_sets_running(self):
    from sentinel_core.sqlite_store import SQLiteStore
    from sentinel_core.models import Portfolio
    from uuid import uuid4

    store = SQLiteStore.in_memory()
    pid = uuid4()
    store.save_portfolio(Portfolio(portfolio_id=pid, user_id=uuid4(), name="Test"))

    job = store.enqueue_job(pid, kind="evaluate", params={"asof": "2026-06-23"})
    dequeued = store.dequeue_next_job()
    self.assertIsNotNone(dequeued)
    self.assertEqual(str(dequeued["job_id"]), str(job["job_id"]))
    self.assertEqual(dequeued["status"], "running")

    # dequeue again — nothing left
    self.assertIsNone(store.dequeue_next_job())
```

- [ ] **Step 6.3: Run to confirm they fail**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_sqlite_persistence.SQLiteStoreTests.test_monitor_job_enqueue_and_get tests.test_sqlite_persistence.SQLiteStoreTests.test_monitor_job_dequeue_sets_running -v
```

Expected: `FAIL`.

- [ ] **Step 6.4: Add job store methods to `sqlite_store.py`**

At the bottom of the `SQLiteStore` class (before the class ends), add:

```python
    def enqueue_job(self, portfolio_id: UUID, *, kind: str, params: dict) -> dict:
        """Create a new queued monitor job and return it as a dict."""
        import json as _json
        job_id = uuid4()
        now = _utc_now_iso()
        with self._lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO monitor_jobs(job_id, portfolio_id, kind, params_json, status, created_at)
                    VALUES (?, ?, ?, ?, 'queued', ?)
                    """,
                    (str(job_id), str(portfolio_id), kind, _json.dumps(params), now),
                )
        return self.get_job(job_id)

    def get_job(self, job_id: UUID) -> Optional[dict]:
        """Return a job dict or None if not found."""
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM monitor_jobs WHERE job_id = ?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                return None
            return self._job_from_row(row)

    def dequeue_next_job(self) -> Optional[dict]:
        """Atomically pick the oldest queued job and mark it running.

        Returns the job dict (now status='running') or None if queue is empty.
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM monitor_jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job_id = row["job_id"]
            now = _utc_now_iso()
            with self.conn:
                self.conn.execute(
                    "UPDATE monitor_jobs SET status = 'running', started_at = ? WHERE job_id = ?",
                    (now, job_id),
                )
            return self.get_job(UUID(job_id))

    def finish_job(
        self,
        job_id: UUID,
        *,
        status: str,
        tickers_total: int = 0,
        tickers_done: int = 0,
        tickers_failed: int = 0,
        error: str = "",
    ) -> None:
        """Mark a job done or failed with final counts."""
        now = _utc_now_iso()
        with self._lock:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE monitor_jobs
                    SET status = ?, completed_at = ?,
                        tickers_total = ?, tickers_done = ?, tickers_failed = ?, error = ?
                    WHERE job_id = ?
                    """,
                    (status, now, tickers_total, tickers_done, tickers_failed, error, str(job_id)),
                )

    def _job_from_row(self, row: sqlite3.Row) -> dict:
        import json as _json
        return {
            "job_id": UUID(row["job_id"]),
            "portfolio_id": UUID(row["portfolio_id"]),
            "kind": row["kind"],
            "params": _json.loads(row["params_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "tickers_total": int(row["tickers_total"]),
            "tickers_done": int(row["tickers_done"]),
            "tickers_failed": int(row["tickers_failed"]),
            "error": row["error"],
        }
```

- [ ] **Step 6.5: Run job store tests**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_sqlite_persistence.SQLiteStoreTests.test_monitor_job_enqueue_and_get tests.test_sqlite_persistence.SQLiteStoreTests.test_monitor_job_dequeue_sets_running -v
```

Expected: `OK`

- [ ] **Step 6.6: Add `GET /jobs/{id}` endpoint and job-queue endpoints to `http_api.py`**

Open `backend/sentinel_core/http_api.py`.

**a) Add job polling route** — in `handle()`, before the final `raise ApiError(HTTPStatus.NOT_FOUND, ...)` line, add:

```python
        match = re.fullmatch(r"/jobs/([^/]+)", path)
        if method == "GET" and match:
            job_id = _parse_uuid(match.group(1), "job_id")
            job = self.workspace.store.get_job(job_id)
            if job is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "Job not found: %s" % job_id)
            return HTTPStatus.OK, {"job": job}
```

**b) Change `backfill_massive` and `backfill_online` to enqueue** — find the existing `backfill_massive` and `backfill_online` methods. Replace their implementations to enqueue a job and return immediately:

```python
    def backfill_massive(self, portfolio_id: UUID, body: dict) -> dict:
        api_key = body.get("api_key") or os.environ.get("MASSIVE_API_KEY") or ""
        lookback = _parse_limited_int(
            body.get("lookback"), "lookback", default=250, minimum=10, maximum=500
        )
        end = _parse_iso_date(body.get("end"), "end")
        job = self.workspace.store.enqueue_job(
            portfolio_id,
            kind="backfill_massive",
            params={"api_key": api_key, "lookback": lookback, "end": end.isoformat()},
        )
        return {"job": job}

    def backfill_online(self, portfolio_id: UUID, body: dict) -> dict:
        lookback = _parse_limited_int(
            body.get("lookback"), "lookback", default=250, minimum=10, maximum=500
        )
        end = _parse_iso_date(body.get("end"), "end")
        job = self.workspace.store.enqueue_job(
            portfolio_id,
            kind="backfill_online",
            params={"lookback": lookback, "end": end.isoformat()},
        )
        return {"job": job}
```

**c) Change `evaluate` to enqueue:**

```python
    def evaluate(self, portfolio_id: UUID, body: dict) -> dict:
        asof = _parse_iso_date(body.get("asof"), "asof")
        job = self.workspace.store.enqueue_job(
            portfolio_id,
            kind="evaluate",
            params={"asof": asof.isoformat()},
        )
        return {"job": job}
```

- [ ] **Step 6.7: Add background worker to `http_api.py`**

Add the following standalone function and modify `create_server` to start it:

After the `SentinelHTTPServer` class, add:

```python
def _run_job_worker(api: "SentinelApi") -> None:
    """Background thread: process queued monitor jobs one at a time."""
    import time as _time
    import json as _json

    while True:
        _time.sleep(1)
        try:
            job = api.workspace.store.dequeue_next_job()
            if job is None:
                continue
            _execute_job(api, job)
        except Exception:
            pass  # worker must never crash


def _execute_job(api: "SentinelApi", job: dict) -> None:
    """Execute a single job, updating the job row with progress and final status."""
    job_id = job["job_id"]
    portfolio_id = job["portfolio_id"]
    params = job["params"]
    kind = job["kind"]
    tickers_done = 0
    tickers_failed = 0
    tickers_total = 0

    try:
        if kind == "backfill_massive":
            api_key = params.get("api_key", "")
            lookback = int(params.get("lookback", 250))
            end = date.fromisoformat(params.get("end", date.today().isoformat()))
            provider = MassiveMarketDataProvider(
                api_key=api_key,
                host=os.environ.get("MASSIVE_API_HOST", "api.massive.com"),
                port=int(os.environ.get("MASSIVE_API_PORT", "443")),
                use_ssl=True,
            )
            tickers = api.workspace.store.list_tickers(portfolio_id, include_inactive=False)
            tickers_total = len(tickers)
            for ticker in tickers:
                try:
                    bars = provider.get_bars(ticker.ticker, end=end, lookback=lookback)
                    if bars:
                        api.workspace.store.save_bars(
                            ticker.ticker, bars,
                            source="massive", source_label="Massive",
                        )
                    tickers_done += 1
                except Exception:
                    tickers_failed += 1

        elif kind == "backfill_online":
            lookback = int(params.get("lookback", 250))
            end = date.fromisoformat(params.get("end", date.today().isoformat()))
            provider = YahooChartMarketDataProvider()
            tickers = api.workspace.store.list_tickers(portfolio_id, include_inactive=False)
            tickers_total = len(tickers)
            for ticker in tickers:
                try:
                    bars = provider.get_bars(ticker.ticker, end=end, lookback=lookback)
                    if bars:
                        api.workspace.store.save_bars(
                            ticker.ticker, bars,
                            source="yahoo", source_label="Yahoo Finance",
                        )
                    tickers_done += 1
                except Exception:
                    tickers_failed += 1

        elif kind == "evaluate":
            asof = date.fromisoformat(params.get("asof", date.today().isoformat()))
            api.workspace.evaluate_portfolio(portfolio_id=portfolio_id, asof=asof)
            tickers = api.workspace.store.list_tickers(portfolio_id, include_inactive=False)
            tickers_total = len(tickers)
            tickers_done = tickers_total

        api.workspace.store.finish_job(
            job_id,
            status="done",
            tickers_total=tickers_total,
            tickers_done=tickers_done,
            tickers_failed=tickers_failed,
        )

    except Exception as exc:
        api.workspace.store.finish_job(
            job_id,
            status="failed",
            tickers_total=tickers_total,
            tickers_done=tickers_done,
            tickers_failed=tickers_failed,
            error=str(exc),
        )
```

Update `create_server` to start the worker thread:

```python
def create_server(
    *,
    db_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    static_dir: Optional[str | Path] = None,
) -> ThreadingHTTPServer:
    store = SQLiteStore(db_path)
    api = SentinelApi(PersistentSentinelWorkspace(store))
    handler = make_handler(api, Path(static_dir) if static_dir else None)
    server = SentinelHTTPServer((host, port), handler)
    # Start background job worker
    import threading as _threading
    worker = _threading.Thread(target=_run_job_worker, args=(api,), daemon=True, name="sentinel-job-worker")
    worker.start()
    return server
```

- [ ] **Step 6.8: Write HTTP test for job queue flow**

Add to `tests/test_http_api.py`:

```python
def test_backfill_massive_returns_job_id(self):
    import threading
    server = create_server(db_path=":memory:", port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        _, portfolio_data = request(server, "POST", "/portfolios", {"name": "Test"})
        pid = portfolio_data["portfolio"]["portfolio_id"]
        status, data = request(server, "POST", "/portfolios/%s/backfill-massive" % pid, {"api_key": "test"})
        self.assertEqual(status, 200)
        self.assertIn("job", data)
        self.assertIn("job_id", str(data["job"]))
        self.assertEqual(data["job"]["status"], "queued")
    finally:
        server.shutdown()
        server.server_close()

def test_get_job_returns_job_status(self):
    import threading
    server = create_server(db_path=":memory:", port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        _, portfolio_data = request(server, "POST", "/portfolios", {"name": "Test"})
        pid = portfolio_data["portfolio"]["portfolio_id"]
        _, backfill_data = request(server, "POST", "/portfolios/%s/backfill-massive" % pid, {"api_key": "test"})
        job_id = backfill_data["job"]["job_id"]
        status, job_data = request(server, "GET", "/jobs/%s" % job_id)
        self.assertEqual(status, 200)
        self.assertIn("job", job_data)
        self.assertIn(job_data["job"]["status"], ("queued", "running", "done", "failed"))
    finally:
        server.shutdown()
        server.server_close()

def test_get_job_with_bad_id_returns_400(self):
    import threading
    server = create_server(db_path=":memory:", port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        status, data = request(server, "GET", "/jobs/not-a-uuid")
        self.assertEqual(status, 400)
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 6.9: Run job endpoint tests**

```
$env:PYTHONPATH="backend;."
python -m unittest tests.test_http_api.HttpApiTests.test_backfill_massive_returns_job_id tests.test_http_api.HttpApiTests.test_get_job_returns_job_status tests.test_http_api.HttpApiTests.test_get_job_with_bad_id_returns_400 -v
```

Expected: `OK`

- [ ] **Step 6.10: Update `frontend/sidebar.html` to poll job status**

Open `frontend/sidebar.html`. Search for the JavaScript functions that call the backfill and evaluate endpoints (search for `backfill-massive`, `backfill-online`, `evaluate`).

For each function that currently does a blocking `fetch` and then calls a refresh function, update the pattern to:

1. POST to the endpoint → receive `{ job: { job_id, status } }`
2. Start polling `GET /jobs/{job_id}` every 2 seconds
3. On status `done` or `failed`, stop polling and refresh portfolio detail

The general polling helper to add in the `<script>` section of `frontend/sidebar.html`:

```javascript
async function pollJobUntilDone(jobId, onProgress, onDone) {
  const interval = setInterval(async () => {
    try {
      const resp = await fetch('/jobs/' + jobId);
      if (!resp.ok) { clearInterval(interval); onDone(null, 'HTTP ' + resp.status); return; }
      const data = await resp.json();
      const job = data.job;
      if (onProgress) onProgress(job);
      if (job.status === 'done' || job.status === 'failed') {
        clearInterval(interval);
        onDone(job, job.status === 'failed' ? (job.error || 'Job failed') : null);
      }
    } catch (err) {
      clearInterval(interval);
      onDone(null, String(err));
    }
  }, 2000);
}
```

Then update each backfill/evaluate call site from:
```javascript
// OLD — blocking pattern
const result = await fetch('/portfolios/' + pid + '/backfill-massive', { method: 'POST', ... });
const data = await result.json();
await refreshPortfolio();
```

To:
```javascript
// NEW — enqueue then poll
const result = await fetch('/portfolios/' + pid + '/backfill-massive', { method: 'POST', ... });
const data = await result.json();
const jobId = data.job.job_id;
showStatus('Running... (job ' + jobId.slice(0, 8) + ')');
pollJobUntilDone(jobId,
  (job) => showStatus('Running... ' + job.tickers_done + '/' + job.tickers_total + ' tickers'),
  async (job, err) => {
    if (err) { showStatus('Run failed: ' + err); }
    else { showStatus('Run complete'); }
    await refreshPortfolio();
  }
);
```

> Find the actual function names by searching for `backfill` and `evaluate` in `sidebar.html`. Apply this pattern to each. If `showStatus` is called differently in this file, match the existing convention.

- [ ] **Step 6.11: Run full test suite**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 6.12: Commit**

```
git add backend/sentinel_core/sqlite_store.py backend/sentinel_core/persistent_service.py backend/sentinel_core/http_api.py frontend/sidebar.html tests/test_sqlite_persistence.py tests/test_http_api.py
git commit -m "feat: async backfill and evaluate via SQLite job queue

- monitor_jobs table: job_id, kind, params, status, progress counts.
- SQLiteStore: enqueue_job, get_job, dequeue_next_job, finish_job.
- Backfill and evaluate endpoints return {job: {job_id, status}} immediately.
- Background daemon thread processes queued jobs one at a time.
- GET /jobs/{id} polling endpoint for client status checks.
- frontend/sidebar.html: poll job status every 2 s; refresh on completion.

Closes finding 6 from AUDIT_FINDINGS_2026-06-23.md.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Split `http_api.py` by Route Domain

**Goal:** Extract route handler methods into focused sub-modules. No behaviour change — existing tests pass unchanged. Portfolio routes are the largest chunk and are deferred to a later pass; this task extracts the four smaller domains.

**Files:**
- Create: `backend/sentinel_core/api_market_data.py`
- Create: `backend/sentinel_core/api_alerts.py`
- Create: `backend/sentinel_core/api_notifications.py`
- Create: `backend/sentinel_core/api_jobs.py`
- Modify: `backend/sentinel_core/http_api.py`

**Contract:** Each sub-module is a plain Python module containing handler functions. `SentinelApi` in `http_api.py` keeps the route dispatcher and shared helpers (`_parse_uuid`, `ApiError`, etc.) and delegates to sub-module functions.

Because this is a purely structural change, write NO new tests. Run the existing test suite as the regression check at each step.

- [ ] **Step 7.1: Run baseline to record the passing count**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests 2>&1 | tail -5
```

Record the output (e.g., `Ran 185 tests in ...s OK`). This is your target — every step must produce the same count.

- [ ] **Step 7.2: Create `backend/sentinel_core/api_jobs.py`**

Read the `get_job` handling block in `http_api.py` (added in Task 6). Create a new file:

```python
# backend/sentinel_core/api_jobs.py
"""Job queue polling handlers."""
from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from .http_api import ApiError, _parse_uuid


def handle_get_job(job_id_str: str, workspace) -> tuple:
    job_id = _parse_uuid(job_id_str, "job_id")
    job = workspace.store.get_job(job_id)
    if job is None:
        raise ApiError(HTTPStatus.NOT_FOUND, "Job not found: %s" % job_id)
    return HTTPStatus.OK, {"job": job}
```

Then update the `handle()` dispatcher in `http_api.py` — replace the inline job handling block with a delegation:

```python
        match = re.fullmatch(r"/jobs/([^/]+)", path)
        if method == "GET" and match:
            from .api_jobs import handle_get_job
            return handle_get_job(match.group(1), self.workspace)
```

- [ ] **Step 7.3: Run full suite to confirm no regressions**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: same count as Step 7.1, all passing.

- [ ] **Step 7.4: Create `backend/sentinel_core/api_alerts.py`**

Move the `acknowledge`, `list_alerts`, `list_alert_events`, `maintenance_scorecard` handler logic out of `SentinelApi` methods into standalone functions:

```python
# backend/sentinel_core/api_alerts.py
"""Alert management handlers."""
from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from .scorecard import stale_exit_events


def handle_list_alerts(portfolio_id: UUID, workspace) -> tuple:
    return HTTPStatus.OK, {"alerts": workspace.list_alerts(portfolio_id=portfolio_id)}


def handle_list_alert_events(portfolio_id: UUID, ticker: str | None, workspace) -> tuple:
    return HTTPStatus.OK, {
        "events": workspace.store.list_alert_events(portfolio_id, ticker=ticker)
    }


def handle_acknowledge(portfolio_id: UUID, alert_id: UUID, body: dict, workspace) -> tuple:
    return HTTPStatus.OK, workspace.acknowledge_alert_api(
        portfolio_id=portfolio_id, alert_id=alert_id, body=body
    )


def handle_maintenance_scorecard(portfolio_id: UUID, workspace) -> tuple:
    open_exit_alerts = [
        a for a in workspace.store.list_alerts(portfolio_id)
        if a.status in {"new", "sent"} and a.result.kind == "exit"
    ]
    events = stale_exit_events(open_exit_alerts)
    deferred_written = 0
    missed_written = 0
    for event in events:
        written = workspace.store.save_scorecard_event_if_not_exists(event)
        if written:
            if event.kind == "deferred":
                deferred_written += 1
            elif event.kind == "missed":
                missed_written += 1
    return HTTPStatus.OK, {"deferred_written": deferred_written, "missed_written": missed_written}
```

> Note: `workspace.acknowledge_alert_api` does not exist yet — you will need to keep the acknowledge logic in `SentinelApi.acknowledge` and call it from the dispatcher, OR move it into a workspace method. The simplest approach: keep `SentinelApi.acknowledge()` as-is and just have the dispatcher call it. Only move code that doesn't need `self` (the `SentinelApi` instance).

For the dispatcher in `http_api.py`, update the alert-related blocks:
```python
        match = re.fullmatch(r"/portfolios/([^/]+)/alerts", path)
        if method == "GET" and match:
            from .api_alerts import handle_list_alerts
            return handle_list_alerts(_parse_uuid(match.group(1), "portfolio_id"), self.workspace)

        match = re.fullmatch(r"/portfolios/([^/]+)/alert-events", path)
        if method == "GET" and match:
            from .api_alerts import handle_list_alert_events
            portfolio_id = _parse_uuid(match.group(1), "portfolio_id")
            ticker = query.get("ticker", [""])[0].strip().upper() or None
            return handle_list_alert_events(portfolio_id, ticker, self.workspace)

        match = re.fullmatch(r"/portfolios/([^/]+)/maintenance/scorecard", path)
        if method == "POST" and match:
            from .api_alerts import handle_maintenance_scorecard
            return handle_maintenance_scorecard(_parse_uuid(match.group(1), "portfolio_id"), self.workspace)

        match = re.fullmatch(r"/portfolios/([^/]+)/alerts/([^/]+)/ack", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.acknowledge(
                _parse_uuid(match.group(1), "portfolio_id"),
                _parse_uuid(match.group(2), "alert_id"),
                body,
            )
```

- [ ] **Step 7.5: Run full suite**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: same count, all passing.

- [ ] **Step 7.6: Create `backend/sentinel_core/api_notifications.py`**

```python
# backend/sentinel_core/api_notifications.py
"""Notification settings and delivery handlers."""
from __future__ import annotations

from http import HTTPStatus
from uuid import UUID


def handle_get_notification_settings(portfolio_id: UUID, workspace) -> tuple:
    return HTTPStatus.OK, {
        "settings": workspace.store.get_notification_settings(portfolio_id),
        "delivery_status": {
            "email_configured": workspace.email_provider is not None,
            "telegram_configured": workspace.telegram_provider is not None,
        },
    }


def handle_save_notification_settings(portfolio_id: UUID, body: dict, workspace) -> tuple:
    settings = workspace.store.save_notification_settings(
        portfolio_id,
        email_enabled=bool(body.get("email_enabled")),
        email_recipients=body.get("email_recipients") or (),
        telegram_enabled=bool(body.get("telegram_enabled")),
        telegram_chat_id=str(body.get("telegram_chat_id") or "").strip(),
    )
    return HTTPStatus.OK, {
        "settings": settings,
        "delivery_status": {
            "email_configured": workspace.email_provider is not None,
            "telegram_configured": workspace.telegram_provider is not None,
        },
    }


def handle_list_notifications(portfolio_id: UUID, workspace) -> tuple:
    return HTTPStatus.OK, {
        "notifications": workspace.list_notifications(portfolio_id=portfolio_id)
    }
```

Update the dispatcher in `http_api.py` to delegate to these functions (keep `test_notification_settings` in `SentinelApi` as it's complex):

```python
        match = re.fullmatch(r"/portfolios/([^/]+)/notification-settings", path)
        if method == "GET" and match:
            from .api_notifications import handle_get_notification_settings
            return handle_get_notification_settings(_parse_uuid(match.group(1), "portfolio_id"), self.workspace)
        if method == "POST" and match:
            from .api_notifications import handle_save_notification_settings
            return handle_save_notification_settings(_parse_uuid(match.group(1), "portfolio_id"), body, self.workspace)

        match = re.fullmatch(r"/portfolios/([^/]+)/notifications", path)
        if method == "GET" and match:
            from .api_notifications import handle_list_notifications
            return handle_list_notifications(_parse_uuid(match.group(1), "portfolio_id"), self.workspace)
```

- [ ] **Step 7.7: Run full suite**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: same count, all passing.

- [ ] **Step 7.8: Create `backend/sentinel_core/api_market_data.py`**

```python
# backend/sentinel_core/api_market_data.py
"""Market data backfill handlers (enqueue jobs)."""
from __future__ import annotations

from datetime import date
from http import HTTPStatus
from uuid import UUID


def handle_backfill_massive(portfolio_id: UUID, body: dict, workspace, store) -> tuple:
    import os
    from .http_api import _parse_limited_int, _parse_iso_date
    api_key = body.get("api_key") or os.environ.get("MASSIVE_API_KEY") or ""
    lookback = _parse_limited_int(body.get("lookback"), "lookback", default=250, minimum=10, maximum=500)
    end = _parse_iso_date(body.get("end"), "end")
    job = store.enqueue_job(
        portfolio_id,
        kind="backfill_massive",
        params={"api_key": api_key, "lookback": lookback, "end": end.isoformat()},
    )
    return HTTPStatus.OK, {"job": job}


def handle_backfill_online(portfolio_id: UUID, body: dict, store) -> tuple:
    from .http_api import _parse_limited_int, _parse_iso_date
    lookback = _parse_limited_int(body.get("lookback"), "lookback", default=250, minimum=10, maximum=500)
    end = _parse_iso_date(body.get("end"), "end")
    job = store.enqueue_job(
        portfolio_id,
        kind="backfill_online",
        params={"lookback": lookback, "end": end.isoformat()},
    )
    return HTTPStatus.OK, {"job": job}


def handle_evaluate(portfolio_id: UUID, body: dict, store) -> tuple:
    from .http_api import _parse_iso_date
    asof = _parse_iso_date(body.get("asof"), "asof")
    job = store.enqueue_job(
        portfolio_id,
        kind="evaluate",
        params={"asof": asof.isoformat()},
    )
    return HTTPStatus.OK, {"job": job}
```

Update dispatcher:
```python
        match = re.fullmatch(r"/portfolios/([^/]+)/backfill-online", path)
        if method == "POST" and match:
            from .api_market_data import handle_backfill_online
            return handle_backfill_online(_parse_uuid(match.group(1), "portfolio_id"), body, self.workspace.store)

        match = re.fullmatch(r"/portfolios/([^/]+)/backfill-massive", path)
        if method == "POST" and match:
            from .api_market_data import handle_backfill_massive
            return handle_backfill_massive(_parse_uuid(match.group(1), "portfolio_id"), body, self.workspace, self.workspace.store)

        match = re.fullmatch(r"/portfolios/([^/]+)/evaluate", path)
        if method == "POST" and match:
            from .api_market_data import handle_evaluate
            return handle_evaluate(_parse_uuid(match.group(1), "portfolio_id"), body, self.workspace.store)
```

- [ ] **Step 7.9: Run full suite**

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

Expected: same count, all passing.

- [ ] **Step 7.10: Commit**

```
git add backend/sentinel_core/api_jobs.py backend/sentinel_core/api_alerts.py backend/sentinel_core/api_notifications.py backend/sentinel_core/api_market_data.py backend/sentinel_core/http_api.py
git commit -m "refactor: split http_api.py route handlers into focused sub-modules

No behaviour change — existing tests unchanged.

- api_jobs.py: GET /jobs/{id} polling
- api_alerts.py: alert list, events, ack, maintenance/scorecard
- api_notifications.py: notification settings and list
- api_market_data.py: backfill and evaluate job-enqueue handlers
- http_api.py: now the dispatcher + shared helpers + static serving

Closes finding 7 from AUDIT_FINDINGS_2026-06-23.md.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] Run full test suite one last time:

```
$env:PYTHONPATH="backend;."
python -m unittest discover -s tests
```

- [ ] Run upload package validation:

```
python scripts/validate_upload_package.py
```

- [ ] Confirm git log shows 7 new commits on `main`.

```
git log --oneline -10
```

- [ ] Push to GitHub:

```
git push origin main
```
