# Sentinel V2 Audit Findings Register

Date: 2026-05-19

Scope: current local codebase, current sidebar frontend, backend import/evaluate/persistence flow, test suite, and user-reported UX/data issues from the review cycle.

## Executive Summary

Sentinel has a working local monitor loop and passing unit tests, but it is not yet reliable enough as a novice-facing trading assistant. The main gaps are not only visual. They are also data lifecycle and observability issues:

- The frontend still computes some user-facing priority scores locally, which can create repeated values and weak explanations.
- Setup/protection data can regress or appear stale unless the backend owns more of the lifecycle.
- Import semantics are risky because broker files often omit stop data, but omitted fields should not erase setup values the user already accepted.
- Alert records are snapshots, not an event log. The app cannot yet tell a full story: what triggered, what changed, when it was resolved, and what happened afterward.
- The chart and alert display need stronger test coverage. Current frontend tests are mostly static string guards.
- Massive data status is clearer than before, but the model still needs durable run receipts and per-run/per-ticker status records.

## Findings

### F-001: Import Can Erase Accepted Setup Data

Severity: Critical

Area: backend import/data integrity

Evidence:

- `backend/sentinel_core/csv_import.py` merges existing tickers by replacing `entry_price`, `shares`, `current_profit_lock`, `user_exit_price`, `entry_date`, and `notes` directly from parsed CSV values.
- If a user accepts a recommended stop, then imports a broker/export file that omits the stop column or leaves it blank, the accepted stop can be removed.
- XLSX conversion emits an empty `current_profit_lock` column, so this is a realistic workflow risk.

User Impact:

- The app can tell the user a stock is missing protection after the user already saved protection.
- This breaks trust in the main protection workflow.

Required Fix:

- Preserve existing setup fields on merge when uploaded data omits or leaves those fields blank.
- Support explicit clearing later through a dedicated setup edit action, not through accidental blank imports.

Definition of Done:

- Re-importing ticker-only CSV preserves existing `shares`, `entry_price`, `entry_date`, `current_profit_lock`, `user_exit_price`, `type`, and `notes`.
- Re-importing XLSX-derived CSV with blank stop preserves accepted stop values for existing tickers.
- New tickers still accept blank setup fields and are marked as needing setup.

Success Criteria:

- Automated tests fail on the old behavior and pass after the fix.
- User can accept a recommended CGDV stop, re-import the same portfolio file, and no missing-stop warning returns for CGDV unless the value is explicitly removed through a setup action.

### F-002: CSV Numeric Validation Is Inconsistent

Severity: High

Area: backend import/data integrity

Evidence:

- `/setup-data` rejects non-positive `entry_price` and `current_profit_lock`.
- CSV import currently accepts zero or negative `shares`, `entry_price`, and `current_profit_lock`.
- Signal evaluation can divide by `entry_price`, so `entry_price=0` is a runtime risk.

User Impact:

- Invalid broker or edited CSV data can produce impossible calculations, confusing alerts, or server errors.

Required Fix:

- Reject non-positive numeric values during import with row-level issues.

Definition of Done:

- `shares`, `entry_price`, and `current_profit_lock` must be greater than zero when provided.
- Invalid rows are rejected with stable issue codes.
- Evaluation cannot crash because imported `entry_price` is zero.

Success Criteria:

- Tests cover zero and negative values for each numeric field.
- The import report explains which row was rejected and why.

### F-003: Saved Portfolio Next Action Can Mislead

Severity: Medium

Area: frontend workflow

Evidence:

- `renderNextAction()` checks the current editor content before considering an already-selected saved portfolio.
- A saved portfolio with tickers can still lead with "Load a portfolio file" if the editor is empty.

User Impact:

- The user does not know whether a portfolio is actually loaded or what the next useful action is.

Required Fix:

- For a selected portfolio with saved tickers, compute next action from saved state first.
- Only ask for a file when no portfolio is selected or the selected portfolio has no tickers.

Definition of Done:

- Saved portfolio with tickers and no editor rows shows a monitor/evaluate/review next action, not "Load a portfolio file."
- Empty selected portfolio still asks the user to import/load a file.

Success Criteria:

- Static or browser test guards the branching order.
- The global status always names the loaded portfolio.

### F-004: Frontend Priority Gauges Are Not Trustworthy Enough

