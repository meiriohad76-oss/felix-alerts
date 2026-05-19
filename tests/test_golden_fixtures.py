from __future__ import annotations

import json
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sentinel_core.alerts import materialize_alerts
from sentinel_core.signals import evaluate_ticker

from tests.bar_fixtures import p1_cross_below_sma150_bars, p7_distribution_day_bars
from tests.factories import ticker_view


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "fixtures" / "golden"


def bars_from_pattern(pattern: str):
    if pattern == "p1_cross_below_sma150":
        return p1_cross_below_sma150_bars()
    if pattern == "p7_distribution_day":
        return p7_distribution_day_bars()
    raise ValueError("Unknown golden bar pattern: %s" % pattern)


def ticker_from_payload(payload, bars):
    ticker_data = payload["ticker"]
    return ticker_view(
        ticker_data["ticker"],
        ticker_data.get("type", "unknown"),
        shares=Decimal(ticker_data["shares"]) if "shares" in ticker_data else None,
        entry_price=Decimal(ticker_data["entry_price"]) if "entry_price" in ticker_data else None,
        current_profit_lock=Decimal(ticker_data["current_profit_lock"])
        if "current_profit_lock" in ticker_data
        else None,
        bars=tuple(bars),
    )


class GoldenFixtureTests(unittest.TestCase):
    def test_all_golden_fixtures(self):
        fixture_paths = sorted(GOLDEN_DIR.glob("*.json"))
        self.assertTrue(fixture_paths, "expected at least one golden fixture")
        for path in fixture_paths:
            with self.subTest(path=path.name):
                payload = json.loads(path.read_text())
                bars = bars_from_pattern(payload["bars"]["pattern"])
                ticker = ticker_from_payload(payload, bars)
                asof = datetime.strptime(payload["asof"], "%Y-%m-%d").date()
                results = evaluate_ticker(ticker, asof=asof)
                alerts = materialize_alerts(ticker=ticker, results=results)
                self.assertEqual(
                    [result.rule_id for result in results],
                    payload["expected"]["rule_ids"],
                )
                self.assertEqual(
                    [alert.ticket.action for alert in alerts if alert.ticket is not None],
                    payload["expected"]["ticket_actions"],
                )


if __name__ == "__main__":
    unittest.main()
