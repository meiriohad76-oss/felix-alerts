# Sentinel Implementation Plan

This plan turns the methodology, product spec, UX review, and new multi-portfolio CSV requirement into an executable build sequence.

The most important product interpretation:

CSV import creates portfolio tickers and alert subscriptions. An alert is created only when a subscribed rule triggers or when a rule state is already active. This avoids filling the app with fake "alerts" while still ensuring every ticker is monitored by the full applicable playbook.

## Mission

Build Sentinel as a methodology-enforced portfolio monitor that:

1. Supports multiple user portfolios.
2. Imports each portfolio from CSV.
3. Automatically inserts tickers into the correct portfolio.
4. Automatically attaches the complete applicable Felix playbook alert set to each ticker.
5. Evaluates alerts daily from market data.
6. Explains every triggered alert in plain language:
   - What triggered.
   - Which rule it relates to.
   - What stands behind that rule from the playbook.
   - What action the user should take.
7. Generates manual broker tickets where the recommended action requires an order.
8. Maintains strict auditability, repeatability, and no hidden rule overrides.

## Product Scope

### V1 In Scope

- User authentication.
- Multiple portfolios per user.
- CSV upload per portfolio.
- Ticker-only CSV support.
- Rich CSV support with optional fields: `type`, `shares`, `entry_price`, `entry_date`, `current_profit_lock`, `notes`.
- Idempotent import: re-uploading the same CSV does not duplicate tickers, subscriptions, or alerts.
- Portfolio ticker classification: Investor, Trader, Index, Unknown.
- Automatic alert subscription creation for each ticker.
- Daily EOD rule evaluation.
- Immediate post-import evaluation.
- Alert explanation engine backed by playbook rule metadata.
- Manual order tickets for sell, place stop, and modify stop actions.
- Alert acknowledgement and discipline scorecard.
- Portfolio dashboard, import triage, alert detail, and Sunday report.
- Admin/beta support tools.

### V1 Out Of Scope

- Broker order execution.
- Live intraday trading.
- AI stock picking.
- Strategy backtesting.
- Options, futures, crypto, fixed income.
- Multi-currency support.
- Native mobile app.

## Clarified Requirements

### Multiple Portfolios

Each user can create any number of portfolios. A portfolio owns:

- Ticker set.
- CSV import history.
- Alert subscriptions.
- Alerts.
- Order tickets.
- Scorecard.
- Reports.

The same ticker can exist in multiple portfolios and must be evaluated independently per portfolio, because classification, holdings metadata, profit lock, and user action state can differ.

### CSV Input

Minimum accepted CSV:

```csv
ticker
AAPL
MSFT
PLUG
```

Recommended CSV:

```csv
ticker,type,shares,entry_price,entry_date,current_profit_lock,notes
AAPL,investor,25,184.20,2025-11-03,176.50,Core holding
PLUG,trader,1200,14.22,2025-08-11,,Growth basket
VOO,index,40,438.10,2024-01-08,,Long horizon
```

CSV import modes:

| Mode | Behavior |
|---|---|
| Merge | Upsert rows from CSV and keep portfolio tickers missing from the file. Default mode. |
| Replace | Upsert rows from CSV and mark missing existing tickers as inactive after confirmation. |

### Complete Playbook Alerts

"Insert complete playbook alerts" means:

- Create alert subscriptions for every applicable rule per ticker.
- Keep subscriptions dormant until evaluation produces a trigger or active state.
- Show setup alerts when a ticker lacks metadata required for a rule.

Example: a ticker-only row for `PLUG` creates subscriptions for C1 setup/classification and P7 distribution. After it is classified as Trader and holdings metadata is added, the app adds/activates P2, P3/T4, T1, T5, A1, A5, A6, and A8 monitoring.

### Alert Explanation

Every alert detail must include:

- Rule ID and title.
- Plain-language trigger statement.
- Evidence table.
- Playbook rationale.
- Recommended action.
- Manual order ticket when applicable.
- Acknowledgement controls.

Example:

```text
What triggered:
PLUG closed at $8.22, below its Trader exit line, the SMA-50 at $9.14.

Rule:
P2 - The 50-day Simple Moving Average exit.

Why this rule exists:
Trader positions move faster. The methodology uses the SMA-50 as the institutional support line for high-beta names. Losing that line means the position no longer meets the trend-following discipline.

Recommended action:
Sell the full PLUG position. Copy the market-sell ticket into your broker, then mark the ticket as placed.
```

## Architecture Breakdown

### Runtime Architecture

```text
                   Web App
             Next.js / React / TS
                       |
                       | HTTPS / generated API client
                       v
              FastAPI Application
                       |
       ---------------------------------
       |               |               |
   Postgres          Redis        Object Storage
       |               |               |
       v               v               v
      Data        Celery Queue      Report PDFs
                       |
                       v
                Worker Process
       ---------------------------------
       |        |        |       |     |
 CSV Import  Market   Signals Alerts Reports
             Data
```

### Backend Modules

| Module | Responsibility |
|---|---|
| `auth` | Login, sessions, user profile, admin role. |
| `portfolios` | Portfolio CRUD, portfolio ticker CRUD, inactive/archive state. |
| `csv_imports` | CSV parsing, validation, import report, merge/replace behavior. |
| `rule_catalog` | Versioned playbook rule metadata used by explanations. |
| `market_data` | EOD bars, symbol validation, caching, indicator inputs. |
| `indicators` | SMA, volume baselines, swing pivots, drawdown helpers. |
| `signals` | Pure rule evaluation. No I/O. |
| `subscriptions` | Rule subscriptions created per portfolio ticker. |
| `alerts` | Alert persistence, dedupe, lifecycle, acknowledgement. |
| `explanations` | Server-side alert explanation rendering. |
| `order_tickets` | Alert-to-ticket conversion. |
| `scorecard` | Discipline metrics per portfolio and user. |
| `reports` | Sunday report generation and PDF storage. |
| `notifications` | Email/push/SMS delivery. |
| `admin` | Invites, reruns, import diagnostics, beta support. |
| `audit` | Immutable event trail for imports, evaluations, alerts, acknowledgements. |

### Frontend Areas

