# Sidebar Displays UX Redesign Spec

**Date:** 2026-05-19  
**Status:** Draft for review  
**Selected Direction:** Option A - Task Sidebar + Dedicated Displays

## Goal

Replace the current long, mixed-purpose screen with a persistent sidebar and dedicated displays. Each display should answer one user question clearly, reduce scrolling, and make the monitoring workflow understandable for a non-expert trader.

## Problem Summary

The current page mixes portfolio setup, run status, portfolio ticker list, alert triage, stock chart, rule legend, monitoring matrix, activity logs, and advanced controls in one vertical flow. This creates several UX failures:

- Users cannot tell which portfolio is loaded and what they should do next.
- The chart competes with setup panels, legends, alert tables, and long ticker lists.
- The stock detail appears after too much content and can feel hidden.
- Alerts, watched criteria, and rule meanings are spread across multiple panels.
- Reference material such as legends and monitoring matrix occupies decision-making space.

## Design Principle

Use a persistent navigation shell with one active display at a time.

The app should keep global status visible, but it should not show every tool and data panel at once. The user should choose a task from the sidebar, then see a page dedicated to that task.

## App Shell

### Sidebar

The sidebar is the primary navigation surface. It should be visible on desktop and collapse into a menu on small screens.

Sidebar items:

1. **Overview**
2. **Import & Run**
3. **Holdings**
4. **Alert Queue**
5. **Stock Detail**
6. **Playbook**
7. **Settings & Activity**

Sidebar badges should be used sparingly:

- Alert Queue: open action count.
- Holdings: ticker count.
- Stock Detail: selected ticker.
- Import & Run: run state when active or failed.

### Global Status

The top/global status area should remain small and stable. It should show:

- Portfolio name.
- Last run state and timestamp when available.
- Market data readiness.
- One next-action phrase.

It should not contain the full import workflow, alert explanations, or rule legend.

### Routing

The frontend should support display-specific URLs:

- `?view=overview&portfolio=<id>`
- `?view=import&portfolio=<id>`
- `?view=holdings&portfolio=<id>`
- `?view=alerts&portfolio=<id>`
- `?view=stock&portfolio=<id>&ticker=<ticker>`
- `?view=playbook&portfolio=<id>`
- `?view=settings&portfolio=<id>`

Opening a ticker from Holdings or Alert Queue should route to Stock Detail. Stock Detail must not be buried below the ticker list.

## Dedicated Displays

### 1. Overview

Purpose: answer “Where am I, is the monitor current, and what needs my attention?”

Content:

- Portfolio identity.
- Last successful or failed run.
- Data readiness: loaded tickers vs tickers with market bars.
- Open action count.
- Setup/data issues count.
- Top urgent holdings, limited to the top 3-5.
- Clear primary next action.

Excluded:

- Full import form.
- Full ticker table.
- Full chart.
- Full monitoring matrix.
- Advanced logs.

### 2. Import & Run

Purpose: handle setup and monitor execution.

Content:

- Portfolio create/select.
- File upload for CSV, TSV, XLSX, XLSM, and clear unsupported XLS messaging.
- Massive API key field/status.
- As-of date.
- Primary “Import & Run Monitor” action.
- Run progress and final receipt.
- Import source, imported ticker count, market data result.
- Advanced manual controls in a collapsed section.
- Import report in a collapsed section.

Excluded:

- Stock chart.
- Full alert queue.
- Full holdings list, except a compact import summary.

### 3. Holdings

Purpose: let users scan the whole portfolio and choose where to inspect.

Content:

- Action-sorted ticker list.
- Per-stock gauges: urgency, setup/data readiness, exit pressure, bearish pressure, buy-signal state.
- Compact plain-English reason for the current priority.
- Style/type and rule coverage count.
- Market data status.
- “Open Details” action that navigates to Stock Detail.

Behavior:

- Default sort is urgency/action needed.
- The list should be dense enough to scan but not visually crowded.
- Selecting a ticker should not expand a large chart inline.

### 4. Alert Queue

Purpose: triage triggered and near-trigger items.

Content:

- Open alerts and near-trigger watches grouped by urgency.
- For each item: ticker, rule name, rule meaning, trigger status, current value vs trigger value, recommended action.
- Clear distinction between:
  - Triggered action.
  - Near trigger.
  - Setup/data task.
  - Informational/background watch.
- Action controls such as acknowledge or open stock detail.
- Evidence collapsed by default.

