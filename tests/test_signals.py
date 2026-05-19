from __future__ import annotations

import unittest
from datetime import date, timedelta

from sentinel_core.signals import evaluate_ticker

from tests.factories import dec, flat_bars, make_bar, pivot_low, ticker_view


class SignalTests(unittest.TestCase):
    def test_p1_cross_below_sma150(self):
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
        exits = [result for result in results if result.rule_id == "P1"]

        self.assertEqual(len(exits), 1)
        self.assertTrue(exits[0].triggered)
        self.assertEqual(exits[0].kind, "exit")

    def test_p2_cross_below_sma50(self):
        bars = list(flat_bars(49, close=50))
        bars.append(make_bar(date(2025, 2, 20), 51))
        bars.append(make_bar(date(2025, 2, 21), 45))
        ticker = ticker_view(
            "PLUG",
            "trader",
            shares=dec(100),
            entry_price=dec(60),
            current_profit_lock=dec(48),
            bars=tuple(bars),
        )

        results = evaluate_ticker(ticker, asof=date(2025, 2, 21))
        self.assertEqual([result.rule_id for result in results if result.kind == "exit"], ["P2"])

    def test_p7_distribution_supports_ticker_only(self):
        start = date(2025, 1, 1)
        bars = list(flat_bars(50, close=100, volume=1000, start=start))
        bars.append(make_bar(start + timedelta(days=50), close=95, open_price=100, volume=5200))
        ticker = ticker_view("AAPL", "unknown", bars=tuple(bars))

        results = evaluate_ticker(ticker, asof=start + timedelta(days=50))
        p7 = [result for result in results if result.rule_id == "P7"]

        self.assertEqual(len(p7), 1)
        self.assertEqual(p7[0].kind, "distribution")

    def test_t4_profit_lock_never_lowers(self):
        bars = list(flat_bars(151, close=100))
        asof = bars[-1].date
        ticker = ticker_view(
            "AAPL",
            "investor",
            shares=dec(10),
            entry_price=dec(80),
            current_profit_lock=dec(120),
            bars=tuple(bars),
            swing_pivots=(pivot_low(asof, 110),),
        )

        results = evaluate_ticker(ticker, asof=asof)
        self.assertEqual([result for result in results if result.rule_id == "T4"], [])

    def test_t4_profit_lock_raise(self):
        bars = list(flat_bars(151, close=100))
        asof = bars[-1].date
        ticker = ticker_view(
            "AAPL",
            "investor",
            shares=dec(10),
            entry_price=dec(80),
            current_profit_lock=dec(90),
            bars=tuple(bars),
            swing_pivots=(pivot_low(asof, 110),),
        )

        results = evaluate_ticker(ticker, asof=asof)
        t4 = [result for result in results if result.rule_id == "T4"]
        self.assertEqual(len(t4), 1)
        self.assertEqual(t4[0].payload["proposed_profit_lock"], "108.90")

    def test_t5_drawdown_without_exit(self):
        bars = list(flat_bars(151, close=100))
        asof = bars[-1].date
        ticker = ticker_view(
            "AAPL",
            "investor",
            shares=dec(10),
            entry_price=dec(120),
            current_profit_lock=dec(95),
            bars=tuple(bars),
        )

        results = evaluate_ticker(ticker, asof=asof)
        self.assertEqual([result.rule_id for result in results if result.rule_id == "T5"], ["T5"])

    def test_index_exemption_skips_exit_and_t5(self):
        bars = list(flat_bars(151, close=100))
        bars[-1] = make_bar(bars[-1].date, close=80)
        ticker = ticker_view("VOO", "index", entry_price=dec(120), bars=tuple(bars))

        results = evaluate_ticker(ticker, asof=bars[-1].date)
        self.assertNotIn("P1", [result.rule_id for result in results])
        self.assertNotIn("T5", [result.rule_id for result in results])


if __name__ == "__main__":
    unittest.main()