| Area | Responsibility |
|---|---|
| App shell | Navigation, portfolio switcher, disclaimer, account menu. |
| Portfolio list | Create/select/archive portfolios. |
| CSV import | Upload, map columns, preview, validate, import report. |
| Import triage | Shows missing metadata and current rule states after upload. |
| Portfolio dashboard | Tickers, health, open alerts, distance to exit. |
| Alert inbox | Filter by portfolio, severity, rule, status. |
| Alert detail | Explanation, evidence, action ticket, acknowledgement. |
| Rule reference | Read-only playbook rule catalog summaries. |
| Scorecard | Compliance metrics and missed/deferred actions. |
| Reports | Sunday report list and detail/PDF view. |
| Admin | Invites, reruns, import/event inspection. |

### Data Model

Core tables:

```text
users
portfolios
portfolio_tickers
csv_imports
csv_import_rows
playbook_rules
alert_subscriptions
bars
indicator_cache
swing_pivots
signal_runs
alerts
alert_explanations
order_tickets
acknowledgements
scorecard_events
reports
notification_log
audit_log
```

Key constraints:

- `portfolio_tickers`: unique `(portfolio_id, ticker)`.
- `alert_subscriptions`: unique `(portfolio_id, ticker, rule_id)`.
- `alerts`: partial unique index for open dedupe by `(portfolio_id, ticker, rule_id, kind, dedupe_key)`.
- `bars`: primary key `(ticker, date)`.
- `playbook_rules`: unique `(rule_id, version)`.

### Data Flow: CSV Import

```text
User uploads CSV
  -> parse file
  -> validate columns
  -> normalize tickers
  -> validate symbols
  -> create csv_import record
  -> upsert portfolio_tickers
  -> classify missing types when possible
  -> create alert subscriptions
  -> enqueue market-data backfill
  -> run immediate evaluation
  -> create setup/triggered alerts
  -> return import report and triage view
```

### Data Flow: Daily Evaluation

```text
Nightly after US close
  -> refresh bars for all active portfolio tickers
  -> compute indicators
  -> load active subscriptions
  -> evaluate each portfolio ticker
  -> create RuleResult objects
  -> dedupe and persist alerts
  -> render alert explanations
  -> create tickets when applicable
  -> notify user
  -> write signal_run and audit records
```

## Delivery Milestones

| Milestone | Outcome |
|---|---|
| M0 Foundation | Repo, app skeleton, CI, DB migrations, auth shell. |
| M1 Portfolio CSV | Multiple portfolios and idempotent CSV import work end to end. |
| M2 Rule Catalog | Playbook rule metadata and explanation rendering are available. |
| M3 Market Data | Symbol validation, bars, indicators, and cache are available. |
| M4 Signal Engine | Core playbook rules evaluate deterministically with golden fixtures. |
| M5 Alerts & Tickets | Subscriptions, alerts, explanations, tickets, and acknowledgements work. |
| M6 Product UI | Portfolio dashboard, import triage, alert inbox/detail, scorecard. |
| M7 Reports & Notifications | Sunday report and alert emails are delivered. |
| M8 Launch Hardening | Security, observability, legal copy, beta runbook, performance. |

## Mission Tickets

### M0-01 Repository And Tooling Foundation

Goal: Create the monorepo structure and baseline developer workflow.

Work:

- Create `backend/`, `frontend/`, `docs/`, `fixtures/`, and `scripts/`.
- Configure Python tooling: `ruff`, `mypy` or `pyright`, `pytest`.
- Configure frontend tooling: TypeScript, ESLint, formatting, test runner.
- Add CI pipeline for lint, type check, tests, build.

Definition of Done:

- A fresh clone can install dependencies and run backend/frontend checks.
- CI passes on an empty baseline.
- README documents local setup.

Testing:

- Run backend lint/type/test commands.
- Run frontend lint/type/build commands.
- CI dry run or local equivalent succeeds.

### M0-02 Application Configuration

Goal: Standardize environment configuration for local, staging, and production.

Work:

- Define typed settings for API, worker, database, Redis, object storage, market data, email.
- Add `.env.example` with no real secrets.
- Add configuration validation at app startup.

Definition of Done:

- Missing required config fails fast with clear errors.
- Local dev config runs without production services when mocks are enabled.

Testing:

- Unit tests for config parsing.
- Startup test with valid config.
- Startup test with missing required values.

### M0-03 Database Schema Baseline

Goal: Add migration system and initial schema.

Work:

- Add Alembic migrations.
- Create base tables: users, portfolios, portfolio_tickers, csv_imports, playbook_rules, alert_subscriptions, bars, alerts, order_tickets, audit_log.
- Add constraints and indexes for idempotency.

Definition of Done:

- Migrations apply from empty database.
- Migrations roll forward in CI.
- Uniqueness constraints prevent duplicate portfolio tickers and duplicate subscriptions.

Testing:

- Migration test against disposable Postgres.
- Constraint tests for duplicate `(portfolio_id, ticker)`.
- Constraint tests for duplicate `(portfolio_id, ticker, rule_id)`.

### M0-04 Auth And User Shell

Goal: Support beta users and admin users.

Work:

- Implement magic-link or simple beta auth.
- Add user profile and role model.
- Add authenticated API dependency.
- Add frontend protected route shell.

Definition of Done:

- User can sign in and access protected routes.
- Admin role can access admin routes.
- Unauthenticated requests are rejected.

Testing:

- API auth tests for authenticated and unauthenticated requests.
- Role-gating tests.
- Frontend route protection test.

### M1-01 Portfolio CRUD

Goal: Let users manage multiple portfolios.

Work:

- API endpoints: create, list, get, rename, archive portfolio.
- Frontend portfolio switcher.
- Portfolio-level empty state.

Definition of Done:

- A user can create multiple portfolios.
- Portfolio selection scopes all dashboard and alert views.
- Archived portfolios stop scheduled evaluations.

Testing:

- API CRUD tests.
- Authorization tests proving users cannot access other users' portfolios.
- Frontend test for portfolio switcher state.

### M1-02 CSV Schema Detection And Parsing

Goal: Accept ticker-only and rich portfolio CSV files.

Work:

- Implement CSV parser.
- Detect required and optional columns.
- Normalize headers and ticker values.
- Produce row-level parse errors.

Definition of Done:

- Minimum `ticker` CSV parses.
- Recommended schema parses.
- Invalid rows are rejected without rejecting the entire file unless all rows fail.

Testing:

- Unit tests for ticker-only CSV.
- Unit tests for rich CSV.
- Unit tests for duplicate tickers, blank tickers, malformed dates, malformed decimals.

### M1-03 CSV Import Preview

Goal: Show users what will happen before committing an import.

Work:

- API endpoint for dry-run import.
- Frontend upload and preview screen.
- Display created, updated, unchanged, invalid rows.
- Display merge vs replace choice.

