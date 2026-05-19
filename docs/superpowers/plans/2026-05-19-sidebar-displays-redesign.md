# Sidebar Displays Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved sidebar-driven Sentinel UX as a parallel app version without overwriting the current `frontend/index.html`.

**Architecture:** The first implementation creates `frontend/sidebar.html` as an isolated redesign entrypoint. Existing backend APIs and domain logic stay unchanged. The sidebar version reuses existing frontend render/data functions but splits the DOM into one active display at a time: Overview, Import & Run, Holdings, Alert Queue, Stock Detail, Playbook, and Settings & Activity.

**Tech Stack:** Single-file vanilla HTML/CSS/JS frontend, Python standard-library HTTP API, SQLite store, Python `unittest` static and integration tests.

---

## Non-Overwrite Rule

Do not overwrite or replace `frontend/index.html` during this plan.

Implementation target:

- Create and modify: `frontend/sidebar.html`
- Add tests that read: `frontend/sidebar.html`
- Leave existing current app: `frontend/index.html`

Cutover is explicitly out of scope for this plan. After review, a separate task can decide whether `sidebar.html` becomes `index.html`, whether both remain available, or whether a feature toggle is added.

## File Structure

- Create: `frontend/sidebar.html`  
  Parallel sidebar version of the app. It starts as a copy of `frontend/index.html` and is refactored display-by-display.

- Create: `tests/test_frontend_sidebar_static.py`  
  Static regression tests for the sidebar entrypoint, route mapping, display separation, and non-overwrite guarantees.

- Modify: no backend files expected.  
  Existing endpoints `/portfolios`, `/portfolios/<id>`, `/alerts`, `/notifications`, and `/tickers/<ticker>` should continue to be used.

- Do not modify: `frontend/index.html` during implementation tasks.  
  If an implementation worker believes a shared change is required, stop and document the reason before editing the current app.

---

## Mission Ticket 1: Preserve Current Version And Add Parallel Entrypoint

**Goal:** Create a separate `frontend/sidebar.html` that can be developed without changing the current production/test version.

**Definition of Done:**

- `frontend/sidebar.html` exists.
- `frontend/index.html` still contains the current one-screen implementation.
- The dev server can serve `http://127.0.0.1:8765/sidebar.html`.
- Tests prove that the current version still exists and the sidebar version is separate.

**Files:**

- Create: `frontend/sidebar.html`
- Create: `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Create the failing static test**

Add `tests/test_frontend_sidebar_static.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_HTML = ROOT / "frontend" / "index.html"
SIDEBAR_HTML = ROOT / "frontend" / "sidebar.html"


