from __future__ import annotations

import unittest
from datetime import date

from sentinel_core.explanations import render_explanation
from sentinel_core.signals import evaluate_ticker
from sentinel_core.tickets import generate_order_ticket

from tests.factories import dec, flat_bars, make_bar, pivot_low, ticker_view


class ExplanationAndTicketTests(unittest.TestCase):
    def test_exit_alert_explanation_contains_rule_context(self):
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
        result = [item for item in evaluate_ticker(ticker, asof=date(2025, 5, 31)) if item.rule_id == "P1"][0]

        explanation = render_explanation(result)

        self.assertEqual(explanation.rule_id, "P1")
        self.assertIn("closed at", explanation.what_triggered)
        self.assertIn("150-day", explanation.title)
        self.assertIn("Sell", explanation.recommended_action)

    def test_exit_ticket_requires_shares(self):
        bars = list(flat_bars(149, close=100))
        bars.append(make_bar(date(2025, 5, 30), 101))
        bars.append(make_bar(date(2025, 5, 31), 90))
        ticker = ticker_view("AAPL", "investor", shares=None, current_profit_lock=dec(95), bars=tuple(bars))
        result = [item for item in evaluate_ticker(ticker, asof=date(2025, 5, 31)) if item.rule_id == "P1"][0]

        self.assertIsNone(generate_order_ticket(ticker, result))

    def test_t5_explanation_uses_human_percent(self):
        bars = [make_bar(date(2025, 5, 31), 6.42)]
        ticker = ticker_view(
            "PLUG",
            "trader",
            shares=dec(1200),
            entry_price=dec("14.22"),
            current_profit_lock=dec("12.50"),
            bars=tuple(bars),
        )
        result = [item for item in evaluate_ticker(ticker, asof=date(2025, 5, 31)) if item.rule_id == "T5"][0]

        explanation = render_explanation(result)

        self.assertIn("down 54.9% from entry", explanation.what_triggered)
        self.assertNotIn("0.548", explanation.what_triggered)

    def test_missing_profit_lock_explanation_is_plain_english(self):
        ticker = ticker_view(
            "AAOI",
            "investor",
            shares=dec(10),
            entry_price=dec("178.60"),
            current_profit_lock=None,
            bars=tuple(),
        )
        result = [item for item in evaluate_ticker(ticker, asof=date(2025, 5, 31)) if item.rule_id == "T1"][0]

        explanation = render_explanation(result)

        self.assertIn("needs setup data", explanation.what_triggered)
        self.assertIn("profit-lock/stop level", explanation.what_triggered)
        self.assertIn("imported portfolio file did not include", explanation.what_triggered)

    def test_missing_profit_lock_includes_reviewable_suggested_stop(self):
        bars = list(flat_bars(150, close=100))
        bars.append(make_bar(date(2025, 5, 31), 130))
        ticker = ticker_view(
            "CGDV",
            "investor",
            shares=dec(10),
            entry_price=dec("125"),
            current_profit_lock=None,
            bars=tuple(bars),
            swing_pivots=(pivot_low(date(2025, 5, 15), 120),),
        )

        result = [item for item in evaluate_ticker(ticker, asof=date(2025, 5, 31)) if item.rule_id == "A1"][0]
        ticket = generate_order_ticket(ticker, result)
        explanation = render_explanation(result)

        self.assertEqual(result.payload["suggested_stop"], "118.80")
        self.assertEqual(result.payload["basis_rule"], "swing low above SMA150")
        self.assertIn("Review the suggested protective stop", explanation.recommended_action)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.stop_price, dec("118.80"))
        self.assertEqual(ticket.copy_text, "PLACE STOP CGDV AT 118.80 FOR 10 SHARES")

    def test_exit_ticket_copy_text(self):
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
        result = [item for item in evaluate_ticker(ticker, asof=date(2025, 5, 31)) if item.rule_id == "P1"][0]
        ticket = generate_order_ticket(ticker, result)

        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.action, "sell")
        self.assertEqual(ticket.copy_text, "SELL 10 AAPL MARKET")


if __name__ == "__main__":
    unittest.main()
