# UX Review Handoff - 2026-05-18

## Current Review Focus

The active review item is the selected-stock alert experience and the portfolio urgency list. The user goal is that a non-experienced trader can understand:

- Which alerts/criteria are watched for each stock.
- Which items are real market action signals versus setup/data completion tasks.
- What each rule means in plain English.
- What the user should do next.
- Why a stock appears urgent.

## Root Cause Confirmed

The `Stocks By Urgency` panel previously showed many stocks with the same-looking scores because almost every ticker in the current dev portfolio is missing `current_profit_lock`.

Persisted portfolio state:

- Portfolio: `ahad2`
- Portfolio id: `cae64c03-1463-406d-8ccf-b8b3e0a8e5a3`
- Tickers: 28
- All imported tickers are currently `investor`.
- Most tickers have open setup alerts `T1` and `A1` because `current_profit_lock` is empty.
- Some tickers also have real market/action alerts, for example `P1` or `T5`.

Important interpretation:

- `T1` and `A1` missing stop/profit-lock alerts are setup completion work.
- They must not look like sell pressure, bearish pressure, or buy/sell signals.
- Real market actions such as `P1`, `P2`, `P7`, `T5`, and `T4` must be prioritized ahead of setup tickets.

## Data Explanation Confirmed

For AAOI:

- Latest loaded close: `190.36`
- Latest volume: about `8.5M`
- Previous 50-bar average volume: about `12.6M`
- The UI phrase `Volume vs Normal 8.5M / 12.6M` means latest volume versus the previous 50 loaded bars' average volume.
- That is about `0.7x normal`, so it is not a P7 heavy-selling trigger. P7 requires `5.0x normal` volume plus a down day.

## Network/Proxy Finding - 2026-05-18

Symptom:

- Monitor run stopped with `Cannot reach Massive API at api.massive.com:443 from this computer (timed out)`.

Root cause:

- Direct outbound HTTPS from this Mac failed for Massive, Polygon, Yahoo, and Google.
- macOS has auto-proxy/WPAD enabled, but `wpad` resolves to multiple internal IPs; some WPAD attempts time out.
- The app previously tried to fetch the PAC file once. If that one attempt hit a bad WPAD address, the app cached `no proxy` and tried direct HTTPS, which fails on this network.

Fix:

- `backend/sentinel_core/http_api.py` now retries PAC downloads up to 4 times and ignores empty PAC bodies before falling back to direct HTTPS.
- A regression test covers the case where PAC fetch fails twice and succeeds on the third attempt.
- Fresh proxy detection resolved `http://www-proxy-ned.oraclecorp.com:80`.
- Massive connectivity through that proxy returned no connectivity error.

Verification:

- `PYTHONPATH=backend python3 -m unittest tests.test_http_api.HttpApiTests.test_macos_proxy_detection_retries_unstable_wpad_pac`
- `PYTHONPATH=backend python3 -m unittest tests.test_http_api.HttpApiTests.test_massive_backfill_reports_connectivity_before_per_ticker_fetches`
- `PYTHONPATH=backend python3 -m unittest discover -s tests`
- Dev server restarted at `http://127.0.0.1:8765`, PID `5363`.

## Implemented So Far

Backend/API:

- Added `PersistentSentinelWorkspace.update_ticker_setup_data(...)`.
- Added `POST /portfolios/{id}/tickers/{ticker}/setup-data`.
- The endpoint validates positive numeric setup values and persists `entry_price` and/or `current_profit_lock`.
- Saving `current_profit_lock` also updates `user_exit_price`.

Frontend behavior:

- Added explicit rule groups:
  - `SETUP_RULE_IDS`
  - `SELL_RULE_IDS`
  - `BEARISH_RULE_IDS`
  - `MARKET_ACTION_RULE_IDS`
- Separated setup scoring from sell/bearish scoring.
- Added a `Setup` gauge so missing setup work has its own visible bucket.
- Replaced `N/A` buy signal language with `No buy signal yet`.
- Added setup-data inputs for missing stop/profit-lock values.
- Added setup save flow that posts to `/setup-data`, reruns evaluation, refreshes the portfolio, and reloads the selected ticker.
- Changed A1 intent from protection/sell-like display to setup display.
- Added `isSetupAlert`, `alertStatusForMonitor`, and `sortAlertsForQueue`.
- The portfolio action queue now sorts market actions before setup tickets.
- Setup queue items now say `Setup needed, not a sell signal`.
- Selected-stock rule cards now use open ticker alerts from `detail.alerts`, not only chart alerts from `detail.chart_alerts`; this makes setup alerts visible in the detailed cards even when they do not have chart dates.
- Setup rule cards now include `Setup item, not a buy or sell signal`.
- Volume wording now explicitly states that normal volume uses the previous 50 loaded bars and excludes the latest bar.

Tests added/updated:

- `tests/test_frontend_static.py`
  - setup alerts do not score as sell pressure
  - detail panels explain volume and setup input
  - setup alerts are setup status inside detail panels
  - market actions are prioritized ahead of setup tickets
- `tests/test_http_api.py`
  - setup data can be updated over HTTP

## Verification Run

Passing:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_static
```

```bash
python3 - <<'PY'
from pathlib import Path
html=Path('frontend/index.html').read_text()
start=html.index('<script>')+len('<script>')
end=html.rindex('</script>')
Path('/tmp/felix-index-script.js').write_text(html[start:end])
PY
node --check /tmp/felix-index-script.js
```

Pending:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_http_api.HttpApiTests.test_update_ticker_setup_data_over_http
PYTHONPATH=backend python3 -m unittest discover -s tests
```