class FrontendSidebarStaticTests(unittest.TestCase):
    def read_current(self) -> str:
        return CURRENT_HTML.read_text()

    def read_sidebar(self) -> str:
        return SIDEBAR_HTML.read_text()

    def test_current_index_remains_available(self):
        html = self.read_current()
        self.assertIn("Portfolio Command", html)
        self.assertIn("command-deck", html)
        self.assertIn("main-board", html)
        self.assertIn("Portfolio Action Queue", html)

    def test_sidebar_entrypoint_exists_as_parallel_version(self):
        html = self.read_sidebar()
        self.assertIn("<title>Sentinel Portfolio Monitor</title>", html)
        self.assertIn("SENTINEL", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected:

```text
FileNotFoundError: ... frontend/sidebar.html
```

- [ ] **Step 3: Create the parallel file**

Run:

```bash
cp frontend/index.html frontend/sidebar.html
```

This copies the current version into a separate redesign entrypoint. Do not edit `frontend/index.html`.

- [ ] **Step 4: Run the test and verify it passes**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected:

```text
Ran 2 tests
OK
```

---

## Mission Ticket 2: Add Sidebar Display State And Route Mapping

**Goal:** Add display-level routing to `frontend/sidebar.html` while preserving stock detail route behavior.

**Definition of Done:**

- `state.activeDisplay` exists.
- `view=` route values map to the seven approved displays.
- Legacy `?view=stock&portfolio=<id>&ticker=<ticker>` opens Stock Detail.
- Unknown or missing `view=` defaults to Overview.
- Route helper functions generate display URLs.

**Files:**

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Add failing route/display tests**

Append these tests to `FrontendSidebarStaticTests`:

```python
    def test_sidebar_defines_approved_display_routes(self):
        html = self.read_sidebar()
        self.assertIn("const DISPLAY_CONFIG", html)
        for display in ["overview", "import", "holdings", "alerts", "stock", "playbook", "settings"]:
            self.assertIn(f'id: "{display}"', html)
        self.assertIn("function routeDisplayFromParams", html)
        self.assertIn('state.activeDisplay', html)
        self.assertIn('ROUTE_PARAMS.get("view")', html)

    def test_stock_route_still_preserves_selected_ticker(self):
        html = self.read_sidebar()
        self.assertIn('routeDisplayFromParams(ROUTE_PARAMS)', html)
        self.assertIn('state.selectedTicker = state.routeTicker;', html)
        self.assertIn('displayUrl("stock"', html)
        self.assertIn('tickerDetailUrl(ticker)', html)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: fails because route/display functions are not defined yet.

- [ ] **Step 3: Add display config and route mapping**

In `frontend/sidebar.html`, replace the current `INITIAL_ROUTE` block with:

```javascript
      const ROUTE_PARAMS = new URLSearchParams(window.location.search);
      const DISPLAY_CONFIG = [
        { id: "overview", label: "Overview" },
        { id: "import", label: "Import & Run" },
        { id: "holdings", label: "Holdings" },
        { id: "alerts", label: "Alert Queue" },
        { id: "stock", label: "Stock Detail" },
        { id: "playbook", label: "Playbook" },
        { id: "settings", label: "Settings & Activity" }
      ];
      const DISPLAY_IDS = new Set(DISPLAY_CONFIG.map((item) => item.id));

      function routeDisplayFromParams(params) {
        const requested = params.get("view") || "overview";
        return DISPLAY_IDS.has(requested) ? requested : "overview";
      }

      const INITIAL_ROUTE = {
        activeDisplay: routeDisplayFromParams(ROUTE_PARAMS),
        portfolioId: ROUTE_PARAMS.get("portfolio") || ROUTE_PARAMS.get("portfolioId") || "",
        ticker: (ROUTE_PARAMS.get("ticker") || "").trim().toUpperCase()
      };
```

Then update `state`:

```javascript
        activeDisplay: INITIAL_ROUTE.activeDisplay,
        pageMode: INITIAL_ROUTE.activeDisplay === "stock" ? "stock" : "portfolio",
```

Keep `routePortfolioId` and `routeTicker` as they are.

- [ ] **Step 4: Add display URL helpers**

Replace `portfolioPageUrl()` and `tickerDetailUrl(ticker)` in `frontend/sidebar.html` with:

```javascript
      function displayUrl(display, extra = {}) {
        const params = new URLSearchParams();
        params.set("view", display);
        if (state.portfolioId) {
          params.set("portfolio", state.portfolioId);
        }
        if (extra.ticker) {
          params.set("ticker", extra.ticker);
        }
        return `${window.location.pathname}?${params.toString()}`;
      }

      function portfolioPageUrl() {
        return displayUrl("overview");
      }

      function tickerDetailUrl(ticker) {
        if (!state.portfolioId || !ticker) {
          return "#";
        }
        return displayUrl("stock", { ticker });
      }
```

- [ ] **Step 5: Add display setter**

Add this function after `requirePortfolio()`:

```javascript
      function setActiveDisplay(display, { pushState = true } = {}) {
        state.activeDisplay = DISPLAY_IDS.has(display) ? display : "overview";
        state.pageMode = state.activeDisplay === "stock" ? "stock" : "portfolio";
        document.body.dataset.activeDisplay = state.activeDisplay;
        document.body.dataset.pageMode = state.pageMode;
        if (pushState) {
          window.history.pushState({}, "", displayUrl(state.activeDisplay, { ticker: state.selectedTicker }));
        }
        renderAll();
      }
```

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: all sidebar static tests pass.

---

## Mission Ticket 3: Build The App Shell And Sidebar Navigation

**Goal:** Replace the single vertical workspace in `frontend/sidebar.html` with a sidebar shell and display containers.

**Definition of Done:**

- Sidebar renders the seven approved items.
- Each display has a dedicated container with `data-display`.
- Only the active display is visible.
- The current `index.html` layout remains unchanged.

**Files:**

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Add failing shell tests**

Append:

```python
    def test_sidebar_shell_has_seven_navigation_items_and_display_containers(self):
        html = self.read_sidebar()
        self.assertIn("app-shell", html)
        self.assertIn("side-nav", html)
        for display in ["overview", "import", "holdings", "alerts", "stock", "playbook", "settings"]:
            self.assertIn(f'data-display-nav="{display}"', html)
            self.assertIn(f'data-display="{display}"', html)
        self.assertIn("function renderSidebarNav", html)
        self.assertIn("function renderActiveDisplay", html)

    def test_sidebar_css_hides_inactive_displays(self):
        html = self.read_sidebar()
        self.assertIn(".display-panel", html)
        self.assertIn(".display-panel.active", html)
        self.assertIn('body[data-active-display="stock"]', html)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: fails on missing shell/display strings.

- [ ] **Step 3: Add sidebar shell CSS**

In `frontend/sidebar.html` CSS, add:

```css
      .app-shell {
        display: grid;
        grid-template-columns: 248px minmax(0, 1fr);
        min-height: calc(100vh - 86px);
      }

      .side-nav {
        position: sticky;
        top: 0;
        align-self: start;
        min-height: calc(100vh - 86px);
        padding: 18px 14px;
        border-right: 1px solid var(--border);
        background: #0b111c;
      }

      .side-nav-title {
        display: grid;
        gap: 4px;
        margin-bottom: 18px;
      }

      .side-nav-title strong {
        color: var(--primary);
        font-size: 18px;
      }

      .side-nav-list {
        display: grid;
        gap: 8px;
      }

      .side-nav-item {
        width: 100%;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 8px;
        align-items: center;
        padding: 10px 11px;
        border: 1px solid transparent;
        border-radius: 8px;
        color: var(--muted);
        background: transparent;
        text-align: left;
      }

      .side-nav-item.active {
        color: var(--text);
        border-color: rgba(155, 188, 255, 0.45);
        background: rgba(36, 79, 159, 0.35);
      }

      .side-nav-badge {
        min-width: 24px;
        padding: 2px 6px;
        border-radius: 999px;
        background: var(--panel-2);
        color: var(--text);
        font-size: 11px;
        text-align: center;
      }

      .display-area {
        min-width: 0;
        padding: 18px;
      }

      .display-panel {
        display: none;
      }

      .display-panel.active {
        display: grid;
        gap: 16px;
      }

      .display-title {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
      }

      .display-title h2 {
        margin: 0;
        color: var(--primary);
      }

      @media (max-width: 900px) {
        .app-shell {
          grid-template-columns: 1fr;
        }

        .side-nav {
          position: static;
          min-height: auto;
          border-right: 0;
          border-bottom: 1px solid var(--border);
        }

        .side-nav-list {
          grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
        }
      }
```

- [ ] **Step 4: Replace workspace wrapper in sidebar.html only**

In `frontend/sidebar.html`, replace:

```html
      <main class="workspace">
        <div class="workspace-inner">
```

with:

```html
      <main class="app-shell">
        <nav class="side-nav" aria-label="Sentinel displays">
          <div class="side-nav-title">
            <strong>SENTINEL</strong>
            <span id="sidePortfolioLabel" class="muted">No portfolio selected</span>
          </div>
          <div id="sidebarNav" class="side-nav-list"></div>
        </nav>
        <div class="display-area">
```

Then wrap existing major sections into display panels in later tickets. For this ticket, add the container skeleton above the current sections:

```html
          <section class="display-panel" data-display="overview" id="overviewDisplay"></section>
          <section class="display-panel" data-display="import" id="importDisplay"></section>
          <section class="display-panel" data-display="holdings" id="holdingsDisplay"></section>
          <section class="display-panel" data-display="alerts" id="alertsDisplay"></section>
          <section class="display-panel" data-display="stock" id="stockDisplay"></section>
          <section class="display-panel" data-display="playbook" id="playbookDisplay"></section>
          <section class="display-panel" data-display="settings" id="settingsDisplay"></section>
```

Do not delete existing sections yet; they are moved in later tickets.

- [ ] **Step 5: Add sidebar render functions**

Add:

```javascript
      function sidebarBadge(display) {
        const summary = state.detail?.summary || {};
        if (display === "alerts" && summary.open_alert_count) {
          return String(summary.open_alert_count);
        }
        if (display === "holdings" && summary.ticker_count) {
          return String(summary.ticker_count);
        }
        if (display === "stock" && state.selectedTicker) {
          return state.selectedTicker;
        }
        if (display === "import" && state.lastRunReceipt?.status === "failed") {
          return "!";
        }
        return "";
      }

      function renderSidebarNav() {
        $("sidePortfolioLabel").textContent = state.portfolioName || "No portfolio selected";
        $("sidebarNav").innerHTML = DISPLAY_CONFIG.map((item) => {
          const active = state.activeDisplay === item.id ? " active" : "";
          const badge = sidebarBadge(item.id);
          return `
            <button class="side-nav-item${active}" data-display-nav="${item.id}">
              <span>${escapeHtml(item.label)}</span>
              ${badge ? `<span class="side-nav-badge">${escapeHtml(badge)}</span>` : ""}
            </button>
          `;
        }).join("");
        [...$("sidebarNav").querySelectorAll("[data-display-nav]")].forEach((button) => {
          button.addEventListener("click", () => setActiveDisplay(button.dataset.displayNav));
        });
      }

      function renderActiveDisplay() {
        document.body.dataset.activeDisplay = state.activeDisplay;
        [...document.querySelectorAll("[data-display]")].forEach((panel) => {
          panel.classList.toggle("active", panel.dataset.display === state.activeDisplay);
        });
      }
```

- [ ] **Step 6: Update renderAll**

In `renderAll()`, call:

```javascript
        renderSidebarNav();
        renderActiveDisplay();
```

before display-specific render calls.

- [ ] **Step 7: Run tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: all sidebar static tests pass.

---

## Mission Ticket 4: Move Existing Panels Into Dedicated Displays

**Goal:** Move existing UI blocks inside their approved display containers so the sidebar version no longer renders one endless screen.

**Definition of Done:**

- Import controls render only in Import & Run.
- Holdings table renders only in Holdings.
- Alert Queue renders only in Alert Queue.
- Ticker Detail renders only in Stock Detail.
- Rule legend and monitoring matrix render only in Playbook.
- Activity and notifications render only in Settings & Activity.

**Files:**

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Add failing display separation tests**

Append:

```python
    def test_current_panels_are_mapped_to_dedicated_displays(self):
        html = self.read_sidebar()
        self.assertIn('id="importDisplay"', html)
        self.assertIn('id="holdingsDisplay"', html)
        self.assertIn('id="alertsDisplay"', html)
        self.assertIn('id="stockDisplay"', html)
        self.assertIn('id="playbookDisplay"', html)
        self.assertIn('id="settingsDisplay"', html)
        self.assertIn("renderImportDisplay", html)
        self.assertIn("renderHoldingsDisplay", html)
        self.assertIn("renderAlertQueueDisplay", html)
        self.assertIn("renderStockDetailDisplay", html)
        self.assertIn("renderPlaybookDisplay", html)
        self.assertIn("renderSettingsDisplay", html)

    def test_sidebar_version_does_not_keep_main_board_as_primary_layout(self):
        html = self.read_sidebar()
        self.assertNotIn('<div class="main-board">', html)
        self.assertNotIn('body[data-page-mode="portfolio"] .main-board::before', html)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: fails because current markup still has `main-board` and display render wrappers do not exist.

- [ ] **Step 3: Move Import & Run markup**

Inside `#importDisplay`, move the existing `command-deck` section:

```html
          <section class="display-panel" data-display="import" id="importDisplay">
            <div class="display-title">
              <div>
                <h2>Import & Run</h2>
                <p class="muted">Load a portfolio file, fetch market data, and evaluate the playbook.</p>
              </div>
            </div>
            <section class="command-deck" aria-label="Portfolio Command">
              ...
            </section>
          </section>
```

Keep existing element IDs unchanged: `portfolioName`, `portfolioSelect`, `portfolioFile`, `runSimpleWorkflow`, `runStatus`, `csvText`, `importReport`.

- [ ] **Step 4: Move Holdings markup**

Inside `#holdingsDisplay`, move ticker table markup:

```html
          <section class="display-panel" data-display="holdings" id="holdingsDisplay">
            <div class="display-title">
              <div>
                <h2>Holdings</h2>
                <p class="muted">Action-sorted portfolio list. Open a stock to inspect chart and alerts.</p>
              </div>
              <span class="badge" id="tickerTableBadge">Not Saved</span>
            </div>
            <section class="section action-queue-section">
              <div class="section-header">
                <h3 id="tickerTableTitle">Portfolio Tickers</h3>
              </div>
              <div class="actions" id="classificationActions" style="display: none;">
                <button id="classifyUnknownInvestor">Classify Unknowns as Investor</button>
              </div>
              <div id="tickerTable"></div>
            </section>
          </section>
```

- [ ] **Step 5: Move Alert Queue markup**

Inside `#alertsDisplay`:

```html
          <section class="display-panel" data-display="alerts" id="alertsDisplay">
            <div class="display-title">
              <div>
                <h2>Alert Queue</h2>
                <p class="muted">Triggered, near-trigger, setup, and information items that need review.</p>
              </div>
              <span class="badge" id="actionQueueBadge">Open Actions</span>
            </div>
            <section class="section action-queue-section">
              <div id="alerts"></div>
            </section>
          </section>
```

- [ ] **Step 6: Move Stock Detail markup**

Inside `#stockDisplay`:

```html
          <section class="display-panel" data-display="stock" id="stockDisplay">
            <div class="display-title">
              <div>
                <h2 id="tickerDetailTitle">Stock Detail</h2>
                <p class="muted">Focused chart, watched alerts, setup tasks, and trigger history.</p>
              </div>
              <span class="badge" id="tickerDetailBadge">None Selected</span>
            </div>
            <section class="section stock-detail-section">
              <div id="tickerDetail" class="empty-state">Select a saved ticker to open its chart and alert explanations.</div>
            </section>
          </section>
```

- [ ] **Step 7: Move Playbook markup**

Inside `#playbookDisplay`:

```html
          <section class="display-panel" data-display="playbook" id="playbookDisplay">
            <div class="display-title">
              <div>
                <h2>Playbook</h2>
                <p class="muted">Rule meanings, chart symbols, monitoring coverage, and methodology reference.</p>
              </div>
            </div>
            <details id="ruleMeaningPanel" class="rule-meaning-disclosure" open>
              ...
            </details>
            <section class="section">
              <div class="section-header">
                <h3>Portfolio Monitoring Matrix</h3>
                <span class="badge" id="coverageBadge">No Portfolio</span>
              </div>
              <div id="subscriptionCoverage" class="empty-state">No subscriptions loaded.</div>
            </section>
          </section>
```

- [ ] **Step 8: Move Settings & Activity markup**

Inside `#settingsDisplay`:

```html
          <section class="display-panel" data-display="settings" id="settingsDisplay">
            <div class="display-title">
              <div>
                <h2>Settings & Activity</h2>
                <p class="muted">Operational status, notifications, run receipts, and diagnostics.</p>
              </div>
            </div>
            <section class="monitor-context" aria-label="Monitor Snapshot">
              <div id="runReceiptPanel" class="context-card"></div>
              <div id="notificationPanel" class="context-card"></div>
            </section>
            <details class="drawer-panel activity-drawer" open>
              <summary>Activity</summary>
              <pre id="activity">Ready.</pre>
            </details>
          </section>
```

- [ ] **Step 9: Remove old main-board wrapper from sidebar.html**

Delete only from `frontend/sidebar.html`:

```html
          <div class="main-board">
            ...
          </div>
```

Do not delete the moved content. Do not edit `frontend/index.html`.

- [ ] **Step 10: Add no-op display wrapper functions for static traceability**

Add:

```javascript
      function renderImportDisplay() {}
      function renderHoldingsDisplay() {}
      function renderAlertQueueDisplay() {}
      function renderStockDetailDisplay() {}
      function renderPlaybookDisplay() {}
      function renderSettingsDisplay() {}
```

Then call them in `renderAll()` after `renderActiveDisplay()`.

- [ ] **Step 11: Run tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static tests.test_frontend_static
```

Expected: both current-version and sidebar-version tests pass.

---

## Mission Ticket 5: Implement The Overview Display

**Goal:** Add a bottom-line Overview display that answers portfolio status and next action without showing the full workflow.

**Definition of Done:**

- Overview is the default display.
- Overview shows portfolio, last run, data readiness, open actions, next action, and top urgent holdings.
- Overview has clear empty states.
- Overview does not render full import controls, full chart, rule legend, or monitoring matrix.

**Files:**

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Add failing Overview tests**

Append:

```python
    def test_overview_display_has_bottom_line_summary_without_workflow_noise(self):
        html = self.read_sidebar()
        self.assertIn("function renderOverviewDisplay", html)
        self.assertIn("overviewBottomLine", html)
        self.assertIn("overviewUrgentHoldings", html)
        self.assertIn("Last Run", html)
        self.assertIn("Market Data Ready", html)
        self.assertIn("Top Urgent Holdings", html)
        overview_markup = html[html.index('id="overviewDisplay"'):]
        self.assertNotIn('id="portfolioFile"', overview_markup.split('id="importDisplay"', 1)[0])
        self.assertNotIn('id="ruleMeaningPanel"', overview_markup.split('id="importDisplay"', 1)[0])
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: fails because Overview renderer is not implemented.

- [ ] **Step 3: Add Overview markup**

Inside `#overviewDisplay`, add:

```html
            <div class="display-title">
              <div>
                <h2>Overview</h2>
                <p class="muted">Portfolio status, last run, data readiness, and the next review step.</p>
              </div>
            </div>
            <div id="overviewBottomLine"></div>
            <div id="overviewUrgentHoldings"></div>
```

- [ ] **Step 4: Add Overview CSS**

Add:

```css
      .overview-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
      }

      .overview-card {
        display: grid;
        gap: 6px;
        min-height: 92px;
        padding: 14px;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: var(--panel);
      }

      .overview-card span {
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
      }

      .overview-card strong {
        color: var(--text);
        font-size: 20px;
      }

      .overview-urgent-list {
        display: grid;
        gap: 10px;
      }
```

- [ ] **Step 5: Add Overview render function**

Add:

```javascript
      function renderOverviewDisplay() {
        const summary = state.detail?.summary || {};
        const receipt = state.lastRunReceipt;
        const tickerCount = summary.ticker_count || 0;
        const marketDataCount = summary.market_data_ticker_count || 0;
        const openAlertCount = summary.open_alert_count || 0;
        const setupCount = summary.classification_needed_count || 0;
        const lastRunLabel = receipt
          ? `${receipt.status === "success" ? "Success" : "Failed"}${receipt.created_at ? ` / ${formatValue(receipt.created_at)}` : ""}`
          : "No run recorded";
        $("overviewBottomLine").innerHTML = `
          <div class="overview-grid">
            <div class="overview-card"><span>Portfolio</span><strong>${escapeHtml(state.portfolioName || "None selected")}</strong></div>
            <div class="overview-card"><span>Last Run</span><strong>${escapeHtml(lastRunLabel)}</strong></div>
            <div class="overview-card"><span>Market Data Ready</span><strong>${marketDataCount} / ${tickerCount}</strong></div>
            <div class="overview-card"><span>Open Actions</span><strong>${openAlertCount}</strong></div>
          </div>
          <section class="section">
            <div class="section-header">
              <h3>Next Action</h3>
            </div>
            <div class="next-action" data-state="${openAlertCount ? "done" : "working"}">
              <span>Next</span>
              <div><strong>${openAlertCount ? "Review Alert Queue" : "Import & Run Monitor"}</strong><small>${openAlertCount ? "Open alerts are ready for triage." : "Load or refresh the portfolio monitor."}</small></div>
            </div>
          </section>
        `;

        const rows = sortTickerRowsByUrgency(tableRowsForCurrentContext()).slice(0, 5);
        $("overviewUrgentHoldings").innerHTML = `
          <section class="section">
            <div class="section-header">
              <h3>Top Urgent Holdings</h3>
              <a class="button-link" href="${escapeHtml(displayUrl("holdings"))}">Open Holdings</a>
            </div>
            <div class="overview-urgent-list">
              ${rows.length ? rows.map((ticker) => {
                const urgency = tickerUrgency(ticker);
                return `
                  <article class="compact-position-row ${escapeHtml(urgency.className)}">
                    <div class="row-main">
                      <a class="ticker-button" href="${escapeHtml(tickerDetailUrl(ticker.ticker))}">${escapeHtml(ticker.ticker)}</a>
                      <span class="status-pill ${escapeHtml(urgency.className)}">${escapeHtml(urgency.label)}</span>
                      ${renderRowPrimaryReason(ticker)}
                    </div>
                  </article>
                `;
              }).join("") : '<div class="empty-state">No holdings loaded yet. Open Import & Run to load a portfolio file.</div>'}
            </div>
          </section>
        `;
      }
```

Replace the earlier no-op `renderOverviewDisplay` if one was added.

- [ ] **Step 6: Update renderAll**

Call `renderOverviewDisplay()` in `renderAll()`.

- [ ] **Step 7: Run tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: all sidebar static tests pass.

---

## Mission Ticket 6: Convert Holdings And Alerts Links To Same-App Display Navigation

**Goal:** Make navigation feel like a real app: selecting a ticker moves to Stock Detail display instead of creating a hidden inline chart or relying only on a new browser tab.

**Definition of Done:**

- Holdings ticker links point to `?view=stock&portfolio=<id>&ticker=<ticker>`.
- Alert Queue “Open” links point to Stock Detail.
- The sidebar active state changes to Stock Detail when a ticker is selected.
- Existing route can still be opened in a new tab by browser behavior.

**Files:**

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Add failing navigation tests**

Append:

```python
    def test_holdings_and_alerts_route_to_stock_display(self):
        html = self.read_sidebar()
        self.assertIn('setActiveDisplay("stock"', html)
        self.assertIn('href="${escapeHtml(tickerDetailUrl(ticker.ticker))}"', html)
        self.assertIn('href="${escapeHtml(tickerDetailUrl(alert.result.ticker))}"', html)
        self.assertNotIn('target="_blank" rel="noopener">Open Details</a>', html)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: fails while links still use old target behavior.

- [ ] **Step 3: Update `selectTicker`**

In `selectTicker(ticker)`, after `state.selectedTicker = ticker;`, add:

```javascript
          setActiveDisplay("stock", { pushState: false });
          window.history.pushState({}, "", tickerDetailUrl(ticker));
```

Keep the existing loading and render calls.

- [ ] **Step 4: Remove forced new-tab target in sidebar.html**

In `renderTickerTable()`, replace:

```javascript
<a class="button-link primary open-chart" href="${escapeHtml(tickerDetailUrl(ticker.ticker))}" target="_blank" rel="noopener">Open Details</a>
```

with:

```javascript
<a class="button-link primary open-chart" href="${escapeHtml(tickerDetailUrl(ticker.ticker))}">Open Details</a>
```

In `renderAlerts()`, replace:

```javascript
<a class="button-link primary" href="${escapeHtml(tickerDetailUrl(alert.result.ticker))}" target="_blank" rel="noopener">Open ${escapeHtml(alert.result.ticker)}</a>
```

with:

```javascript
<a class="button-link primary" href="${escapeHtml(tickerDetailUrl(alert.result.ticker))}">Open ${escapeHtml(alert.result.ticker)}</a>
```

- [ ] **Step 5: Add link interception**

In the event listener setup area, add:

```javascript
      document.addEventListener("click", async (event) => {
        const link = event.target.closest("a[href]");
        if (!link || link.target || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
          return;
        }
        const url = new URL(link.href, window.location.href);
        if (url.pathname !== window.location.pathname || url.searchParams.get("view") !== "stock") {
          return;
        }
        const ticker = (url.searchParams.get("ticker") || "").trim().toUpperCase();
        if (!ticker) {
          return;
        }
        event.preventDefault();
        await selectTicker(ticker);
      });
```

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: all sidebar static tests pass.

---

## Mission Ticket 7: Improve Display-Level Empty And Error States

**Goal:** Replace silent “None selected” style failures with display-specific guidance.

**Definition of Done:**

- No portfolio state points user to Import & Run.
- No tickers state points user to file import.
- No market data state points user to run monitor.
- Missing stock route explains the ticker is not in the selected portfolio.
- API failures show clear text in the relevant display.

**Files:**

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Add failing empty-state tests**

Append:

```python
    def test_sidebar_empty_states_are_task_specific(self):
        html = self.read_sidebar()
        self.assertIn("Create or select a portfolio in Import & Run.", html)
        self.assertIn("Import a portfolio file to start monitoring.", html)
        self.assertIn("Run monitor to load market data.", html)
        self.assertIn("Ticker not found in this portfolio. Return to Holdings.", html)
        self.assertIn("displayError", html)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: fails because task-specific messages are not all present.

- [ ] **Step 3: Add display error state**

Add to `state`:

```javascript
        displayError: "",
```

Add helper:

```javascript
      function setDisplayError(message) {
        state.displayError = message || "";
      }
```

- [ ] **Step 4: Use task-specific messages**

Update empty states:

```javascript
      const EMPTY_MESSAGES = {
        noPortfolio: "Create or select a portfolio in Import & Run.",
        noTickers: "Import a portfolio file to start monitoring.",
        noMarketData: "Run monitor to load market data.",
        tickerMissing: "Ticker not found in this portfolio. Return to Holdings."
      };
```

Use these strings in `renderOverviewDisplay`, `renderTickerTable`, `renderTickerDetail`, and the `refreshPortfolioState()` ticker catch block.

- [ ] **Step 5: Update ticker catch block**

In `refreshPortfolioState()`, replace the current ticker catch behavior with:

```javascript
          } catch (error) {
            setDisplayError(EMPTY_MESSAGES.tickerMissing);
            state.tickerDetail = null;
            log(error.message);
          }
```

- [ ] **Step 6: Render display error in Stock Detail**

At the top of `renderTickerDetail()`:

```javascript
        if (state.displayError && state.activeDisplay === "stock") {
          $("tickerDetailTitle").textContent = "Stock Detail";
          $("tickerDetailBadge").textContent = "Needs Selection";
          container.className = "empty-state";
          container.innerHTML = `${escapeHtml(state.displayError)} <a class="button-link" href="${escapeHtml(displayUrl("holdings"))}">Return to Holdings</a>`;
          return;
        }
```

- [ ] **Step 7: Clear display error on successful ticker selection**

In `selectTicker(ticker)`, before fetching detail:

```javascript
          setDisplayError("");
```

- [ ] **Step 8: Run tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: all sidebar static tests pass.

---

## Mission Ticket 8: Responsive QA And Visual Polish Pass

**Goal:** Ensure the sidebar version is usable on desktop and mobile widths and avoids the previous misalignment/crowding problems.

**Definition of Done:**

- Desktop uses sidebar plus content.
- Mobile stacks navigation above content.
- Stock chart remains large in Stock Detail.
- No nested cards or oversized legends in primary displays.
- Text does not overlap in sidebar or display titles.

**Files:**

- Modify: `frontend/sidebar.html`
- Modify: `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Add failing responsive/static polish tests**

Append:

```python
    def test_sidebar_responsive_layout_and_chart_priority(self):
        html = self.read_sidebar()
        self.assertIn("@media (max-width: 900px)", html)
        self.assertIn(".side-nav-list", html)
        self.assertIn(".chart-viewport", html)
        self.assertIn('data-display="stock"', html)
        stock_display = html[html.index('data-display="stock"'):]
        self.assertLess(stock_display.index('id="tickerDetail"'), stock_display.index('data-display="playbook"'))

    def test_playbook_reference_content_is_not_in_overview(self):
        html = self.read_sidebar()
        overview_block = html[html.index('id="overviewDisplay"'):html.index('id="importDisplay"')]
        self.assertNotIn("What the colors and symbols mean", overview_block)
        self.assertNotIn("Portfolio Monitoring Matrix", overview_block)
```

- [ ] **Step 2: Run tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: fails if layout strings or display separation are missing.

- [ ] **Step 3: Polish CSS constraints**

Add or verify:

```css
      .display-panel > .section,
      .display-panel > .command-deck,
      .display-panel > .monitor-context {
        max-width: 1500px;
      }

      body[data-active-display="stock"] .chart-viewport {
        min-height: 520px;
      }

      body[data-active-display="stock"] .chart-svg {
        min-height: 520px;
      }

      body[data-active-display="overview"] .rule-meaning-disclosure,
      body[data-active-display="overview"] #subscriptionCoverage {
        display: none;
      }