Definition of Done:

- User sees row-level import preview.
- User can cancel before database writes.
- Preview uses the same parser as real import.

Testing:

- API dry-run does not mutate database.
- Frontend test for preview counts.
- Snapshot test for invalid-row messaging.

### M1-04 CSV Import Commit

Goal: Upsert portfolio tickers from CSV and write import history.

Work:

- Persist `csv_imports` and `csv_import_rows`.
- Upsert `portfolio_tickers`.
- Support merge and replace.
- Return import report.

Definition of Done:

- Import creates portfolio tickers.
- Re-upload updates existing rows without duplicates.
- Replace mode marks missing tickers inactive after confirmation.

Testing:

- Integration test for first import.
- Integration test for re-upload idempotency.
- Integration test for replace behavior.

### M1-05 Import Triage Setup Alerts

Goal: Surface missing metadata after import.

Work:

- Detect missing type, shares, entry price, and profit lock.
- Create setup alerts or setup tasks.
- Show triage screen after import.

Definition of Done:

- Ticker-only CSV creates tickers and setup prompts.
- Rich CSV with full metadata avoids unnecessary setup prompts.
- Setup prompts link to exact fields needed.

Testing:

- Fixture: ticker-only import creates C1/setup alert.
- Fixture: rich import does not create missing metadata alert.
- Frontend test for triage rendering.

### M2-01 Playbook Rule Catalog

Goal: Store the rule metadata used for alert explanations.

Work:

- Create seed data for C1, P1-P7, T1-T6, A1-A8.
- Include title, pillar, short summary, rationale, trigger template, action template, source section.
- Add version field.

Definition of Done:

- Rule catalog is loaded in local and test environments.
- Each supported rule result maps to exactly one catalog entry.
- Catalog text is concise and UI-safe.

Testing:

- Seed test checks required rule IDs exist.
- Schema test checks no empty title/rationale/action template.
- Mapping test checks every signal rule ID has metadata.

### M2-02 Alert Explanation Renderer

Goal: Generate user-facing explanations from rule metadata and evidence.

Work:

- Implement explanation renderer.
- Support templates for exit, distribution, raise lock, setup violation, gate blocker.
- Persist rendered explanation with alert.

Definition of Done:

- Every alert has `what_triggered`, `rule_rationale`, `evidence`, and `recommended_action`.
- Email, dashboard, and reports read the same explanation payload.

Testing:

- Unit tests for P1, P2, P7, T4, T5 explanation rendering.
- Snapshot tests for explanation text.
- Test missing metadata fails gracefully with internal error, not user-visible blank content.

### M2-03 Rule Reference API

Goal: Let the frontend show playbook rule summaries.

Work:

- Add endpoint to list rules.
- Add endpoint to get rule by ID.
- Add frontend read-only rule reference view.

Definition of Done:

- Users can inspect rule summaries without editing them.
- Alert detail links to relevant rule reference.

Testing:

- API tests for rule list/detail.
- Frontend test for alert-to-rule link.

### M3-01 Market Data Port

Goal: Define a vendor-independent market data interface.

Work:

- Define `MarketDataPort`.
- Add mock provider for tests.
- Add symbol validation method.
- Add bars backfill method.

Definition of Done:

- Signals and CSV import depend on the port, not vendor SDKs.
- Tests can run fully offline.

Testing:

- Unit tests for port contract.
- Mock provider integration test.

### M3-02 Market Data Vendor Client

Goal: Fetch and cache EOD bars.

Work:

- Implement selected vendor client behind `MarketDataPort`.
- Cache bars in Postgres.
- Handle rate limits and retries.
- Store vendor error diagnostics.

Definition of Done:

- Backfill works for imported tickers.
- Repeated evaluations use cached bars.
- Vendor failures create actionable diagnostics.

Testing:

- HTTP mock tests for success, 404 symbol, rate limit, transient failure.
- Cache hit/miss integration tests.

### M3-03 Indicator Computation

Goal: Compute SMA, volume baseline, swing pivots, and drawdown.

Work:

- Implement SMA-50 and SMA-150.
- Implement volume SMA-50.
- Implement swing-low detection.
- Implement drawdown helper.
- Persist indicator cache where useful.

Definition of Done:

- Indicator outputs are deterministic.
- Insufficient data returns explicit unavailable state.
- Calculations use adjusted close where required.

Testing:

- Unit tests with hand-computed small datasets.
- Golden fixture tests for SMA values.
- Edge tests for insufficient bars.

### M3-04 Market Data Backfill Worker

Goal: Automatically prepare data after CSV import.

Work:

- Queue backfill jobs for new tickers.
- Deduplicate jobs by ticker/date range.
- Record job status.

Definition of Done:

- New imported tickers become evaluable without manual action.
- Failed backfills are visible in import diagnostics.

Testing:

- Worker integration test for new ticker.
- Deduplication test.
- Retry/failure test.

### M4-01 Signal Engine Contracts

Goal: Implement pure input/output rule engine structure.

Work:

- Add `PortfolioTickerView`, `AlertSubscriptionView`, `RuleResult`.
- Add rule registry.
- Add deterministic evaluation function.

Definition of Done:

- Engine has no I/O imports.
- Engine accepts an explicit `asof`.
- Rule results include `portfolio_id`, `rule_id`, severity, kind, payload.

Testing:

- Static import boundary test.
- Unit test proving same input produces same output.
- Type tests for rule result shape.

### M4-02 P1 And P2 Exit Rules

Goal: Evaluate SMA exit rules for Investor and Trader positions.

Work:

- Implement P1 SMA-150 cross and state.
- Implement P2 SMA-50 cross and state.
- Support trigger vs onboarding/current state.

Definition of Done:

- Cross-below creates triggered exit result.
- Already-below creates state-active result for triage.
- Index positions are skipped.

Testing:

- Golden fixture `p1_cross_below_sma150`.
- Golden fixture `p1_already_below_onboarding`.
- Golden fixture `p2_cross_below_sma50`.
- Edge test for previous close already below.

### M4-03 P7 Distribution Rule

Goal: Detect high-volume down-day distribution.

Work:

- Implement `volume > 5 * volume_sma50 and close < open`.
- Support ticker-only portfolios.
- Mark as supporting evidence when exit also fires.

Definition of Done:

- Distribution alert fires without holdings metadata.
- Distribution does not generate an order ticket.
- Same-week dedupe key is available.

Testing:

