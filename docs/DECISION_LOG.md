# Deferred Decision Log

The user asked to concentrate decisions at the end of implementation. This log captures assumptions made during autonomous implementation so they can be reviewed later in one batch.

## Open Decisions

1. **Market-data provider**: the current backend core uses a provider-neutral port. Vendor selection remains deferred.
2. **Ticker-only portfolio language**: the implementation supports ticker-only rows as monitored portfolio tickers. Final product wording still needs a choice: watch portfolio, holdings with missing metadata, or both.
3. **P3/T4 buffer**: implemented with the v1 fixed 1% buffer from the spec. ATR-based buffering remains deferred.
4. **P7 volume baseline**: implemented as today's volume compared with the previous 50 sessions' average volume, excluding today. This avoids the current spike diluting its own baseline.
5. **Subscription matrix**: implemented `T4` as the user-facing subscription for the P3/T4 profit-lock raise behavior.
6. **CSV replace semantics**: replace mode marks missing tickers inactive. Merge mode remains the default.
7. **Ticker validation**: implemented syntactic validation only in the core. Real symbol validation will happen through the future market-data port.
8. **Pre-trade gate sizing**: implemented 5% notional as a blocker, 1.5% risk as a blocker, and 1% risk as a warning.
9. **Index classification**: implemented a small broad-index ETF allowlist in `gate.py`; final allowlist can be expanded later.
10. **Report format**: implemented a compact structured portfolio report object, not a final HTML/PDF report renderer.
11. **Persistence**: implemented an in-memory `SentinelWorkspace` service to prove the end-to-end flow before choosing database/API details.
12. **Dependency posture**: kept this first implementation slice standard-library only because FastAPI/uvicorn/pytest were not installed locally. The core is ready to be wrapped by FastAPI later.
13. **Golden fixtures**: added a small executable test fixture set first, with the expectation that historical market cases can be added once vendor data is connected.
14. **Dev API transport**: added a dependency-free standard-library HTTP API for local development. This is a bridge until FastAPI is added.
15. **Dev UI data source**: superseded. Local synthetic market-data routes have been removed from the product API; imported portfolios now use Massive or the online fallback path.
16. **Local persistence**: the dev server writes to `sentinel_dev.sqlite3` in the repo root. Production database placement remains deferred.
17. **Uploaded workbook source**: superseded. The converted workbook file is no longer bundled; the user imports local portfolio files through the UI or conversion endpoint.
18. **Workbook row filtering**: skipped invalid symbol rows such as Excel date/lot rows and `TOTAL`; retained 28 valid tickers.
19. **Workbook type mapping**: untyped portfolio holdings now default to `investor` so full playbook subscriptions attach immediately. Excel workbook imports do not auto-classify broad ETFs as `index`; imported/default holdings use normal investor style unless explicitly changed.
20. **Workbook profit locks**: left `current_profit_lock` blank because the workbook does not provide methodology exit/profit-lock levels.
21. **Portfolio name UI**: portfolio names were already persisted; the UI now displays saved names and includes a saved-portfolio selector.
22. **Subscription re-import cleanup**: persistent CSV re-import now replaces portfolio subscriptions so stale `A7` index subscriptions are removed when a ticker changes to `unknown`.
23. **Portfolio file formats**: implemented local upload conversion for `.csv`, `.tsv`, `.xlsx`, and `.xlsm`. Legacy binary `.xls` remains deferred because reliable parsing requires an external parser dependency or conversion service.
24. **Untyped CSV rows**: ticker-only or blank-type CSV rows default to `investor`. Explicit `unknown` remains available for watchlist/setup rows.
25. **Existing dev portfolio repair**: added a bulk action to classify existing `unknown` tickers as `investor` and rebuild subscriptions, because older imported dev portfolios may still have 3 setup subscriptions per ticker.
26. **Market data source**: Massive daily aggregates are the preferred real-data path. The online fallback path remains available for resilience while final production vendor details remain open.
27. **Readable chart fixture**: superseded. Local chart-seeding routes and bundled portfolio files were removed so charts reflect imported holdings and loaded market data only.
28. **Chart trigger metadata**: ticker detail now returns watched indicators and potential trigger watches from the backend. The frontend can compute fallback lines, but the backend is the source of truth for rule labels, rationale, action copy, and trigger status.
29. **Massive market-data integration**: added Massive daily aggregate backfill as the preferred subscribed real-data path, configured through the app key field or `MASSIVE_API_KEY` in the server environment. The online fallback remains available for resilience.
30. **Default portfolio style**: the default style/type for every imported or newly displayed portfolio ticker is `investor`. `unknown` remains only as an explicit override for special watchlist/setup rows or old dev data.
31. **Evidence display**: raw evidence/data payloads remain available for auditability, but they are hidden by default behind explicit `Show Evidence & Data` expanders on alert and watched-rule views.
32. **UX redesign direction**: applied the Institutional Pro design files by replacing the stacked setup-panel layout with a compact command dock, position rail, dominant chart workspace, and methodology-verdict alert queue.
33. **Chart and alert emphasis**: chart rendering now includes visible methodology overlays, SMA150 exit-zone shading, alert callout rays, and command-style alert actions so the center of the app is the rule decision, not the raw data.
34. **Frontend cache posture**: the local dev API now serves `index.html` with no-cache headers so UI changes are not hidden by browser caching during active development.
