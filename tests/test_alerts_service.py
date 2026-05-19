from __future__ import annotations

import unittest
from datetime import date
from uuid import uuid4

from sentinel_core.alerts import materialize_alerts
from sentinel_core.service import SentinelWorkspace
from sentinel_core.signals import evaluate_ticker

from tests.factories import dec, flat_bars, make_bar, ticker_view


class AlertMaterializationTests(unittest.TestCase):
    def test_dedupes_existing_open_alerts(self):
        bars = list(flat_bars(149, close=100))
        bars.append(make_bar(date(2025, 5, 30), 101))
        bars.append(make_bar(date(2025, 5, 31), 90))
        ticker = ticker_view(
            "AAPL",
            "investor",
            shares=dec(10),
            entry_price=dec(110),
            current_profit_lock=dec(95),
            bars=tuple(bars),
        )
        results = evaluate_ticker(ticker, asof=date(2025, 5, 31))
        first = materialize_alerts(ticker=ticker, results=results)
        second = materialize_alerts(ticker=ticker, results=results, existing_alerts=first)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])


class WorkspaceFlowTests(unittest.TestCase):
    def test_preview_does_not_mutate_workspace(self):
        user_id = uuid4()
        workspace = SentinelWorkspace()
        portfolio = workspace.create_portfolio(user_id=user_id, name="Preview")

        report = workspace.preview_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker\nAAPL\n",
        )

        self.assertEqual(report.created_count, 1)
        self.assertEqual(workspace.tickers_by_portfolio[portfolio.portfolio_id], {})

    def test_import_subscribe_evaluate_alert_flow(self):
        user_id = uuid4()
        workspace = SentinelWorkspace()
        portfolio = workspace.create_portfolio(user_id=user_id, name="Growth")
        report, subscriptions = workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n",
        )
        bars = list(flat_bars(149, close=100))
        bars.append(make_bar(date(2025, 5, 30), 101))
        bars.append(make_bar(date(2025, 5, 31), 90))
        workspace.set_market_data(
            portfolio_id=portfolio.portfolio_id,
            ticker_symbol="AAPL",
            bars=bars,
        )

        alerts = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2025, 5, 31))

        self.assertEqual(report.created_count, 1)
        self.assertIn("P1", [subscription.rule_id for subscription in subscriptions])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].result.rule_id, "P1")
        self.assertEqual(alerts[0].ticket.copy_text, "SELL 10 AAPL MARKET")
        self.assertIn("closed at", alerts[0].explanation.what_triggered)

    def test_evaluation_is_scoped_per_portfolio(self):
        user_id = uuid4()
        workspace = SentinelWorkspace()
        portfolio_a = workspace.create_portfolio(user_id=user_id, name="A")
        portfolio_b = workspace.create_portfolio(user_id=user_id, name="B")
        csv_text = "ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n"
        workspace.import_csv(user_id=user_id, portfolio_id=portfolio_a.portfolio_id, csv_text=csv_text)
        workspace.import_csv(user_id=user_id, portfolio_id=portfolio_b.portfolio_id, csv_text=csv_text)
        bars = list(flat_bars(149, close=100))
        bars.append(make_bar(date(2025, 5, 30), 101))
        bars.append(make_bar(date(2025, 5, 31), 90))
        workspace.set_market_data(portfolio_id=portfolio_a.portfolio_id, ticker_symbol="AAPL", bars=bars)

        alerts_a = workspace.evaluate_portfolio(portfolio_id=portfolio_a.portfolio_id, asof=date(2025, 5, 31))
        alerts_b = workspace.evaluate_portfolio(portfolio_id=portfolio_b.portfolio_id, asof=date(2025, 5, 31))

        self.assertEqual(len(alerts_a), 1)
        self.assertEqual(alerts_b, [])


if __name__ == "__main__":
    unittest.main()
