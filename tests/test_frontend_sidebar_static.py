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

    def test_sidebar_defines_approved_display_routes(self):
        html = self.read_sidebar()
        self.assertIn("const DISPLAY_CONFIG", html)
        for display in ["overview", "import", "holdings", "alerts", "stock", "playbook", "settings"]:
            self.assertIn(f'id: "{display}"', html)
        self.assertIn("function routeDisplayFromParams", html)
        self.assertIn("state.activeDisplay", html)
        self.assertIn('params.get("view")', html)

    def test_stock_route_still_preserves_selected_ticker(self):
        html = self.read_sidebar()
        self.assertIn("routeDisplayFromParams(ROUTE_PARAMS)", html)
        self.assertIn("state.selectedTicker = state.routeTicker;", html)
        self.assertIn('displayUrl("stock"', html)
        self.assertIn("tickerDetailUrl(ticker)", html)

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

    def test_holdings_and_alerts_route_to_stock_display(self):
        html = self.read_sidebar()
        self.assertIn('setActiveDisplay("stock"', html)
        self.assertIn('href="${escapeHtml(tickerDetailUrl(ticker.ticker))}"', html)
        self.assertIn('href="${escapeHtml(tickerDetailUrl(alert.result.ticker))}"', html)
        self.assertNotIn('target="_blank" rel="noopener">Open Details</a>', html)

    def test_sidebar_empty_states_are_task_specific(self):
        html = self.read_sidebar()
        self.assertIn("Create or select a portfolio in Import & Run.", html)
        self.assertIn("Import a portfolio file to start monitoring.", html)
        self.assertIn("Run monitor to load market data.", html)
        self.assertIn("Ticker not found in this portfolio. Return to Holdings.", html)
        self.assertIn("displayError", html)

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

    def test_sidebar_polish_constraints_are_applied(self):
        html = self.read_sidebar()
        self.assertIn(".display-panel > .section", html)
        self.assertIn(".display-panel > .command-deck", html)
        self.assertIn(".display-panel > .monitor-context", html)
        self.assertIn("max-width: 1500px", html)
        self.assertIn('body[data-active-display="stock"] .chart-svg', html)
        self.assertIn('body[data-active-display="overview"] .rule-meaning-disclosure', html)

    def test_import_display_uses_novice_walkthrough_flow(self):
        html = self.read_sidebar()
        self.assertIn("Portfolio Setup Walkthrough", html)
        for label in [
            "1. Choose or create the saved portfolio",
            "2. Choose the portfolio file",
            "3. Load and review the tickers",
            "4. Save the portfolio and run the monitor",
        ]:
            self.assertIn(label, html)
        for element_id in [
            "walkPortfolioStatus",
            "walkFileStatus",
            "walkLoadedStatus",
            "walkSavedStatus",
        ]:
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("Supported file types: CSV, TSV, XLS, XLSX, XLSM.", html)
        self.assertIn("Advanced manual controls", html)
        self.assertIn("function renderImportDisplay", html)

    def test_load_file_for_review_has_visible_feedback(self):
        html = self.read_sidebar()
        self.assertIn('id="loadedTickerPreview"', html)
        self.assertIn("function renderLoadedTickerPreview", html)
        self.assertIn('setRunStatus("working", "Loading selected file"', html)
        self.assertIn('setRunStatus("done", "File loaded for review"', html)
        self.assertIn('setRunStatus("error", "File did not load"', html)
        self.assertIn("Review these tickers before saving the portfolio.", html)

    def test_run_monitor_reuses_already_loaded_file(self):
        html = self.read_sidebar()
        self.assertIn("loadedFileSignature", html)
        self.assertIn("function fileSignature", html)
        self.assertIn("fileAlreadyLoaded", html)
        self.assertIn('setRunStatus("working", "Using loaded file"', html)
        self.assertIn("!fileAlreadyLoaded", html)

    def test_server_massive_key_allows_monitor_without_browser_key(self):
        html = self.read_sidebar()
        self.assertIn("marketDataConfig", html)
        self.assertIn("function refreshMarketDataConfig", html)
        self.assertIn("/market-data/config", html)
        self.assertIn("function serverMassiveConfigured", html)
        self.assertIn("function massiveReady", html)
        self.assertIn("Massive key configured on server", html)
        self.assertIn("Server-side Massive key is configured", html)
        self.assertIn("if (!massiveReady())", html)
        self.assertNotIn('if (!massiveApiKey()) {\n          const message = "Massive key is missing.', html)

    def test_near_moving_average_marker_uses_above_and_prepare_copy(self):
        html = self.read_sidebar()
        self.assertIn("function movingAverageTriggerText", html)
        self.assertIn('const relation = close < exitMa ? "below" : "above";', html)
        self.assertIn('if (chartAlertStatusKey(marker) === "near")', html)
        self.assertIn("Prepare. Review the position and wait for a confirmed close below the moving average before treating this as an exit.", html)
        self.assertIn('return { className: "protect", label: "Near trigger watch" };', html)

    def test_near_volume_and_drawdown_markers_do_not_use_triggered_copy(self):
        html = self.read_sidebar()
        self.assertIn("function volumeTriggerText", html)
        self.assertIn('const dayDirection = close !== null && open !== null ? (close < open ? "down day" : close > open ? "up day" : "flat day") : "day";', html)
        self.assertIn("This is elevated volume, not the full 5x down-day distribution trigger.", html)
        self.assertIn("function drawdownTriggerText", html)
        self.assertIn("This is near the 15% loss-limit watch, not a confirmed violation.", html)
        self.assertIn("function nearTriggerRecommendedAction", html)
        self.assertIn("Prepare. Watch for a 5x volume down day before treating this as distribution.", html)
        self.assertIn("Prepare. Check protection and wait for a 15% drawdown breach before treating this as a recovery violation.", html)
        self.assertIn('if (rawStatus.includes("not triggered"))', html)

    def test_t5_clear_and_primary_exit_covered_copy_is_not_violation_copy(self):
        html = self.read_sidebar()
        self.assertIn("covered_by_primary_exit", html)
        self.assertIn("function rowStateAwarePlainEnglish", html)
        self.assertIn('if (row.status.status === "covered_by_primary_exit")', html)
        self.assertIn("This 15% loss-limit watch is covered by the active primary exit signal.", html)
        self.assertIn("No T5 action is needed while there is buffer.", html)
        self.assertIn("Covered by primary exit", html)

    def test_overview_urgency_sort_uses_context_rows(self):
        html = self.read_sidebar()
        self.assertIn("sortTickerRowsByUrgency(tableRowsForCurrentContext().rows)", html)
        self.assertNotIn("sortTickerRowsByUrgency(tableRowsForCurrentContext()).slice", html)

    def test_setup_form_can_use_suggested_stop_without_auto_placing_order(self):
        html = self.read_sidebar()
        self.assertIn("Suggested protective stop", html)
        self.assertIn("Review before saving. Sentinel does not place broker orders.", html)
        self.assertIn("data-use-suggested-stop", html)
        self.assertIn("function useSuggestedStop", html)

    def test_setup_form_always_shows_stop_recommendation_state(self):
        html = self.read_sidebar()
        self.assertIn("Stop recommendation", html)
        self.assertIn("Stop recommendation unavailable", html)
        self.assertIn("Recommendation unavailable until Massive data is loaded for this ticker.", html)
        self.assertIn("function setupStopRecommendationMarkup", html)

    def test_sidebar_uses_readable_custom_tooltips_for_core_explanations(self):
        html = self.read_sidebar()
        self.assertIn(".tooltip-content", html)
        self.assertIn("font-size: 15px", html)
        self.assertIn("line-height: 21px", html)
        self.assertIn("function tooltipMarkup", html)
        self.assertIn("data-tooltip", html)
        self.assertNotIn('class="row-gauge" title=', html)
        self.assertNotIn('class="signal-meter ${unavailable ? "unavailable" : ""}" title=', html)

    def test_resolved_setup_history_is_not_treated_as_current_action(self):
        html = self.read_sidebar()
        self.assertIn("function isCurrentActionStatus", html)
        self.assertIn('return ["triggered", "active"].includes(status);', html)
        self.assertIn("function historicalAlertStatusForMonitor", html)
        self.assertIn("Resolved history", html)
        self.assertIn("Historical alert only. No current action from this alert.", html)
        self.assertIn("rows.filter((row) => isCurrentActionStatus(row.status.status))", html)
        self.assertIn('rows.filter((row) => isCurrentActionStatus(row.status.status)).length', html)

    def test_resolved_setup_chart_history_uses_closed_copy_not_missing_stop_copy(self):
        html = self.read_sidebar()
        self.assertIn("function chartAlertDisplayTitle", html)
        self.assertIn("Stop setup resolved", html)
        self.assertIn("This setup issue has been resolved. No current action is needed from this historical marker.", html)
        self.assertIn("chartAlertRecommendedAction(alert)", html)
        self.assertIn("chartAlertSeverityClass(alert)", html)
        self.assertIn("chartAlertTriggerText(alert)", html)

    def test_passive_watch_cards_have_status_symbols_and_tone_groups(self):
        html = self.read_sidebar()
        self.assertIn("function ruleStatusPresentation", html)
        self.assertIn("function renderStatusBadge", html)
        self.assertIn("status-symbol", html)
        self.assertIn(".rule-focus-card.clear", html)
        self.assertIn(".rule-focus-card.history", html)
        self.assertIn("Good / monitoring", html)
        self.assertIn("History only", html)
        self.assertIn("What this means for", html)

    def test_market_data_status_distinguishes_stored_bars_from_latest_attempt(self):
        html = self.read_sidebar()
        self.assertIn("ticker(s) have stored market data", html)
        self.assertIn("Missing bars:", html)
        self.assertIn("Latest data attempt:", html)
        self.assertIn("Massive key was not active for that run", html)

    def test_primary_monitor_requires_massive_instead_of_silent_fallback(self):
        html = self.read_sidebar()
        self.assertIn("Massive key required", html)
        self.assertIn("Save Portfolio & Run Monitor requires Massive", html)
        self.assertIn("Massive key is missing. Paste the key before running the monitor.", html)
        self.assertNotIn("No Massive key saved. Trying the online fallback", html)
        self.assertNotIn("No Massive key found; trying online fallback bars", html)

    def test_sidebar_remembers_last_active_portfolio(self):
        html = self.read_sidebar()
        self.assertIn('activePortfolioId: "sentinel.activePortfolioId"', html)
        self.assertIn("function loadActivePortfolioId", html)
        self.assertIn("function saveActivePortfolioId", html)
        self.assertIn("saveActivePortfolioId(portfolio.portfolio_id)", html)
        self.assertIn("const rememberedPortfolioId = loadActivePortfolioId();", html)
        self.assertIn("rememberedPortfolioId && state.portfolios.find", html)

    def test_stock_detail_shows_active_portfolio_context(self):
        html = self.read_sidebar()
        self.assertIn("Portfolio Context", html)
        self.assertIn("state.portfolioName || \"Portfolio\"", html)
        self.assertIn("compactId(state.portfolioId)", html)
        self.assertIn("Stop / Profit Lock", html)

    def test_resolved_setup_marker_history_is_neutral_and_grouped(self):
        html = self.read_sidebar()
        self.assertIn("function chartExplanationItems", html)
        self.assertIn("isResolvedSetupGroup", html)
        self.assertIn("function chartAlertCardClass", html)
        self.assertIn("function chartAlertActionMarkup", html)
        self.assertIn(".mini-alert.history", html)
        self.assertIn("alert-command history", html)
        self.assertIn("Current action", html)
        self.assertIn("No current action is needed. This setup issue is closed.", html)

    def test_holdings_rows_use_three_zone_layout_without_dense_data_columns(self):
        html = self.read_sidebar()
        self.assertIn("function renderTickerRowFactGrid", html)
        self.assertIn("function renderTickerRowActionPanel", html)
        self.assertIn("row-layout-main", html)
        self.assertIn("row-layout-signals", html)
        self.assertIn("row-layout-actions", html)
        self.assertIn("row-fact-grid", html)
        self.assertIn("row-meta-details", html)
        self.assertIn("Price data", html)
        self.assertIn("Current style", html)

    def test_chart_markers_are_readable_decluttered_and_ignore_resolved_setup_when_stop_saved(self):
        html = self.read_sidebar()
        self.assertIn("function tickerHasStopSetup", html)
        self.assertIn("function chartMarkerVisibleOnPriceChart", html)
        self.assertIn("chartMarkerVisibleOnPriceChart(marker, ticker)", html)
        self.assertIn("function markerClusterOffset", html)
        self.assertIn("marker-lane", html)
        self.assertIn("const boxWidth = 520", html)
        self.assertIn("font-size: 16px", html)
        self.assertIn("line-height: 22px", html)
        self.assertIn("fill-opacity: 0.96", html)
        self.assertIn("function chartMarkerActionSummary", html)
        self.assertIn("Action: ${chartMarkerActionSummary(marker)}", html)
        self.assertNotIn('visible[maxLines - 1] = `${visible[maxLines - 1].replace(/[. ]+$/, "")}...`;', html)
        self.assertIn("const markerLaneCount = 6", html)
        self.assertIn("xOffset: column * 38", html)
        self.assertIn("yOffset: lane * 42", html)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', html)
        self.assertIn("data-marker-index", html)

    def test_holdings_scores_use_backend_payload_with_frontend_fallback(self):
        html = self.read_sidebar()
        self.assertIn("ticker.holding_scores", html)
        self.assertIn('sell: scoreValue("exit")', html)
        self.assertIn("left.holding_scores?.rank", html)
        self.assertIn("function triggerItemsForRules", html)
        self.assertIn("function scoreSellPressure", html)
        self.assertIn("function scoreSetupCoverage", html)
        self.assertIn("function scoreRowUrgency", html)
        self.assertIn("const setupScore = scoreSetupCoverage", html)
        self.assertIn("const sell = scoreSellPressure(ticker, sellOpenCount);", html)
        self.assertIn("const urgencyScore = scoreRowUrgency", html)
        self.assertNotIn("marketOpenCount ? 100", html)
        self.assertNotIn("sellOpenCount ? 100 : 0", html)

    def test_frontend_uses_durable_backend_run_receipts_and_alert_events(self):
        html = self.read_sidebar()
        self.assertIn("detailPayload.latest_run || loadRunReceipt", html)
        self.assertIn("receipt.alerts_created_count", html)
        self.assertIn("receipt.alerts_resolved_count", html)
        self.assertIn("function renderAlertEventLog", html)
        self.assertIn("detail.alert_events || []", html)
        self.assertIn("Alert Timeline", html)
        self.assertIn("function alertTimelineEventLabel", html)
        self.assertIn("Price response since trigger", html)

    def test_overview_has_portfolio_qa_panel_and_failed_massive_retry(self):
        html = self.read_sidebar()
        self.assertIn('id="portfolioQaPanel"', html)
        self.assertIn("function renderPortfolioQaPanel", html)
        self.assertIn("Portfolio QA Checklist", html)
        self.assertIn("qa_summary", html)
        self.assertIn("Retry Failed Massive Symbols", html)
        self.assertIn("function failedMassiveTickers", html)
        self.assertIn("function retryFailedMassiveTickers", html)
        self.assertIn('failed_only: true', html)

    def test_settings_display_supports_email_and_telegram_notification_settings(self):
        html = self.read_sidebar()
        self.assertIn('id="notificationSettingsPanel"', html)
        self.assertIn("function renderNotificationSettings", html)
        self.assertIn("function saveNotificationSettings", html)
        self.assertIn("/notification-settings", html)
        self.assertIn("Email alerts", html)
        self.assertIn("Telegram alerts", html)
        self.assertIn("data-save-notification-settings", html)
        self.assertIn("data-test-notification-settings", html)
        self.assertIn("function testNotificationSettings", html)
        self.assertIn("state.notificationSettings", html)

    def test_holdings_entry_price_uses_readable_one_decimal_format(self):
        html = self.read_sidebar()
        self.assertIn("function formatRowPrice", html)
        self.assertIn("formatRowPrice(ticker.entry_price)", html)
        self.assertNotIn("formatValue(ticker.entry_price)", html)

    def test_missing_stop_can_be_entered_from_holdings_and_stock_detail(self):
        html = self.read_sidebar()
        self.assertIn("function tickerNeedsStopSetup", html)
        self.assertIn("function stopSetupEvidenceForTicker", html)
        self.assertIn("function renderMissingStopSetupPanel", html)
        self.assertIn("tickerNeedsStopSetup(ticker)", html)
        self.assertIn("Add missing stop / profit-lock", html)
        self.assertIn("Protection setup", html)
        self.assertIn("data-save-setup", html)
        self.assertIn("renderMissingStopSetupPanel(detail.ticker", html)
        self.assertIn("renderMissingStopSetupPanel(ticker", html)

    def test_profit_lock_raise_action_can_save_recommended_level(self):
        html = self.read_sidebar()
        self.assertIn("function profitLockRaiseActionMarkup", html)
        self.assertIn("Use recommended profit lock", html)
        self.assertIn("proposed_profit_lock", html)
        self.assertIn("data-use-profit-lock", html)
        self.assertIn("profitLockRaiseActionMarkup(row)", html)
        self.assertIn("profitLockRaiseActionMarkup(alert)", html)

    def test_setup_save_uses_backend_lifecycle_response_without_second_evaluate(self):
        html = self.read_sidebar()
        start = html.index("async function saveTickerSetupData")
        end = html.index("async function selectTicker", start)
        body = html[start:end]
        self.assertIn("const payload = await api(`/portfolios/${state.portfolioId}/tickers/${encodeURIComponent(ticker)}/setup-data`", body)
        self.assertIn("asof: $(\"asofDate\").value || todayIso()", body)
        self.assertIn("state.detail = payload.portfolio_detail || state.detail;", body)
        self.assertNotIn("`/portfolios/${state.portfolioId}/evaluate`", body)

    def test_saved_portfolio_next_action_uses_saved_tickers_before_editor_rows(self):
        html = self.read_sidebar()
        saved_count_index = html.index("const savedTickerCount = Number(savedSummary.ticker_count || 0);")
        import_current_index = html.index("if (csv.rowCount && (!importIsCurrent || sourceNeedsSave))")
        empty_editor_index = html.index("if (!savedTickerCount)")
        self.assertLess(saved_count_index, import_current_index)
        self.assertLess(import_current_index, empty_editor_index)
        self.assertIn("Saved tickers are ready, but no bars are loaded for charts or price rules.", html)

    def test_route_portfolio_id_is_honored_for_all_displays(self):
        html = self.read_sidebar()
        start = html.index("async function initializeApp")
        end = html.index("function resetReportsForNewCsv", start)
        body = html[start:end]
        routed_index = body.index("const routedPortfolio = state.routePortfolioId && state.portfolios.find")
        remembered_index = body.index("const rememberedPortfolioId = loadActivePortfolioId();")
        self.assertLess(routed_index, remembered_index)
        self.assertIn("setActivePortfolio(routedPortfolio, { preserveSelectedTicker: Boolean(state.routeTicker) });", body)
        self.assertNotIn('if (state.pageMode === "stock" && state.routePortfolioId && state.routeTicker)', body)

    def test_chart_current_trigger_markers_are_not_suppressed_by_rule_id_only(self):
        html = self.read_sidebar()
        self.assertIn("function chartMarkerDedupeKey", html)
        self.assertIn("const existingMarkerKeys = new Set", html)
        self.assertIn("!existingMarkerKeys.has(chartMarkerDedupeKey(trigger, latestVisibleDate))", html)
        self.assertNotIn(".filter((trigger) => !alertRules.has(trigger.rule_id))", html)


if __name__ == "__main__":
    unittest.main()