- Golden fixture `p7_distribution_only`.
- Golden fixture `p7_with_exit`.
- Edge test for 4.99x volume.
- Edge test for 5x volume on up day.

### M4-04 P3 And T4 Profit-Lock Raise

Goal: Suggest monotonic profit-lock raises.

Work:

- Implement confirmed swing-low input.
- Compute candidate stop using corrected max/monotonic logic.
- Apply buffer.
- Emit raise-lock result only when stop increases.

Definition of Done:

- Profit locks never move down.
- Raise-lock result includes swing-low date, price, buffer, current and proposed stop.
- Missing current lock creates setup/protection result instead of bad math.

Testing:

- Golden fixture `t4_raise_lock`.
- Golden fixture `t4_no_lowering`.
- Unit test for buffer application.
- Property test: proposed lock is never below current lock.

### M4-05 T5 One-To-One Rule Violation

Goal: Detect excessive drawdown without an exit alert.

Work:

- Implement drawdown <= -15%.
- Suppress as primary when P1/P2 exit is already primary.
- Include missing protection context.

Definition of Done:

- T5 fires when position is down beyond threshold and no exit is open/fired.
- T5 payload includes entry, close, drawdown, exit MA, profit lock.

Testing:

- Golden fixture `t5_drawdown_no_exit`.
- Edge test at -14.99%.
- Edge test where P1/P2 exit takes priority.

### M4-06 Setup And Gate Rules

Goal: Evaluate C1, T1, P4, A5, A6, A7 setup/gate behavior.

Work:

- Missing type/classification.
- Missing entry/profit lock metadata.
- New buy below MA gate blocker.
- Size/risk gate blocker.
- Margin gate blocker.
- Index exemption.

Definition of Done:

- Ticker-only imports produce setup results, not crashes.
- New position validation is server-side.
- Index tickers skip individual-stock exit rules.

Testing:

- Golden fixture `missing_type`.
- Golden fixture `missing_profit_lock`.
- Golden fixture `gate_buy_below_ma`.
- Golden fixture `gate_size_too_large`.
- Golden fixture `gate_margin_required`.
- Golden fixture `index_exemption`.

### M4-07 Golden Fixture Harness

Goal: Make playbook behavior executable and regression-proof.

Work:

- Create fixture directory format.
- Load bars CSV, position JSON, expected result JSON.
- Add pytest parametrized harness.

Definition of Done:

- All documented golden fixtures run in one command.
- New rule changes require fixture updates.
- Failure output shows rule/payload diffs clearly.

Testing:

- The harness tests itself with one passing and one intentional failing fixture pattern.
- CI runs golden fixtures.

### M5-01 Alert Subscription Creation

Goal: Create complete applicable playbook subscriptions per portfolio ticker.

Work:

- Implement subscription matrix.
- Create subscriptions after CSV import.
- Update subscriptions when type or holdings metadata changes.
- Keep creation idempotent.

Definition of Done:

- Every imported ticker has expected subscriptions.
- Re-upload does not duplicate subscriptions.
- Changing type from unknown to trader activates trader-specific rules.

Testing:

- Golden fixture `csv_ticker_only_import`.
- Golden fixture `csv_rich_import_with_holdings`.
- Golden fixture `csv_reupload_idempotent`.
- Unit tests for subscription matrix.

### M5-02 Immediate Evaluation After Import

Goal: Evaluate newly imported tickers as soon as data is ready.

Work:

- Trigger market-data backfill after import.
- Run evaluation when backfill completes.
- Create triage alerts.

Definition of Done:

- User gets post-import triage without waiting for nightly job.
- Import report links to evaluation run.

Testing:

- Integration test import -> backfill -> evaluate -> alerts.
- Test import with market-data failure produces diagnostic instead of silent failure.

### M5-03 Nightly Evaluation Worker

Goal: Run scheduled evaluation for all active portfolio subscriptions.

Work:

- Schedule worker after US close.
- Load active portfolios and subscriptions.
- Refresh data.
- Evaluate and persist results.
- Record signal run summary.

Definition of Done:

- All active portfolios are evaluated.
- Archived portfolios are skipped.
- Signal run has counts for evaluated tickers, alerts created, failures.

Testing:

- Worker integration test with two users and multiple portfolios.
- Archived portfolio skip test.
- Partial failure test.

### M5-04 Alert Persistence And Dedupe

Goal: Persist alerts without duplicates.

Work:

- Implement dedupe keys per alert kind.
- Persist alert payload and explanation.
- Manage lifecycle: new, sent, acknowledged, resolved, expired, missed.

Definition of Done:

- Re-running evaluation does not duplicate open alerts.
- New swing-low events can create new raise-lock alerts.
- Alert status transitions are validated.

Testing:

- Dedupe test for P1 exit.
- Weekly dedupe test for P7.
- Raise-lock per-swing-low dedupe test.
- Status transition tests.

### M5-05 Order Ticket Generation

Goal: Convert actionable alerts into manual broker tickets.

Work:

- Generate sell ticket for exit alerts.
- Generate place-stop/modify-stop tickets for protection alerts.
- Split tickets by account allocation when known.
- Suppress tickets for ticker-only alerts.

Definition of Done:

- Tickets include ticker, action, quantity, order type, stop/limit when relevant, rationale rule IDs, copy text.
- V1 UI copy never implies execution.

Testing:

- Unit tests for exit ticket.
- Unit tests for modify-stop ticket.
- Test ticker-only alert creates no ticket.
- Snapshot test for copy text.

### M5-06 Acknowledgements And Scorecard Events

Goal: Track user response and discipline outcomes.

Work:

- Add ack endpoint.
- Support `placed`, `placed_with_modification`, `ignored`.
- Require notes where needed.
- Generate scorecard events for ignored, deferred, missed, missing protection.

Definition of Done:

- Acknowledgement updates alert and ticket state.
- Ignored exit creates violation event.
- Deferred/missed jobs mark stale alerts.

Testing:

- API tests for ack validation.
- Test ignored requires note.
- Test stale exit becomes deferred after 48h.
- Test open exit becomes missed after 7d.

### M6-01 Frontend App Shell

Goal: Build the main UI frame.

Work:

- Navigation.
- Portfolio switcher.
- Global disclaimer.
- Responsive layout.
- Authenticated route shell.

Definition of Done:

- User can switch portfolios.
- Every page shows required disclaimer.
- Layout works on desktop and mobile breakpoints.

Testing:

- Frontend component tests.
- Accessibility scan for nav and page landmarks.
- Responsive screenshot checks.

### M6-02 Portfolio And CSV Import UI