```

- [ ] **Step 4: Manual browser QA**

Start or reuse dev server:

```bash
PYTHONPATH=backend python3 scripts/run_dev_server.py --daemon
```

Open:

```text
http://127.0.0.1:8765/sidebar.html
http://127.0.0.1:8765/sidebar.html?view=holdings&portfolio=cae64c03-1463-406d-8ccf-b8b3e0a8e5a3
http://127.0.0.1:8765/sidebar.html?view=stock&portfolio=cae64c03-1463-406d-8ccf-b8b3e0a8e5a3&ticker=QQQ
```

Expected manual results:

- Overview loads without endless scroll.
- Sidebar item selection changes the main display.
- Holdings list does not show chart inline below it.
- Stock Detail shows chart near the top.
- Playbook holds the legend and monitoring matrix.
- Settings & Activity holds receipt/log/notification panels.

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected: all sidebar tests pass.

---

## Mission Ticket 9: Full Regression And Handoff

**Goal:** Verify the sidebar version works without breaking the current version.

**Definition of Done:**

- Current app tests pass.
- Sidebar tests pass.
- Backend tests pass.
- Dev server serves both `index.html` and `sidebar.html`.
- No production cutover has happened.

**Files:**

- Modify only if previous tasks require small corrections: `frontend/sidebar.html`, `tests/test_frontend_sidebar_static.py`

- [ ] **Step 1: Run current frontend static tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_static
```