Severity: High

Area: frontend scoring/product semantics

Evidence:

- The current holdings row score functions are frontend-only heuristics.
- Multiple stocks can still display highly similar urgency/sell/bearish values because local scoring uses broad rule buckets and open-alert counts.

User Impact:

- Users see repeated sell/urgency values and conclude either the data is wrong or every stock is equally urgent.

Required Fix:

- Move row scoring into a backend scorecard payload with explicit components: setup risk, data freshness risk, triggered action pressure, near-trigger pressure, trend state, and portfolio-level rank.
- Frontend should render backend scores and explanations, not invent the core numbers.

Definition of Done:

- Each row score includes numeric value, label, reason, and component breakdown.
- Equal scores must have visible reasons explaining why they are equal.
- Holdings sort uses backend rank.

Success Criteria:

- A portfolio with mixed tickers does not collapse into identical gauges unless the backend explanation says the same exact drivers apply.
- Tests cover a mixed alert/setup/data scenario.

### F-005: Chart Trigger Markers Can Be Suppressed Incorrectly

Severity: Medium

Area: frontend chart

Evidence:

- `renderChartSvg()` filters potential triggers if any historical alert has the same `rule_id`.
- A historical alert can hide the current watch/near-trigger marker for the same rule.

User Impact:

- The chart can omit the very criteria the user is currently watching.

Required Fix:

- Deduplicate by rule and date/status, not only by rule id.
- Keep current watch markers visible even when historical alerts exist.

Definition of Done:

- Historical alert and current near-trigger for the same rule can both appear when they refer to different dates/statuses.
- Exact duplicate marker data still deduplicates.

Success Criteria:

- Test protects against `!alertRules.has(trigger.rule_id)` suppressing current triggers.
- Browser verification shows current watch markers in clean and detailed chart modes.

### F-006: Setup-Data Save Does Not Own Alert Lifecycle

Severity: High

Area: backend alert lifecycle

Evidence:

- `/setup-data` saves fields and returns portfolio detail.
- Existing setup alerts are only resolved after later evaluation or frontend refresh choreography.

User Impact:

- The user can save a stop and still see a missing-stop ticket.

Required Fix:

- Setup-data save should immediately re-evaluate the impacted ticker or explicitly resolve setup alerts linked to saved fields.

Definition of Done:

- Saving `current_profit_lock` resolves or refreshes T1/A1 missing protection alerts in the same API response.
- Response includes a clear lifecycle receipt: saved value, affected rule ids, resolved alert ids, remaining setup tasks.

Success Criteria:

- Integration test creates missing-stop alert, saves stop, and verifies no open missing-stop alert remains in returned portfolio detail.

### F-007: Alert History Is Snapshot-Only

Severity: High

Area: backend logging/compliance/user trust

Evidence:

- Alert rows store a current status and JSON record.
- There is no durable `alert_events` table with created/resolved/sent/acknowledged/suppressed events.

User Impact:

- The app cannot explain "what happened after this alert triggered" or audit why an old warning is still visible.

Required Fix:

- Add alert lifecycle events and connect them to the UI activity stream.

Definition of Done:

- Every alert create, refresh, resolve, acknowledge, suppress, and notification attempt writes an event.
- Event rows include timestamp, ticker, rule id, event kind, actor/source, and payload.

Success Criteria:

- Stock detail can show "Triggered on date, resolved on date, price since trigger" from durable data.

### F-008: Run Receipts Are Not Durable Enough

Severity: High

Area: backend orchestration/logging

Evidence:

- The frontend stores some run receipts in browser local storage.
- Import, backfill, and evaluate are frontend-chained actions.

User Impact:

- After refresh, browser change, or failed middle step, the user cannot trust whether the latest run completed.

Required Fix:

- Introduce server-side monitor runs with per-stage and per-ticker run items.

Definition of Done:

- A single backend endpoint can orchestrate import, market data load, evaluate, and receipt creation.
- Receipts survive browser refresh and identify success, partial success, failure, provider status, ticker counts, and timestamps.

Success Criteria:

- Overview shows latest run from the database.
- Massive failure and fallback state are visible without relying on local storage.

### F-009: Massive/Fallback Status Needs A Formal Data Contract

Severity: High

Area: market data/status

Evidence:

- Market data status is global by ticker, not portfolio/run.
- A failed Massive attempt after earlier data can leave bars available but status confusing.

User Impact:

- The user cannot tell whether current results came from Massive, stale stored bars, Yahoo fallback, or no data.

Required Fix:

- Add run-level and ticker-level provider status with source, freshness, as-of date, last attempt, last success, and error.

Definition of Done:

- Each ticker has a visible market data state: current Massive, current fallback, stored but stale, failed/no bars, or not attempted.
- Monitor receipt summarizes provider success/failure counts.

Success Criteria:

- Tests cover missing key, network timeout, per-ticker failure, fallback success, and stored stale bars.

### F-010: Frontend Tests Are Mostly Static

Severity: Medium

Area: quality/testing

Evidence:

- Existing frontend tests verify string presence in `frontend/sidebar.html`.
- There is no browser-level test for import workflow, routing, setup panel persistence, chart SVG marker rendering, or tooltip readability.

User Impact:

- UX regressions can pass tests.

Required Fix:

- Add minimal browser or DOM-oriented tests for critical workflow paths.

Definition of Done:

- Tests cover import/select/run UI state, stock routing, chart marker rendering, setup panel presence, and Massive status messaging.

Success Criteria:

- A regression hiding the missing stop input or chart markers fails CI/local tests.

### F-011: HTTP Validation Is Not Strict Enough

Severity: Medium

Area: backend API contract

Evidence:

- Invalid UUIDs, invalid dates, invalid lookback values, unknown import modes, malformed JSON, and invalid acknowledgement kinds can fall into generic failures or inconsistent responses.

User Impact:

- The frontend cannot reliably explain API errors.

Required Fix:

- Harden API validation with stable 400/404 error codes and messages.

Definition of Done:

- All known invalid inputs return structured error payloads.
- No invalid request mutates portfolio, ticker, alert, notification, or scorecard data.

Success Criteria:

- Tests cover malformed input classes and assert stable response status/error.

### F-012: Monolithic Frontend Slows Safe Iteration

Severity: Medium

Area: frontend architecture

Evidence:

- `frontend/sidebar.html` is a single file with CSS, state, routing, data fetching, holdings, alert queue, stock detail, and chart logic.

User Impact:

- Fixes in one area can accidentally alter another area, especially around display state and repeated helper functions.

Required Fix:

- Split the sidebar frontend into focused modules after the current review cycle stabilizes.

Definition of Done:

- Separate files for API client, state/router, holdings display, alert queue, stock detail, chart, setup forms, and formatting helpers.
- Existing `sidebar.html` becomes a shell that imports modules.

Success Criteria:

- Unit tests can target chart marker generation and score rendering without parsing the whole HTML file.

### F-013: Routed Portfolio Is Only Honored Reliably On Stock Detail

Severity: Medium

Area: frontend routing/multi-portfolio workflow

Evidence:

- `initializeApp()` previously used `state.routePortfolioId` only for stock routes.
- Non-stock URLs such as `?view=holdings&portfolio=<id>` could load the remembered portfolio instead of the routed portfolio.

User Impact:

- In a multi-portfolio app, a user can believe they are reviewing one portfolio while the UI loads another.

Required Fix:

- Honor `portfolio` or `portfolioId` URL parameters for all displays before falling back to remembered portfolio.

Definition of Done:

- Overview, Import & Run, Holdings, Alert Queue, Playbook, and Settings URLs all activate the routed portfolio.
- Stock detail still preserves the routed ticker.

Success Criteria:

- Static regression test guards the initialization branch order.

Status:

- Implemented in the 2026-05-19 V2 foundation batch.

### F-014: Tooltip And Marker Readability Need Browser-Level Tests

Severity: Medium

Area: frontend UX/testing

Evidence:

- Static tests cannot detect clipped or unreadable tooltips.
- SVG marker tooltip content can be constrained or overlapped at narrow widths.

User Impact:

- Explanations exist technically but remain unreadable to the user.

Required Fix:

- Add browser-level hover/focus tests and adjust CSS/marker layout from measured failures.

Definition of Done:

- Tooltip text is readable at desktop and mobile widths.
- Chart marker explanations remain accessible even when markers cluster.

Success Criteria:

- Browser test fails if a tooltip is clipped outside the viewport or rendered below readable font-size thresholds.