Goal: Let users upload and commit CSV files.

Work:

- Portfolio creation flow.
- CSV upload component.
- Preview table.
- Merge/replace selector.
- Import report.

Definition of Done:

- User can create portfolio and import ticker-only CSV.
- User can import rich CSV.
- Invalid rows are visible with clear reasons.

Testing:

- Component tests for upload states.
- E2E test for create portfolio -> upload CSV -> import report.
- E2E test for invalid row handling.

### M6-03 Import Triage UI

Goal: Show setup tasks and immediate rule states after import.

Work:

- Triage summary.
- Missing metadata cards.
- Current violations.
- Links to edit ticker metadata.

Definition of Done:

- Ticker-only imports show what data is missing.
- Full metadata imports show actual rule status.
- User can resolve missing type/profit lock from triage.

Testing:

- Component tests for setup card.
- E2E test resolve missing type.
- E2E test triage alert links to alert detail.

### M6-04 Portfolio Dashboard

Goal: Show portfolio status and monitored tickers.

Work:

- Portfolio health summary.
- Ticker table/cards.
- Open alert counts.
- Distance to exit where applicable.
- Filter by type/status/severity.

Definition of Done:

- User can see all tickers in selected portfolio.
- Open alerts are visible and prioritized.
- Ticker-only rows are clearly marked as setup-needed.

Testing:

- Component tests for table states.
- E2E test portfolio filtering.
- Visual regression for dense desktop layout.

### M6-05 Alert Inbox And Detail

Goal: Deliver the core alert experience.

Work:

- Inbox with filters.
- Alert detail page.
- Explanation sections.
- Evidence table.
- Ticket panel.
- Acknowledgement controls.

Definition of Done:

- Every alert shows what triggered, rule, rationale, evidence, recommended action.
- Tickets are copyable when present.
- Ignored/modified acknowledgements require notes.

Testing:

- Golden explanation UI snapshot for P1.
- E2E test acknowledge placed.
- E2E test ignored requires note.
- Accessibility test for alert detail.

### M6-06 Rule Reference UI

Goal: Provide transparent methodology context.

Work:

- Rule list grouped by pillar.
- Rule detail page.
- Links from alert detail.

Definition of Done:

- Users can inspect rules without editing them.
- Rule pages use catalog metadata.

Testing:

- Component tests for rule list/detail.
- Link test from alert detail to rule page.

### M6-07 Discipline Scorecard UI

Goal: Show compliance outcomes per portfolio.

Work:

- Rolling 90-day scorecard.
- Counts for ignored, deferred, missed, missing protection.
- Event list.

Definition of Done:

- Scorecard is scoped to selected portfolio and can show all-portfolios rollup.
- Events link back to source alerts.

Testing:

- API test for scorecard aggregation.
- Component test for empty and populated states.
- E2E test ignored alert appears in scorecard.

### M7-01 Notification Email Templates

Goal: Send actionable alert emails.

Work:

- Email templates for exit, distribution, raise-lock, setup violation.
- Include explanation and ticket.
- Include acknowledgement links.
- Include disclaimer.

Definition of Done:

- Emails render in common clients.
- Email text matches alert detail explanation.
- No email implies auto-execution.

Testing:

- Snapshot tests for email HTML/text.
- Integration test with email provider mock.
- Link token validation tests.

### M7-02 Sunday Report

Goal: Generate weekly portfolio reports.

Work:

- Report data aggregation.
- HTML report.
- PDF render.
- Store object.
- Link from app.

Definition of Done:

- Report includes portfolio snapshot, alerts, suggested actions, setup gaps, scorecard.
- Generated per active portfolio.
- Delivered before configured local-time SLA.

Testing:

- Unit tests for report aggregation.
- PDF render smoke test.
- E2E test report appears in UI.

### M7-03 Notification Preferences

Goal: Let users control delivery channels without changing rules.

Work:

- Preferences for email now; push and SMS channels are deferred until delivery vendors are selected.
- Per-portfolio delivery settings.
- No settings that alter rule thresholds.

Definition of Done:

- User can turn delivery channels on/off where allowed.
- Rule logic remains unchanged.

Testing:

- API tests for preferences.
- Test rule settings are not user-editable.
- Notification dispatch tests respect preferences.

### M8-01 Observability And Audit

Goal: Make imports, evaluations, and alerts debuggable.

Work:

- Structured logs.
- Sentry or error tracking.
- Signal run summaries.
- Audit events for imports, rule evaluations, alerts, tickets, acknowledgements.

Definition of Done:

- Admin can inspect why an alert did or did not fire.
- Every alert references signal run, rule version, and input hash.
- PII is not logged.

Testing:

- Audit log integration tests.
- PII redaction tests.
- Signal run traceability test.

### M8-02 Security And Privacy

Goal: Protect user portfolio data.

Work:

- Authorization checks on all portfolio-scoped endpoints.
- Encrypt sensitive tokens if any.
- Rate-limit auth and upload endpoints.
- Add data export and deletion path.

Definition of Done:

- Cross-user access is blocked.
- Uploaded CSVs are not publicly accessible.
- User can export their data.

Testing:

- Authorization tests across endpoints.
- Upload size/type validation tests.
- Data export test.

### M8-03 Performance Hardening

Goal: Keep the app responsive at beta scale.

Work:

- Query indexes.
- Batch market-data refresh.
- Paginate alert inbox.
- Cache rule catalog.
- Measure dashboard load.

Definition of Done:

- 25 users x 30 tickers evaluates within nightly budget.
- Dashboard initial load target is met for 30-position portfolio.
- CSV import returns preview quickly for typical beta files.

Testing:

- Load test for nightly evaluation.
- API performance test for dashboard endpoint.
- CSV import benchmark.

### M8-04 Admin And Support Tools

Goal: Operate the beta without database spelunking.

Work:

- Admin invite management.
- View import reports.
- Trigger market-data backfill.
- Trigger signal rerun for portfolio/date.
- View signal run diagnostics.

Definition of Done:

- Admin can support a failed import or missed alert investigation from the UI.
- Reruns are audited.

Testing:

- Admin authorization tests.
- Rerun integration test.
- Audit test for admin actions.

### M8-05 Legal And Compliance Copy Review

Goal: Reduce regulatory and expectation risk.

Work:

- Review disclaimer placement.
- Review alert/action wording.
- Draft Terms of Service and Privacy Policy.
- Confirm "manual ticket" phrasing.
- Confirm methodology attribution posture.

Definition of Done:

- Legal copy exists before beta users upload data.
- App does not claim investment advice or auto-execution.
- All emails and pages include required disclaimer.

Testing:

- Static copy scan for banned phrases: "execute all exits", "auto-trade", "Sentinel sold".
- UI tests confirming disclaimer presence.

### M8-06 End-To-End Beta Readiness Drill

Goal: Verify the complete user journey.

Work:

- Seed beta user.
- Create two portfolios.
- Import ticker-only CSV.
- Import rich CSV.
- Run backfill and evaluation.
- Trigger P1/P7/T4/T5 fixtures.
- Acknowledge tickets.
- Generate Sunday report.

Definition of Done:

- Full workflow succeeds in staging.
- Failures are documented and fixed or explicitly waived.
- Beta runbook is updated.

Testing:

- Playwright E2E for the core journey.
- API integration test for import-to-alert path.
- Manual staging checklist signed off.

## Testing Strategy

### Unit Tests

- CSV parsing and normalization.
- Indicator calculations.
- Rule evaluation.
- Explanation rendering.
- Ticket generation.
- Scorecard event logic.

### Integration Tests

- CSV import commits data correctly.
- Subscription creation is idempotent.
- Market-data cache feeds signal engine.
- Evaluation persists alerts and explanations.
- Acknowledgement changes alert/ticket/scorecard state.

### Golden Fixture Tests

Golden fixtures are the source of truth for methodology behavior. Required fixtures are listed in `docs/RULE_ENGINE_SPEC.md`.

Run on every PR:

```text
pytest tests/golden
```

### End-To-End Tests

Critical flows:

- Sign in.
- Create portfolio.
- Upload ticker-only CSV.
- Resolve setup triage.
- Upload rich CSV.
- View triggered alert explanation.
- Copy ticket.
- Mark as placed.
- View scorecard.
- Open Sunday report.

### Regression Tests

Every bug in rule behavior must add:

- A failing fixture or unit test.
- A fix.
- A regression note in the PR.

## Definition Of Done For The App

The app is v1 complete when:

1. A user can create multiple portfolios.
2. A user can upload ticker-only and rich CSV files for each portfolio.
3. The app inserts tickers automatically and idempotently.
4. The app creates complete applicable rule subscriptions for each ticker.
5. The app backfills market data and evaluates rules after import.
6. The nightly worker evaluates all active portfolios.
7. Every triggered alert has a playbook-grounded explanation.
8. Every actionable alert has the correct manual ticket or explicitly says no ticket is required.
9. Alert dedupe prevents repeated noise.
10. Acknowledgement and scorecard flows work.
11. Sunday reports are generated per portfolio.
12. Admin can inspect imports, signal runs, and alert diagnostics.
13. Required disclaimers and no-auto-execution wording are present.
14. Golden fixtures and E2E beta readiness tests pass.

## Other Required Activities

### Product Decisions

- Confirm whether ticker-only portfolios should be labeled "watch portfolios", "holding portfolios with missing metadata", or both.
- Confirm private beta CSV template.
- Confirm default behavior for missing tickers during re-upload: merge default, replace optional.
- Confirm classification defaults and how aggressive the app should be about auto-classifying.
- Confirm whether portfolio-level aggregate same-ticker positions are needed in v1.

### Methodology Decisions

- Confirm P3 buffer policy.
- Confirm broad-index ETF allowlist.
- Confirm whether ignored exit alerts count as immediate violations.
- Confirm whether P7 should alert for index tickers as informational.

### Compliance And Legal

- Terms of Service.
- Privacy Policy.
- Methodology attribution review.
- Alert/action wording review.
- Data deletion/export policy.

### Design

- Convert the early review build into app design system components.
- Replace theatrical verdict copy with evidence-led alert language.
- Add portfolio switcher and import triage states.
- Add empty, loading, failed, setup-needed, and no-alert states.
- Verify mobile alert detail and import flows.

### UX Audit Backlog

#### Mission: Stock Snapshot And Monitor Clarity Redesign

Status: Implemented in the review build on 2026-05-17; ready for user review in the next audit pass.

Problem:

- The monitor screen opens with the chart as the dominant story before the user understands the active portfolio, last run status, data freshness, or rule state.
- The last monitor run has no durable receipt showing when it ran, whether it succeeded, which portfolio it covered, which data source loaded, and what to do next.
- Background checks and subscription coverage use internal language that does not explain whether rules are active monitors, passive criteria, setup checks, risk rules, or information-only rules.
- The stock detail lacks a focused snapshot that answers what is monitored, what is actionable, what is near trigger, and what has already triggered.
- Far-away entry/profit-lock levels are currently explained as a chart-rendering artifact rather than a position-data review issue.

Goals:

- Make the first visible monitor state explain portfolio, data freshness, last run result, and next action.
- Add a focused stock snapshot above the chart with action status, primary monitors, closest watch, triggered history, and data trust.
- Use clear rule intent language: Action/Sell, Caution, Protect, Risk, Setup, Info.
- Replace "background methodology checks set" with additional monitoring rules that explain meaning and whether user action is needed.
- Replace subscription coverage with a portfolio monitoring matrix grouped by rule purpose.
- Add clean/detailed chart modes, keeping the clean mode focused on price, volume, SMA50, SMA150, and triggered markers.

Definition of done:

- A user can identify the active portfolio and last successful/failed run from the top of the monitor screen.
- A user can understand the selected stock's monitored alerts and current status before reading the chart.
- A user can distinguish primary chart watches from background monitoring rules.
- A user can understand whether any alert triggered in the past and what happened since.
- The chart has a clean/detailed mode and does not foreground far-away position levels unless relevant.
- Tests and frontend syntax checks pass.

Implementation notes:

- Added monitor receipt and stock snapshot panels above the chart.
- Persisted the last monitor receipt per portfolio in browser storage.
- Reworked subscription coverage into a portfolio monitoring matrix grouped by purpose.
- Renamed background checks to additional monitoring rules.
- Added clean/detailed chart modes and inline SMA labels.
- Verified with frontend syntax check, Python compile check, full unit suite, server smoke test, and a local screenshot.

#### Mission: Consolidated Methodology Center

Status: Implemented in the review build on 2026-05-17 after first user review showed the prior snapshot still spread rule meaning across too many panels.

Problem:

- The user still could not quickly understand which rules were watched, which alert had fired, what each rule meant, and what action was recommended.
- The open portfolio alert could appear in a separate lower panel while another ticker was selected, making the action feel disconnected from the chart and rule state.
- The chart could still become the dominant first object before the user understood the selected stock's methodology status.