Expected:

```text
OK
```

- [ ] **Step 2: Run sidebar frontend static tests**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_sidebar_static
```

Expected:

```text
OK
```

- [ ] **Step 3: Run full backend/frontend suite**

Run:

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests
```

Expected:

```text
OK
```

- [ ] **Step 4: Verify both app versions are served**

Run:

```bash
curl -sS --max-time 5 http://127.0.0.1:8765/ | head -5
curl -sS --max-time 5 http://127.0.0.1:8765/sidebar.html | head -5
```

Expected:

- Both commands return HTML.
- First command remains current app.
- Second command returns sidebar version.

- [ ] **Step 5: Handoff summary**

Report:

- Current app preserved at `http://127.0.0.1:8765/`.
- Sidebar redesign available at `http://127.0.0.1:8765/sidebar.html`.
- Tests run and results.
- Known limitations.
- Explicit statement that no cutover occurred.

---

## Future Cutover Ticket, Not Part Of This Plan

After the user reviews `sidebar.html`, create a separate cutover plan. Options:

1. Replace `frontend/index.html` with the sidebar version after approval.
2. Keep both and add a “Try redesigned dashboard” link.
3. Add a lightweight feature toggle so `?ux=sidebar` uses the new shell.

Do not execute cutover during this plan.

## Self-Review

- Spec coverage: the seven approved displays are represented by tickets 3-8.
- Non-overwrite requirement: enforced by separate `frontend/sidebar.html`, static tests, and no cutover.
- Backend scope: no backend changes planned.
- Testing: static tests, current frontend tests, full `unittest` discovery, and manual browser URLs are included.
- Placeholders: none.