Completed after initial handoff:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_http_api.HttpApiTests.test_update_ticker_setup_data_over_http
```

Result: `Ran 1 test ... OK`

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests
```

Result: `Ran 78 tests ... OK`

Live server smoke check:

- Server URL: `http://127.0.0.1:8765`
- PID after restart: `2964`
- `/health` returned `200`.
- `/` returned the app HTML.
- `/portfolios` returned portfolio `ahad2`.
- Portfolio detail returned `28` tickers and `62` open alerts.
- AAOI detail returned open setup alerts `T1` and `A1`, with `P1`, `P7`, and `T5` as non-triggered watches.

## Files Changed In This Review Pass

- `frontend/index.html`
- `tests/test_frontend_static.py`
- `tests/test_http_api.py`
- `backend/sentinel_core/http_api.py`
- `backend/sentinel_core/persistent_service.py`
- `docs/UX_REVIEW_HANDOFF_2026-05-18.md`

## Next Validation Steps

1. In the browser, validate:
   - Portfolio list no longer shows every ticker as identical sell/bearish pressure.
   - Market-action stocks appear before setup-only stocks.
   - AAOI shows setup work, not sell pressure.
   - AAOI volume reads as latest volume versus normal 50-bar volume.
   - Missing setup cards show the stop/profit-lock input.
   - A stock with real P1/T5 action shows the market action before setup tickets.

## Bottom-Line Decision UX Pass - 2026-05-18

User-reported issue:

- AEM, B, and ERO all looked like the same urgent sell case because the visible gauges led the page and the rule explanations were still scattered.
- AEM detail had better data, but it still did not lead with a plain-English bottom line or a clear primary reason.

Root cause:

- The data was not identical, but the UI made it feel identical.
- Current live data shows:
  - `AEM`: open market alert `P1`, active trigger `T5`, setup alerts `T1` and `A1`.
  - `B`: open market alert `P1`, setup alerts `T1` and `A1`.
  - `ERO`: open market alert `T5`, setup alerts `T1` and `A1`.
  - `AAOI`: setup alerts `T1` and `A1`, no active market alert.
- The row and detail pages needed to explain that difference before showing gauges, evidence, or passive watches.

Implemented:

- Added frontend decision helpers:
  - `activeDecisionRows`
  - `marketDecisionRows`
  - `setupDecisionRows`
  - `decisionSummaryForRows`
  - `rowPrimaryReason`
- Added a selected-stock `Bottom Line` panel with:
  - status: `Action required`, `Watch closely`, `Setup needed`, or `No action now`
  - `Primary reason`
  - `Recommended action`
  - setup context, including `Setup is secondary` when market action exists.
- Added portfolio-row primary reason text so rows explain the cause before gauges.
- Renamed vague state labels:
  - `Triggered now` -> `Exit signal`
  - `Breach active` -> `Action required`
  - `Watching` -> `Not triggered`
- Changed compact/detail signal label from `Sell` to `Exit` to reduce confusion with broker execution.
- Split the methodology cards:
  - active market actions and near triggers render in `triggered-rule-grid`
  - passive watches and setup/background checks render inside collapsed `passive-watch-list`.

Verification:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_static
```

Result: `Ran 8 tests ... OK`

```bash
python3 - <<'PY'
from pathlib import Path
html=Path('frontend/index.html').read_text()
start=html.index('<script>')+len('<script>')
end=html.rindex('</script>')
Path('/tmp/felix-index-script.js').write_text(html[start:end])
PY
node --check /tmp/felix-index-script.js
```

Result: exit code `0`.

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests
```

Result: `Ran 80 tests ... OK`

Server restarted:

- URL: `http://127.0.0.1:8765`
- PID: `6726`
- `/health`: `{"ok": true}`

Audit result:

- The API data confirms AEM, B, ERO, and AAOI have distinct rule causes.
- The served HTML includes the new bottom-line functions/labels and no longer includes `Breach active` or `Triggered now`.
- Browser visual inspection is still recommended with the user's current portfolio because no browser automation package is installed in this repo.

## Stock Chart Route Fix - 2026-05-18

User-reported issue:

- Stock charts looked like they were not working.

Root cause:

- Stock-detail links temporarily rendered `None selected` because the route ticker was applied after `setActivePortfolio()` cleared selected ticker state.
- Even after loading completed, the actual SVG chart was pushed too far down the stock page because stock snapshot/notification panels, overview data, KPIs, and legends rendered before the chart canvas.

Implemented:

- `setActivePortfolio()` now supports preserving a route-selected ticker.
- Stock route initialization applies `state.routeTicker` before the first portfolio render.
- Stock detail pages now render the detail/chart area before stock snapshot context panels.
- Notifications are hidden on stock detail pages.
- The chart SVG viewport now renders before KPI and legend support blocks.
- The ticker detail template now renders the chart before overview/data-warning context.

Verification:

- Static route/layout regression tests pass.
- JavaScript syntax check passes.
- Full test suite passes: `Ran 84 tests ... OK`.
- Chrome DevTools route check for AEM confirmed:
  - `hasChart: true`
  - `chartCount: 1`
  - chart SVG top moved from about `1810px` before the cleanup to about `481px`.
- Dev server is running at `http://127.0.0.1:8765`, PID `8638`, and `/health` returns `{"ok": true}`.
