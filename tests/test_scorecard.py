from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from sentinel_core.alerts import materialize_alerts
from sentinel_core.scorecard import acknowledge_alert, stale_exit_events, summarize_events
from sentinel_core.signals import evaluate_ticker

from tests.factories import dec, flat_bars, make_bar, ticker_view


def exit_alert():
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
    return materialize_alerts(ticker=ticker, results=[result])[0]


class ScorecardTests(unittest.TestCase):
    def test_ignored_ack_requires_note(self):
        alert = exit_alert()
        with self.assertRaises(ValueError):
            acknowledge_alert(alert, ack_kind="ignored")

    def test_ignored_ack_creates_scorecard_event(self):
        alert = exit_alert()
        updated, event = acknowledge_alert(alert, ack_kind="ignored", note="I wanted to wait")

        self.assertEqual(updated.status, "acknowledged")
        self.assertEqual(updated.ack_kind, "ignored")
        self.assertEqual(event.kind, "ignored")

    def test_stale_exit_events(self):
        alert = exit_alert()
        stale = alert.__class__(
            alert_id=alert.alert_id,
            result=alert.result,
            explanation=alert.explanation,
            ticket=alert.ticket,
            status=alert.status,
            created_at=datetime.utcnow() - timedelta(days=8),
        )

        events = stale_exit_events([stale], now=datetime.utcnow())
        self.assertEqual(events[0].kind, "missed")

    def test_summarize_events(self):
        alert = exit_alert()
        _, event = acknowledge_alert(alert, ack_kind="placed")
        self.assertEqual(summarize_events([event]), {"placed": 1})


if __name__ == "__main__":
    unittest.main()