Excluded:

- Full chart unless a compact sparkline is later added.
- Full playbook matrix.

### 5. Stock Detail

Purpose: focused workbench for one selected stock.

Content order:

1. Selected ticker header and bottom-line decision.
2. Large responsive chart.
3. Current price, day change, range change, volume, SMA50, SMA150.
4. Chart controls: timeframe, zoom, clean/detailed mode.
5. Chart-visible alerts and triggers with clear symbols, colors, and tooltips.
6. Watched alert cards with current value vs trigger value and plain-English meaning.
7. Setup tasks for missing data, with inline inputs where the user can fix missing setup data.
8. Triggered history with timestamp and price impact since trigger.
9. Evidence/details collapsed by default.

Behavior:

- Chart clean mode should show price, volume, SMA50, SMA150, current/near markers, and current price.
- Detailed mode should add extra watched levels and evidence context.
- Off-scale imported metadata should stay outside the chart scale and be explained only in detailed context.

### 6. Playbook

Purpose: reference area for methodology, rule meanings, and coverage.

Content:

- Rule meaning legend.
- Color and symbol legend.
- Monitoring matrix.
- Rule catalog grouped by purpose: exit, protection, bearish pressure, setup/data, information.
- Explanation of what is chartable and what is not.

Excluded:

- Primary decision queue.
- Full import workflow.

### 7. Settings & Activity

Purpose: operational diagnostics and advanced details.

Content:

- Massive key status and clear-key action.
- Activity log.
- Run receipts.
- Backend/API status messages.
- Raw diagnostics useful during development or troubleshooting.

Excluded:

- Normal alert triage as the primary content.

## Current UI Mapping

Existing current-page components should move as follows:

- `command-deck` -> Import & Run.
- `workflow`, `nextAction`, `runStatus` -> Import & Run, with a compact summary also feeding Overview.
- `runReceiptPanel` -> Overview and Settings & Activity.
- `stockSnapshotPanel` -> Overview and Stock Detail depending on selected ticker.
- `notificationPanel` -> Settings & Activity, with future notification summaries possibly in Overview.
- `ruleMeaningPanel` -> Playbook.
- `positions-panel` / `tickerTable` -> Holdings.
- `alerts` -> Alert Queue.
- `tickerDetail` -> Stock Detail.
- `subscriptionCoverage` -> Playbook.
- `activity` -> Settings & Activity.

## Data And State Model

Add frontend display state:

- `state.activeDisplay`: one of `overview`, `import`, `holdings`, `alerts`, `stock`, `playbook`, `settings`.
- Existing `state.pageMode` can be retired or mapped into `activeDisplay`.
- Existing route ticker logic should remain for Stock Detail.

Rules:

- Portfolio selection remains global.
- Selected ticker is global but only Stock Detail renders the full chart.
- Backend APIs do not need to change for the first implementation pass.
- No demo/sample data should be introduced.

## Empty And Error States

Every display must have a clear empty state:

- No portfolio: “Create or select a portfolio in Import & Run.”
- Portfolio without tickers: “Import a portfolio file to start monitoring.”
- Tickers without market data: “Run monitor to load market data.”
- Stock route with missing ticker: “Ticker not found in this portfolio. Return to Holdings.”
- API failure: show a display-level error with retry action, not a silent `None selected` state.

## Testing Requirements

Automated frontend static tests:

- Sidebar contains the seven approved displays.
- Only one primary display is active at a time.
- Route parsing maps `view=` values to the expected display.
- `view=stock&portfolio=<id>&ticker=<ticker>` preserves selected ticker.
- Holdings links route to Stock Detail instead of inline chart expansion.
- Rule legend and monitoring matrix are not rendered in Overview.

Backend tests:

- No required backend behavior change in first pass.
- Existing HTTP and SQLite tests must remain green.

Manual/browser QA:

- Load saved portfolio.
- Navigate each sidebar display.
- Import & Run remains possible from the Import & Run display.
- Holdings list does not create an endless page with chart below.
- Opening a stock shows a dedicated chart display.
- Alert Queue explains triggered/near/setup states without requiring the user to open Playbook.
- Mobile width uses collapsed sidebar or top menu without overlapping content.

## Implementation Boundary

This redesign is a structural UI refactor, not a rule-engine rewrite. The first implementation should focus on navigation, layout, routing, display separation, and moving existing panels into the correct screens.

Do not add notification delivery, new alert logic, or portfolio analytics in this pass.

