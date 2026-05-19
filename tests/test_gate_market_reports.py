from __future__ import annotations

import unittest
from datetime import date

from sentinel_core.gate import classify_ticker, validate_new_position
from sentinel_core.market_data import (
    InMemoryMarketDataProvider,
    MassiveMarketDataProvider,
    _bars_from_massive_aggs_payload,
    _bars_from_yahoo_chart_payload,
)
from sentinel_core.reports import build_portfolio_report
from sentinel_core.service import SentinelWorkspace

from tests.factories import PORTFOLIO_ID, USER_ID, dec, flat_bars, make_bar


class GateTests(unittest.TestCase):
    def test_classifies_known_index(self):
        self.assertEqual(classify_ticker("VOO"), "index")

    def test_gate_blocks_missing_exit_price(self):
        result = validate_new_position(
            ticker="AAPL",
            ticker_type="investor",
            qty=dec(10),
            entry_price=dec(100),
            exit_price=None,
            portfolio_value=dec(100000),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.blockers[0].rule_id, "T1")

    def test_gate_blocks_buy_below_ma(self):
        bars = list(flat_bars(150, close=100))
        bars.append(make_bar(date(2025, 6, 1), close=80))
        result = validate_new_position(
            ticker="AAPL",
            ticker_type="investor",
            qty=dec(10),
            entry_price=dec(80),
            exit_price=dec(75),
            portfolio_value=dec(100000),
            bars=bars,
        )
        self.assertIn("P4", [issue.rule_id for issue in result.blockers])

    def test_gate_blocks_position_too_large(self):
        result = validate_new_position(
            ticker="AAPL",
            ticker_type="investor",
            qty=dec(100),
            entry_price=dec(100),
            exit_price=dec(95),
            portfolio_value=dec(100000),
        )
        self.assertIn("A5", [issue.rule_id for issue in result.blockers])


class MarketDataTests(unittest.TestCase):
    def test_in_memory_provider_returns_lookback(self):
        bars = flat_bars(10, close=100)
        provider = InMemoryMarketDataProvider.from_items([("AAPL", bars)])
        result = provider.get_bars("aapl", end=bars[-1].date, lookback=3)
        self.assertTrue(provider.validate_symbol("AAPL"))
        self.assertEqual(len(result), 3)

    def test_workspace_backfills_from_provider(self):
        workspace = SentinelWorkspace()
        portfolio = workspace.create_portfolio(user_id=USER_ID, name="Core")
        workspace.import_csv(user_id=USER_ID, portfolio_id=portfolio.portfolio_id, csv_text="ticker\nAAPL\nMSFT\n")
        bars = flat_bars(10, close=100)
        provider = InMemoryMarketDataProvider.from_items([("AAPL", bars)])

        updated = workspace.backfill_market_data(
            portfolio_id=portfolio.portfolio_id,
            provider=provider,
            end=bars[-1].date,
            lookback=5,
        )

        self.assertEqual(updated, ("AAPL",))
        self.assertEqual(len(workspace.tickers_by_portfolio[portfolio.portfolio_id]["AAPL"].bars), 5)

    def test_yahoo_chart_payload_parser_skips_null_rows(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1735689600, 1735776000],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0, None],
                                    "high": [101.0, None],
                                    "low": [99.0, None],
                                    "close": [100.5, None],
                                    "volume": [1234, None],
                                }
                            ],
                            "adjclose": [{"adjclose": [100.5, None]}],
                        },
                    }
                ],
                "error": None,
            }
        }

        bars = _bars_from_yahoo_chart_payload(payload)

        self.assertEqual(len(bars), 1)
        self.assertEqual(str(bars[0].close), "100.5")

    def test_massive_provider_validates_symbols(self):
        provider = MassiveMarketDataProvider(api_key="secret")
        self.assertTrue(provider.validate_symbol("AAPL"))
        self.assertTrue(provider.validate_symbol("BRK.B"))
        self.assertFalse(provider.validate_symbol("bad symbol"))

    def test_massive_aggregates_payload_parser(self):
        payload = {
            "status": "OK",
            "results": [
                {
                    "t": 1735689600000,
                    "o": 100.0,
                    "h": 102.0,
                    "l": 99.5,
                    "c": 101.25,
                    "v": 1234567,
                },
                {
                    "t": 1735776000000,
                    "o": None,
                    "h": 104.0,
                    "l": 100.0,
                    "c": 103.0,
                    "v": 2345678,
                },
            ],
        }

        bars = _bars_from_massive_aggs_payload(payload)

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].date, date(2025, 1, 1))
        self.assertEqual(str(bars[0].close), "101.25")
        self.assertEqual(bars[0].volume, 1234567)


class ReportTests(unittest.TestCase):
    def test_report_summarizes_open_alerts(self):
        workspace = SentinelWorkspace()
        portfolio = workspace.create_portfolio(user_id=USER_ID, name="Core")
        workspace.import_csv(
            user_id=USER_ID,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n",
        )
        bars = list(flat_bars(149, close=100))
        bars.append(make_bar(date(2025, 5, 30), 101))
        bars.append(make_bar(date(2025, 5, 31), 90))
        workspace.set_market_data(portfolio_id=portfolio.portfolio_id, ticker_symbol="AAPL", bars=bars)
        workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2025, 5, 31))

        report = workspace.build_report(portfolio_id=portfolio.portfolio_id)

        self.assertEqual(report.open_alert_count, 1)
        self.assertEqual(report.critical_alert_count, 1)
        self.assertEqual(report.ticket_count, 1)
        self.assertIn("AAPL P1", report.alert_lines[0])


if __name__ == "__main__":
    unittest.main()