Goals:

- Put the selected stock's full methodology story above the chart.
- Show the action/trigger first, then the primary price watches, then optional additional criteria.
- Consolidate watched criteria, current value, trigger value, distance, status meaning, and recommended action into one rule ledger.
- Focus the first open-alert ticker after evaluation or initial load when no ticker has been manually selected.
- Replace the large alert verdict panel with a compact portfolio action queue that routes the user to the affected ticker.

Definition of done:

- A triggered alert appears directly in the selected stock methodology center.
- The user can see the active primary watches without scrolling below the chart.
- Additional setup/risk/info rules are visible as coverage but collapsed by default.
- The chart appears immediately after the methodology center.
- The portfolio action queue is compact and links to the ticker with the open alert.
- Tests and frontend syntax checks pass.

#### Mission: Terminal-Led Action Flow Redesign

Status: Implemented in the review build on 2026-05-17 after reviewing the designer UX files and selecting the Terminal direction as the clearest fit for the monitor workflow.

Problem:

- The user still experienced the stock detail as a maze of spread-out data, even after the first methodology-center pass.
- The chart and alert explanations competed with each other instead of creating a clear order of attention.
- The portfolio action queue appeared after ticker detail, so triggered alerts were not the first operational object.
- Rule details were technically complete but too table-like and dense for a fast stock snapshot.
- Evidence and raw data were still visible too early, which diluted the main trigger, meaning, and action.

Goals:

- Adopt the Terminal design direction as the main interaction model: action queue first, selected-stock command center second, chart as evidence third.
- Move the portfolio action queue above ticker detail so the user starts with what needs attention.
- Replace the selected-stock rule ledger with focused alert cards showing alert, definition, current value, trigger value, distance, velocity, meaning, and recommended action.
- Keep setup/risk/info rules active but collapsed behind additional-monitoring details.
- Collapse chart-marker explanations and raw evidence by default.
- Make the chart legend explicit about SMA50 and SMA150 colors and keep position metadata outside the chart unless expanded.

Definition of done:

- A user can see open portfolio actions before the chart or ticker detail.
- A selected stock has a single command center that explains watched alerts and recommended actions without requiring cross-panel reading.
- Current vs trigger values are visible in each primary rule card.
- Triggered history is available in an expansion panel and includes date, rule, trigger text, and price move since trigger when available.
- Evidence JSON, chart-marker explanations, and off-scale position metadata are collapsed until requested.
- Frontend static test and full backend/frontend unit suite pass.

Testing:

- `python3 -m unittest tests.test_frontend_static`
- `PYTHONPATH=backend python3 -m unittest discover`

Follow-up from screenshot review on 2026-05-17:

- The user still saw AAPL selected while the only open portfolio action was PLUG, so evaluation now focuses the first open action ticker after refresh.
- Open alert copy now formats T5 drawdown as a human percentage instead of exposing raw decimal payloads.
- Selected-stock methodology no longer presents another ticker's alert as the selected stock's main action.
- Detailed chart mode now adds an explicit alert-context panel listing chartable watches, trigger values, current values, distance, and off-scale position levels before the chart.
- Added a regression test for human-readable T5 explanation text.
- QA found that older saved portfolios could still contain `unknown` tickers with only three setup monitors, so `Import & Run Monitor` now defaults those saved tickers to investor style and rebuilds full playbook subscriptions before loading market data.
- Follow-up UX pass separated the portfolio and stock workflows: saved stocks are now listed as `Stocks By Urgency`, the long list scrolls inside its panel, stock links open a focused stock-detail page in a new tab/window, and chart alert markers now use intent-specific symbols, colors, and tooltip explanations.
- Portfolio row gauges now summarize stock health, trigger proximity, urgency, sell pressure, bearish pressure, bullish support, and explicitly mark buy signals as not scored until buy-trigger rules are implemented.
- Notification slice implemented a local in-app notification log for newly created alert records. The monitor response now returns generated notifications, portfolio state can fetch `/portfolios/{id}/notifications`, and the frontend shows the latest local notifications for the active portfolio. External delivery channels remain a product/integration decision.
- Dev server runner now supports foreground mode plus `--daemon`, `--status`, and `--stop`, with PID/log files. This fixes the local workflow where a backgrounded server could be killed when the shell/tool session exited.
- Structural UX cleanup mission recorded on 2026-05-17 after screenshot review showed the portfolio page still mixed command, list, detail, and chart surfaces. Scope: keep portfolio overview and stock detail as separate workflows, compact the urgency list so many stocks are visible, resolve stale setup alerts after conditions are fixed, prevent setup/data alerts from becoming fake chart markers, replace overlapping chart labels with compact marker icons plus marker-strip explanations, and add chart zoom/pan controls. Detailed execution plan: `docs/superpowers/plans/2026-05-17-structural-ux-cleanup.md`.

#### Mission: Plain-English Methodology Explanations

Status: Implemented in the review build on 2026-05-17 after screenshot review showed that rule cards still exposed backend-style labels and generic status text.

Problem:

- Evidence drawers showed raw JSON without first explaining what the data meant.
- Setup alerts could read like market triggers, for example `Setup data required fired`.
- The methodology center showed chart watches and background checks as separate counts without explaining that all monitors were active.
- Rule names such as Distribution pressure and Recovery violation were not self-explanatory, and the meaning text repeated generic watch-state language instead of explaining the playbook purpose.

Goals:

- Replace generic status meaning with rule-specific plain-English explanations.
- Separate market triggers from setup/data issues in the decision ticket language.
- Explain why a profit-lock/stop value may be missing: the imported portfolio file did not include that field.
- Keep raw evidence collapsed, but show a plain-English evidence explanation before JSON when expanded.
- Clarify that price/chart watches are the chart-visible subset, while setup/risk background checks remain active below the chart.

Definition of done:

- No selected-stock ticket labels setup/data issues as `fired`.
- Evidence drawers include `Plain English` and `Raw Evidence` sections.
- The methodology center explains that all monitors are active and only price-based monitors appear on the chart.
- P1, P2, P7, T1, T4, T5, A1, A5, A6, A7, and A8 have specific user-facing meaning/action copy.
- Backend alert explanations for missing profit-lock/stop setup data use plain English, so notifications and future UI surfaces do not reuse vague setup text.

Testing:

- `PYTHONPATH=backend python3 -m unittest tests.test_explanations_tickets tests.test_frontend_static`
- `awk '/<script>/{flag=1; next} /<\/script>/{flag=0} flag {print}' frontend/index.html | node --check`
- `PYTHONPATH=backend python3 -m unittest discover -s tests`

#### Mission: Non-Trader Action Language

Status: Implemented in the review build on 2026-05-17 after the product goal was clarified: the app must be understandable by users who are not experienced traders.

Problem:

- The methodology center still used trading labels as primary labels, such as `Distribution pressure`, `Recovery violation`, and `Investor SMA150 exit`.
- The user had to understand the playbook vocabulary before understanding whether a card meant sell, caution, setup, or background context.
- Rule cards did not follow one consistent novice-readable structure.

Goals:

- Make plain-language action labels primary.
- Move technical rule names into secondary text.
- Standardize rule cards around the same questions: what is being watched, what it means now, why this matters, and what the user should do now.
- Explain market concepts inline, for example SMA150 as the average of the last 150 trading days and heavy selling as unusually high volume on a down day.

Definition of done:

- Primary labels include `Long-term trend exit`, `Heavy selling warning`, and `15% loss limit warning`.
- Technical terms are still available as `Technical rule` context, but they are not the main thing the user must parse.
- Each focused rule card includes `What is being watched`, `Why this matters`, and `What you should do now`.
- Passive watches say `No action needed right now` instead of implying missing data or malfunction.

Testing:

- `PYTHONPATH=backend python3 -m unittest tests.test_frontend_static`
- `awk '/<script>/{flag=1; next} /<\/script>/{flag=0} flag {print}' frontend/index.html | node --check`
- `PYTHONPATH=backend python3 -m unittest discover -s tests`

#### Mission: Setup Tickets Must Not Look Like Market Signals

Status: Implemented and verified on 2026-05-18. Handoff detail: `docs/UX_REVIEW_HANDOFF_2026-05-18.md`.

Problem:

- The current development portfolio has missing `current_profit_lock` for nearly every ticker, producing open `T1` and `A1` setup tickets across the list.
- The urgency/gauge UI made setup tickets feel like sell/bearish pressure, which made many stocks appear to have identical `urgency`, `sell`, and `bearish` values.
- Selected-stock detail cards were based mainly on chart alerts, so setup alerts without chart dates were not visible as actionable setup tasks in the focused rule cards.
- A user could not tell whether a row meant "sell now", "bearish warning", or "complete missing setup data".

Goals:

- Separate setup completion from market action scoring.
- Prioritize real market actions ahead of setup-only tickets in the action queue and ticker focus flow.
- Explain setup tickets as setup work, not buy/sell signals.
- Show missing setup input controls directly where the setup issue is explained.
- Clarify volume context as latest volume compared with the previous 50 loaded bars.

Definition of done:

- `T1`, `A1`, and `C1` are grouped as setup rules.
- Setup alerts do not drive sell or bearish scores.
- Portfolio queue sorting shows market actions before setup tickets.
- Setup-only cards include wording equivalent to `Setup item, not a buy or sell signal`.
- Missing setup cards include the stop/profit-lock input and save action.
- `Volume vs Normal` explains previous-50-bar average volume and the multiple versus normal.
- Static frontend checks, setup API tests, JavaScript syntax check, and full test suite pass.

Testing:

- `PYTHONPATH=backend python3 -m unittest tests.test_frontend_static`
- `PYTHONPATH=backend python3 -m unittest tests.test_http_api.HttpApiTests.test_update_ticker_setup_data_over_http`
- `python3 - <<'PY' ... extract script ... PY && node --check /tmp/felix-index-script.js`
- `PYTHONPATH=backend python3 -m unittest discover -s tests`

#### Mission: Bottom-Line Decision UX

Status: Implemented and verified on 2026-05-18.

Problem:

- The selected-stock page still required users to interpret scattered rule cards before understanding the action.
- The portfolio urgency list could make multiple stocks look identical because the gauges were shown before the actual reason.
- Passive watches, setup tickets, and market-action triggers had similar visual weight, so a novice user could not quickly tell what mattered first.

Goals:

- Put a `Bottom Line` panel above detailed rule mechanics on every stock page.
- Show `Primary reason`, `Recommended action`, and setup context before evidence or passive watches.
- Explain portfolio rows with a short primary reason such as `Focus first: market action - Long-term trend exit + 15% loss limit warning`.
- Rename trigger states away from vague system language:
  - `Triggered now` -> `Exit signal`
  - `Breach active` -> `Action required`
  - `Watching` -> `Not triggered`
- Collapse passive watches into a secondary drawer so active market actions remain the first focus.

Definition of done:

- Active market rows use bottom-line language before charts/evidence.
- Setup-only rows say setup work is needed and do not read like buy/sell signals.
- Market action rules are rendered in `triggered-rule-grid`.
- Passive and background watches are rendered in collapsed `passive-watch-list`.
- AEM, B, ERO, and AAOI explain different primary reasons even when some gauges remain high.
- Static frontend checks, JavaScript syntax check, full test suite, and local server smoke checks pass.

Testing:

- `PYTHONPATH=backend python3 -m unittest tests.test_frontend_static`
- `python3 - <<'PY' ... extract script ... PY && node --check /tmp/felix-index-script.js`
- `PYTHONPATH=backend python3 -m unittest discover -s tests`
- `PYTHONPATH=backend python3 scripts/run_dev_server.py --stop`
- `PYTHONPATH=backend python3 scripts/run_dev_server.py --daemon`
- `curl -sS http://127.0.0.1:8765/health`

### Operations

- Staging environment.
- Production environment.
- Database backups.
- Error tracking.
- Uptime monitoring.
- Worker heartbeat.
- Admin runbook.
- Beta onboarding guide.
- Support intake process.

### Data

- Select market-data vendor.
- Create API keys and quotas.
- Validate adjusted-close behavior against known references.
- Create seed rule catalog.
- Create production import templates.
- Create golden datasets.

## Recommended Build Order

1. Build repo foundation and schema.
2. Build portfolio CRUD.
3. Build CSV parser, preview, commit, and idempotency.
4. Build rule catalog and explanation renderer.
5. Build market-data port and mock provider.
6. Build signal engine with golden fixtures.
7. Build subscriptions and immediate evaluation after import.
8. Build alerts, dedupe, tickets, acknowledgement.
9. Build frontend import and triage.
10. Build alert inbox/detail.
11. Build dashboard and scorecard.
12. Build notifications and Sunday report.
13. Harden security, observability, performance, and legal copy.
14. Run beta readiness drill.
