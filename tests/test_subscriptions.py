from __future__ import annotations

import unittest

from sentinel_core.subscriptions import create_subscriptions_for_portfolio

from tests.factories import ticker_view


class SubscriptionTests(unittest.TestCase):
    def test_unknown_ticker_gets_setup_and_distribution_subscriptions(self):
        ticker = ticker_view("PLUG", "unknown")
        subscriptions = create_subscriptions_for_portfolio([ticker])
        self.assertEqual([item.rule_id for item in subscriptions], ["C1", "P7", "T1"])

    def test_investor_gets_investor_rule_set(self):
        ticker = ticker_view("AAPL", "investor")
        rule_ids = [item.rule_id for item in create_subscriptions_for_portfolio([ticker])]
        self.assertIn("P1", rule_ids)
        self.assertNotIn("P2", rule_ids)
        self.assertIn("T4", rule_ids)

    def test_recreating_subscriptions_is_idempotent(self):
        ticker = ticker_view("AAPL", "investor")
        first = create_subscriptions_for_portfolio([ticker])
        second = create_subscriptions_for_portfolio([ticker], existing=first)
        self.assertEqual(len(first), len(second))
        self.assertEqual({item.subscription_id for item in first}, {item.subscription_id for item in second})


if __name__ == "__main__":
    unittest.main()
