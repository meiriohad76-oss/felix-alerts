# Sentinel V2 Audit And Product Plan Design

Date: 2026-05-19

Status: Approved for execution by user request on 2026-05-19.

## Goal

Create a disciplined V2 path for Sentinel that fixes reliability, data integrity, alert explainability, and novice-user UX. V2 must turn the current working prototype into a product where a non-expert user can answer four questions quickly:

1. Is there an action now?
2. Why?
3. What should I do?
4. Is this stock protected?

## Constraints

- Do not overwrite the legacy `frontend/index.html`.
- Continue using `frontend/sidebar.html` as the active parallel app version.
- Avoid demo/sample portfolio data in the user-facing app and tests.
- Massive API is the intended primary data source, but failures must be explicit and auditable.
- Current local development stack remains Python standard-library HTTP server, SQLite, and vanilla frontend until a separate migration decision is made.
- All changes need automated tests where feasible.

## Architecture Direction

V2 should reduce frontend-owned decision logic and move durable decisions into backend contracts.

Current frontend responsibilities that should become backend-owned:

- Portfolio row urgency/rank scores.
- Run receipts and latest monitor status.
- Setup-data lifecycle resolution.
- Alert lifecycle events.
- Market data freshness and provider status.

Current frontend responsibilities that remain frontend-owned:

- Layout, route display, filtering, and interaction state.
- Chart rendering and marker presentation.
- Collapsed/expanded evidence panels.
- Copy and novice-readable labels.

## Product Model

### Overview

Purpose: answer "Where am I and what needs attention?"

Displays:

- Portfolio name.
- Last successful or failed monitor run.
- Data readiness.
- Count of triggered actions, near triggers, setup tasks, and stale/missing market data.
- Top urgent holdings.
- One primary next action.

### Import And Run

Purpose: load a portfolio file, save it as a portfolio, fetch market data, and evaluate alerts.

Displays:

- Step-by-step file selection and portfolio naming.
- File preview with detected tickers.
- Massive key/status.
- Primary "Save Portfolio And Run Monitor" action.
- Durable run receipt.
- Collapsed import details.

### Holdings

Purpose: scan all portfolio stocks and choose what to inspect.

Displays:

- Backend-ranked ticker list.
- Gauges for health, urgency, exit pressure, bearish pressure, setup/data readiness, and buy-signal readiness.
- Plain-English reason for each row's priority.
- Setup input where required.
- Open stock detail action.

### Alert Queue

Purpose: triage active actions and near-trigger watches.

Displays:

- Triggered now.
- Near trigger.
- Setup/data tasks.
- Passive/background watches.
- Each row shows rule meaning, current value vs trigger, recommended action, and evidence collapsed by default.

### Stock Detail

Purpose: inspect one stock in detail.

Displays:

- Bottom-line decision panel above the chart.
- Protection state and setup edit form when needed.
- Triggered and near-trigger rules with icons/colors and simple labels.
- Chart with price, volume, SMA50, SMA150, and visible alert/watch markers.
- Evidence panels collapsed by default.
- Alert history timeline once durable events exist.

### Settings And Activity

Purpose: configuration and audit trail.

Displays:

- Massive key status.
- Notification settings.
- Latest run history.
- Import history.
- Alert event log.

## Data Contracts

### Import Contract

Broker/import files are snapshots of holdings, not authoritative records of Sentinel setup decisions.

Rules:

- New ticker: blank setup fields remain blank and create setup tasks.
- Existing ticker in merge mode: blank or omitted setup fields preserve existing values.
- Existing ticker in replace mode: ticker removal deactivates missing tickers, but blank fields for included tickers still preserve accepted setup decisions unless an explicit clear action exists.
- Numeric fields must be positive when provided.

### Run Contract

Every monitor run should eventually be server-owned.

Fields:

- `run_id`
- `portfolio_id`
- `started_at`
- `completed_at`
- `status`: success, partial, failed
- `requested_provider`
- `effective_provider`
- ticker counts
- market data success/failure counts
- alert created/refreshed/resolved counts
- errors

### Alert Event Contract

Each alert should have a lifecycle stream.

Events:

- created
- refreshed
- resolved
- suppressed
- notification queued
- notification sent
- notification failed
- acknowledged
- missed

### Market Data Status Contract

Each ticker should expose:

- current usable source
- last successful provider
- last success timestamp
- last attempted provider
- last attempt timestamp
- last attempt status/error
- freshness label
- stale flag

## Testing Strategy

### Unit Tests

- CSV/XLSX import preservation.
- Numeric validation.
- Alert lifecycle transitions.
- Backend score generation.
- Market data status normalization.

### API Integration Tests

- Portfolio import/evaluate.
- Setup-data save and immediate alert resolution.
- Server-owned monitor run receipt.
- Massive failure and fallback matrix.
- Invalid input validation.

### Frontend Static Tests

- Non-overwrite guarantee for `frontend/index.html`.
- Sidebar display routes.
- Critical UI copy for setup, Massive status, and next action.

### Browser Or DOM Tests

- Saved portfolio selected with empty editor shows portfolio-oriented next action.
- Missing stop setup panel remains visible until saved, then disappears after response refresh.
- Chart renders bars, SMA lines, and non-overlapping marker lanes.
- Tooltip text uses readable sizes.
- Route from holdings to stock detail opens the chart without long scrolling.

## V2 Acceptance Criteria

V2 is acceptable when:

- A user can import a broker file, save the portfolio, run the monitor, and see a durable receipt.
- The app clearly says which portfolio is loaded.
- Every stock row has a ranked reason, not repeated generic scores.
- A stock detail page answers action, reason, recommended action, and protection status above the chart.
- Saving a recommended stop removes the missing-stop task immediately and does not regress after re-import.
- Massive failures are explicit and distinguishable from stale stored data.
- Triggered alerts have durable history and plain-English explanations.
- Tests cover the critical flows that previously regressed.

