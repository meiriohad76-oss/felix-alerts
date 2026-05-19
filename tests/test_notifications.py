from __future__ import annotations

import unittest
from datetime import date

from sentinel_core.alerts import materialize_alerts
from sentinel_core.notifications import (
    DISCLAIMER,
    external_notifications_for_alerts,
    notification_for_alert,
    notifications_for_alerts,
    render_alert_email,
    render_alert_telegram,
)
from sentinel_core.signals import evaluate_ticker

from tests.factories import dec, flat_bars, make_bar, ticker_view


class NotificationTests(unittest.TestCase):
    def test_alert_email_contains_explanation_ticket_and_disclaimer(self):
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
        alert = materialize_alerts(ticker=ticker, results=[result])[0]

        email = render_alert_email(alert)

        self.assertIn("P1", email.subject)
        self.assertIn("What triggered", email.text_body)
        self.assertIn("SELL 10 AAPL MARKET", email.text_body)
        self.assertIn(DISCLAIMER, email.text_body)
        self.assertNotIn("Execute All Exits", email.text_body)
        self.assertNotIn("auto-trade", email.text_body.lower())

    def test_alert_notification_record_is_stable_and_local(self):
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
        alert = materialize_alerts(ticker=ticker, results=[result])[0]

        notification = notification_for_alert(alert)
        duplicate = notification_for_alert(alert)

        self.assertEqual(notification.notification_id, duplicate.notification_id)
        self.assertEqual(notification.channel, "in_app")
        self.assertEqual(notification.status, "sent")
        self.assertEqual(notification.alert_id, alert.alert_id)
        self.assertIn("P1", notification.subject)
        self.assertIn(DISCLAIMER, notification.body)
        generated = notifications_for_alerts([alert])
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0].notification_id, notification.notification_id)

    def test_telegram_alert_message_is_concise_actionable_and_disclaimed(self):
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
        alert = materialize_alerts(ticker=ticker, results=[result])[0]

        message = render_alert_telegram(alert, stock_url="https://sentinel.example.com/?view=stock&ticker=AAPL")

        self.assertLess(len(message), 1200)
        self.assertIn("AAPL", message)
        self.assertIn("P1", message)
        self.assertIn("What triggered", message)
        self.assertIn("Recommended action", message)
        self.assertIn("https://sentinel.example.com", message)
        self.assertIn("does not place broker orders", message)
        self.assertNotIn("auto-trade", message.lower())

    def test_external_notifications_follow_channel_settings(self):
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
        alert = materialize_alerts(ticker=ticker, results=[result])[0]

        notifications = external_notifications_for_alerts(
            [alert],
            {
                "email_enabled": True,
                "email_recipients": ("user@example.com",),
                "telegram_enabled": True,
                "telegram_chat_id": "12345",
            },
        )

        self.assertEqual([notification.channel for notification in notifications], ["email", "telegram"])
        self.assertEqual([notification.status for notification in notifications], ["queued", "queued"])
        self.assertIn(DISCLAIMER, notifications[0].body)
        self.assertIn("does not place broker orders", notifications[1].body)


if __name__ == "__main__":
    unittest.main()
