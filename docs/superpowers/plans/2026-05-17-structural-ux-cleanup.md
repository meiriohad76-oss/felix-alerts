# Structural UX Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate portfolio monitoring from stock analysis so users can clearly see portfolio status, urgent stocks, and a readable stock detail chart.

**Architecture:** Keep the dependency-light Python API and static frontend. Fix stale alert state in the backend/service layer, then simplify the frontend into two page modes: portfolio overview and stock detail. Chart markers become compact point icons with explanations in a side/under-chart list instead of overlapping text labels.

**Tech Stack:** Python standard library, SQLite, static HTML/CSS/JS, `unittest`.

---

### Task 1: Stale Alert Resolution

**Files:**
- Modify: `backend/sentinel_core/persistent_service.py`
- Modify: `backend/sentinel_core/sqlite_store.py`
- Test: `tests/test_sqlite_persistence.py`
- Test: `tests/test_http_api.py`

- [ ] Add a failing test that imports `AEM` as `unknown`, evaluates to create a `C1` setup alert, classifies it as `investor`, evaluates again, and expects the old `C1` alert to be `resolved`.
- [ ] Add a store method `resolve_stale_open_alerts(portfolio_id, active_keys)` that marks open alerts not present in the current evaluation result set as `resolved`.
- [ ] Update `PersistentSentinelWorkspace.evaluate_portfolio()` to compute all currently active dedupe keys before saving new alerts, then resolve stale open alerts.
- [ ] Verify old classification alerts stop appearing once the current ticker type is `investor`.

### Task 2: Portfolio Page Structure

**Files:**
- Modify: `frontend/index.html`
- Test: `tests/test_frontend_static.py`

- [ ] Add static tests that portfolio mode hides the selected ticker detail/chart section.
- [ ] Remove inline stock detail rendering from portfolio mode.
- [ ] Keep top monitor context aligned in a 3-column grid on desktop and 1-column grid on narrow screens.
- [ ] Convert `Stocks By Urgency` rows from large cards to compact rows so at least 10 rows are visible on a normal desktop viewport.

### Task 3: Stock Detail Structure

**Files:**
- Modify: `frontend/index.html`
- Test: `tests/test_frontend_static.py`

- [ ] Make stock mode show one full-width stock detail page only.
- [ ] Put ticker summary and chart first.
- [ ] Put alert/watch explanations under the chart as grouped decision cards: triggered, near, watching, setup/data.
- [ ] Keep portfolio controls, stock list, notifications, and activity hidden in stock mode.

### Task 4: Chart Marker Collision And Zoom

**Files:**
- Modify: `frontend/index.html`
- Test: `tests/test_frontend_static.py`

- [ ] Add chart controls for zoom in, zoom out, pan left, and pan right.
- [ ] Add state for chart window start/range.
- [ ] Stop drawing large marker text labels directly on clustered chart points.
- [ ] Draw compact marker icons on the chart and put full labels/tooltips in the marker strip.
- [ ] Offset same-date marker icons vertically so icons do not overlap.

### Task 5: Verification

**Files:**
- Test: full test suite
- Verify: local HTTP server

- [ ] Run `PYTHONPATH=backend python3 -m unittest discover -s tests`.
- [ ] Run frontend script syntax check.
- [ ] Verify dev DB has 28 investor tickers and no stale `C1` alerts for investor tickers.
- [ ] Restart server and verify `/portfolios` and one stock detail endpoint.
