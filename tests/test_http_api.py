from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from sentinel_core.http_api import create_server
from sentinel_core.market_data import InMemoryMarketDataProvider
from tests.bar_fixtures import p1_cross_below_sma150_bars
from tests.test_xlsx_import import write_minimal_xlsx


class RecordingEmailProvider:
    def __init__(self):
        self.sent = []

    def send(self, message, recipients):
        self.sent.append({"message": message, "recipients": tuple(recipients)})
        return "email-ok"


class RecordingTelegramProvider:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append({"chat_id": chat_id, "text": text})
        return "telegram-ok"


class FailingEmailProvider:
    def send(self, message, recipients):
        raise RuntimeError("smtp unavailable")


def request(server, method, path, payload=None):
    host, port = server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    body = json.dumps(payload or {})
    conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    data = json.loads(response.read().decode("utf-8"))
    conn.close()
    return response.status, data


def raw_request(server, method, path):
    host, port = server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(method, path)
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    headers = {key.lower(): value for key, value in response.getheaders()}
    conn.close()
    return response.status, headers, body


class HttpApiTests(unittest.TestCase):
    def test_macos_proxy_detection_retries_unstable_wpad_pac(self):
        from sentinel_core import http_api

        completed = subprocess.CompletedProcess(
            args=("scutil", "--proxy"),
            returncode=0,
            stdout="ProxyAutoConfigURLString : http://wpad/wpad.dat\n",
            stderr="",
        )
        attempts = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'return "PROXY proxy.example.com:8080; DIRECT";'

        def flaky_urlopen(url, timeout):
            attempts.append((url, timeout))
            if len(attempts) < 3:
                raise OSError("wpad timeout")
            return Response()

        with patch("sentinel_core.http_api.subprocess.run", return_value=completed), patch(
            "sentinel_core.http_api.urlopen",
            side_effect=flaky_urlopen,
        ), patch("sentinel_core.http_api._can_open_tcp", return_value=True):
            self.assertEqual(
                http_api._proxy_from_macos_settings(),
                "http://proxy.example.com:8080",
            )
        self.assertEqual(len(attempts), 3)

    def test_proxy_detection_does_not_cache_initial_miss(self):
        from sentinel_core import http_api

        http_api._PROXY_CACHE_READY = False
        http_api._PROXY_CACHE_VALUE = None
        try:
            with patch("sentinel_core.http_api._proxy_from_environment", return_value=None), patch(
                "sentinel_core.http_api._proxy_from_macos_settings",
                side_effect=[None, "http://proxy.example.com:8080"],
            ):
                self.assertIsNone(http_api._detect_proxy_url())
                self.assertEqual(http_api._detect_proxy_url(), "http://proxy.example.com:8080")
        finally:
            http_api._PROXY_CACHE_READY = False
            http_api._PROXY_CACHE_VALUE = None

    def test_connectivity_check_retries_proxy_detection_after_direct_failure(self):
        from sentinel_core import http_api

        with patch(
            "sentinel_core.http_api._https_connectivity_error",
            side_effect=[
                "Cannot reach Massive API at api.massive.com:443 from this computer (timed out).",
                None,
            ],
        ) as connectivity, patch(
            "sentinel_core.http_api._detect_proxy_url",
            return_value="http://proxy.example.com:8080",
        ) as detect_proxy:
            error, proxy_url = http_api._https_connectivity_error_with_proxy_retry(
                "https://api.massive.com",
                timeout_seconds=8,
                service_label="Massive API",
                proxy_url=None,
            )

        self.assertIsNone(error)
        self.assertEqual(proxy_url, "http://proxy.example.com:8080")
        detect_proxy.assert_called_once_with(force_refresh=True)
        self.assertEqual(connectivity.call_count, 2)
        self.assertIsNone(connectivity.call_args_list[0].kwargs["proxy_url"])
        self.assertEqual(connectivity.call_args_list[1].kwargs["proxy_url"], "http://proxy.example.com:8080")

    def test_static_root_serves_sidebar_when_available_without_browser_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "index.html").write_text("<html>legacy ui</html>")
            Path(tmp, "sidebar.html").write_text("<html>fresh sidebar ui</html>")
            server = create_server(db_path=":memory:", port=0, static_dir=tmp)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, headers, body = raw_request(server, "GET", "/")
                self.assertEqual(status, 200)
                self.assertEqual(body, "<html>fresh sidebar ui</html>")
                self.assertEqual(headers["cache-control"], "no-store, max-age=0")
                self.assertEqual(headers["pragma"], "no-cache")
            finally:
                server.shutdown()
                server.server_close()

    def test_static_index_remains_available_as_legacy_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "index.html").write_text("<html>legacy ui</html>")
            Path(tmp, "sidebar.html").write_text("<html>fresh sidebar ui</html>")
            server = create_server(db_path=":memory:", port=0, static_dir=tmp)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, headers, body = raw_request(server, "GET", "/index.html")
                self.assertEqual(status, 200)
                self.assertEqual(body, "<html>legacy ui</html>")
                self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
            finally:
                server.shutdown()
                server.server_close()

    def test_static_sidebar_entrypoint_is_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "index.html").write_text("<html>current ui</html>")
            Path(tmp, "sidebar.html").write_text("<html>sidebar ui</html>")
            server = create_server(db_path=":memory:", port=0, static_dir=tmp)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, headers, body = raw_request(server, "GET", "/sidebar.html")
                self.assertEqual(status, 200)
                self.assertEqual(body, "<html>sidebar ui</html>")
                self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
            finally:
                server.shutdown()
                server.server_close()

    def test_portfolio_import_evaluate_flow_over_http(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "HTTP Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]
            UUID(portfolio_id)

            csv_text = "ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n"
            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": csv_text},
            )
            self.assertEqual(status, 200)
            self.assertGreater(data["subscription_count"], 0)
            subscription_count = data["subscription_count"]

            status, data = request(server, "GET", "/portfolios/%s" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual(data["portfolio"]["name"], "HTTP Portfolio")
            self.assertEqual(data["summary"]["ticker_count"], 1)
            self.assertEqual(data["summary"]["enabled_subscription_count"], subscription_count)
            self.assertEqual(data["tickers"][0]["ticker"], "AAPL")
            self.assertEqual(data["tickers"][0]["enabled_subscription_count"], subscription_count)
            self.assertEqual(data["subscription_summary"][0]["ticker"], "AAPL")

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/evaluate" % portfolio_id,
                {"asof": "2025-05-31"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["alerts"], [])
            self.assertEqual(data["notifications"], [])

            status, data = request(server, "GET", "/portfolios/%s/notifications" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual(data["notifications"], [])

            status, data = request(server, "GET", "/portfolios/%s/tickers/AAPL" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual(data["ticker"]["ticker"], "AAPL")
            self.assertEqual(data["bars"], [])
            self.assertEqual(data["market_data"]["data_source"], "none")
            self.assertEqual(data["market_data"]["data_source_label"], "No stored bars")
            self.assertEqual(data["chart_alerts"], [])
        finally:
            server.shutdown()
            server.server_close()

    def test_evaluate_exposes_durable_run_receipt_and_alert_events_over_http(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Runs Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n"},
            )
            self.assertEqual(status, 200)

            # Use the server workspace directly to seed deterministic market data.
            workspace = server.RequestHandlerClass.api.workspace
            workspace.backfill_market_data(
                portfolio_id=UUID(portfolio_id),
                provider=InMemoryMarketDataProvider.from_items([("AAPL", p1_cross_below_sma150_bars())]),
                end=date(2025, 5, 31),
            )

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/evaluate" % portfolio_id,
                {"asof": "2025-05-31"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["run"]["status"], "success")
            self.assertEqual(data["run"]["alerts_created_count"], 1)

            status, data = request(server, "GET", "/portfolios/%s/runs/latest" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual(data["run"]["alerts_created_count"], 1)

            status, data = request(server, "GET", "/portfolios/%s/alert-events" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual([event["kind"] for event in data["events"]], ["created", "notification_queued"])
            self.assertEqual(data["events"][0]["rule_id"], "P1")

            status, data = request(server, "GET", "/portfolios/%s" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual(data["latest_run"]["alerts_created_count"], 1)
        finally:
            server.shutdown()
            server.server_close()

    def test_portfolio_detail_includes_backend_owned_holding_scores(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Scores Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {
                    "csv_text": (
                        "ticker,type,shares,entry_price,current_profit_lock\n"
                        "AAPL,investor,10,110,95\n"
                        "AAOI,investor,55,178.60,\n"
                    )
                },
            )
            self.assertEqual(status, 200)
            workspace = server.RequestHandlerClass.api.workspace
            workspace.backfill_market_data(
                portfolio_id=UUID(portfolio_id),
                provider=InMemoryMarketDataProvider.from_items([("AAPL", p1_cross_below_sma150_bars())]),
                end=date(2025, 5, 31),
            )
            request(server, "POST", "/portfolios/%s/evaluate" % portfolio_id, {"asof": "2025-05-31"})

            status, data = request(server, "GET", "/portfolios/%s" % portfolio_id)
            self.assertEqual(status, 200)
            rows = {row["ticker"]: row for row in data["tickers"]}
            aapl_scores = rows["AAPL"]["holding_scores"]
            aaoi_scores = rows["AAOI"]["holding_scores"]

            self.assertGreater(aapl_scores["exit"]["value"], aapl_scores["setup"]["value"])
            self.assertGreater(aaoi_scores["setup"]["value"], aaoi_scores["exit"]["value"])
            self.assertNotEqual(aapl_scores["rank"], aaoi_scores["rank"])
            self.assertIn("reason", aapl_scores)
            self.assertIn("components", aapl_scores)
        finally:
            server.shutdown()
            server.server_close()

    def test_notification_settings_and_external_delivery_over_http(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Notify Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n"},
            )
            self.assertEqual(status, 200)

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/notification-settings" % portfolio_id,
                {
                    "email_enabled": True,
                    "email_recipients": ["ops@example.com"],
                    "telegram_enabled": True,
                    "telegram_chat_id": "12345",
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(data["settings"]["email_enabled"])
            self.assertTrue(data["settings"]["telegram_enabled"])
            self.assertFalse(data["delivery_status"]["email_configured"])
            self.assertFalse(data["delivery_status"]["telegram_configured"])

            status, data = request(server, "GET", "/portfolios/%s/notification-settings" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual(data["settings"]["email_recipients"], ["ops@example.com"])
            self.assertEqual(data["settings"]["telegram_chat_id"], "12345")

            workspace = server.RequestHandlerClass.api.workspace
            workspace.email_provider = RecordingEmailProvider()
            workspace.telegram_provider = RecordingTelegramProvider()
            workspace.backfill_market_data(
                portfolio_id=UUID(portfolio_id),
                provider=InMemoryMarketDataProvider.from_items([("AAPL", p1_cross_below_sma150_bars())]),
                end=date(2025, 5, 31),
            )

            status, data = request(server, "POST", "/portfolios/%s/evaluate" % portfolio_id, {"asof": "2025-05-31"})
            self.assertEqual(status, 200)
            channels = sorted(notification["channel"] for notification in data["notifications"])
            self.assertEqual(channels, ["email", "in_app", "telegram"])
            statuses = {notification["channel"]: notification["status"] for notification in data["notifications"]}
            self.assertEqual(statuses, {"email": "sent", "in_app": "sent", "telegram": "sent"})
            self.assertEqual(workspace.email_provider.sent[0]["recipients"], ("ops@example.com",))
            self.assertIn("AAPL", workspace.telegram_provider.sent[0]["text"])
            self.assertIn("does not place broker orders", workspace.telegram_provider.sent[0]["text"])

            status, data = request(server, "GET", "/portfolios/%s/alert-events" % portfolio_id)
            self.assertEqual(status, 200)
            kinds = [event["kind"] for event in data["events"]]
            self.assertEqual(kinds.count("notification_queued"), 3)
            self.assertEqual(kinds.count("notification_sent"), 2)
        finally:
            server.shutdown()
            server.server_close()

    def test_external_delivery_failure_does_not_fail_monitor_run(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Failed Notify Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]
            status, _ = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n"},
            )
            self.assertEqual(status, 200)
            status, _ = request(
                server,
                "POST",
                "/portfolios/%s/notification-settings" % portfolio_id,
                {"email_enabled": True, "email_recipients": ["ops@example.com"]},
            )
            self.assertEqual(status, 200)

            workspace = server.RequestHandlerClass.api.workspace
            workspace.email_provider = FailingEmailProvider()
            workspace.backfill_market_data(
                portfolio_id=UUID(portfolio_id),
                provider=InMemoryMarketDataProvider.from_items([("AAPL", p1_cross_below_sma150_bars())]),
                end=date(2025, 5, 31),
            )

            status, data = request(server, "POST", "/portfolios/%s/evaluate" % portfolio_id, {"asof": "2025-05-31"})
            self.assertEqual(status, 200)
            self.assertEqual(data["run"]["status"], "success")
            statuses = {notification["channel"]: notification["status"] for notification in data["notifications"]}
            self.assertEqual(statuses["email"], "failed")
            self.assertEqual(statuses["in_app"], "sent")

            status, data = request(server, "GET", "/portfolios/%s/alert-events" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertIn("notification_failed", [event["kind"] for event in data["events"]])
        finally:
            server.shutdown()
            server.server_close()

    def test_notification_test_delivery_over_http(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Test Delivery Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]
            status, data = request(
                server,
                "POST",
                "/portfolios/%s/notification-settings" % portfolio_id,
                {
                    "email_enabled": True,
                    "email_recipients": ["ops@example.com"],
                    "telegram_enabled": True,
                    "telegram_chat_id": "12345",
                },
            )
            self.assertEqual(status, 200)

            workspace = server.RequestHandlerClass.api.workspace
            workspace.email_provider = RecordingEmailProvider()
            workspace.telegram_provider = RecordingTelegramProvider()

            status, data = request(server, "POST", "/portfolios/%s/notification-settings/test" % portfolio_id, {})

            self.assertEqual(status, 200)
            self.assertEqual(
                [(result["channel"], result["status"]) for result in data["results"]],
                [("email", "sent"), ("telegram", "sent")],
            )
            self.assertIn("Sentinel test notification", workspace.email_provider.sent[0]["message"].subject)
            self.assertEqual(workspace.email_provider.sent[0]["recipients"], ("ops@example.com",))
            self.assertEqual(workspace.telegram_provider.sent[0]["chat_id"], "12345")
            self.assertIn("Sentinel test notification", workspace.telegram_provider.sent[0]["text"])
        finally:
            server.shutdown()
            server.server_close()

    def test_notification_test_delivery_reports_missing_provider(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Missing Provider Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]
            status, _ = request(
                server,
                "POST",
                "/portfolios/%s/notification-settings" % portfolio_id,
                {"email_enabled": True, "email_recipients": ["ops@example.com"]},
            )
            self.assertEqual(status, 200)

            status, data = request(server, "POST", "/portfolios/%s/notification-settings/test" % portfolio_id, {})

            self.assertEqual(status, 200)
            self.assertEqual(data["results"][0]["channel"], "email")
            self.assertEqual(data["results"][0]["status"], "failed")
            self.assertIn("not configured", data["results"][0]["error"])
        finally:
            server.shutdown()
            server.server_close()

    def test_external_delivery_not_resent_for_duplicate_open_alert(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Duplicate Notify Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]
            status, _ = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n"},
            )
            self.assertEqual(status, 200)
            status, _ = request(
                server,
                "POST",
                "/portfolios/%s/notification-settings" % portfolio_id,
                {"email_enabled": True, "email_recipients": ["ops@example.com"]},
            )
            self.assertEqual(status, 200)
            workspace = server.RequestHandlerClass.api.workspace
            workspace.email_provider = RecordingEmailProvider()
            workspace.backfill_market_data(
                portfolio_id=UUID(portfolio_id),
                provider=InMemoryMarketDataProvider.from_items([("AAPL", p1_cross_below_sma150_bars())]),
                end=date(2025, 5, 31),
            )

            first_status, first_data = request(server, "POST", "/portfolios/%s/evaluate" % portfolio_id, {"asof": "2025-05-31"})
            second_status, second_data = request(server, "POST", "/portfolios/%s/evaluate" % portfolio_id, {"asof": "2025-05-31"})

            self.assertEqual(first_status, 200)
            self.assertEqual(second_status, 200)
            self.assertEqual(len(first_data["alerts"]), 1)
            self.assertEqual(second_data["alerts"], [])
            self.assertEqual(len(workspace.email_provider.sent), 1)
        finally:
            server.shutdown()
            server.server_close()

    def test_classify_ticker_over_http_rebuilds_subscriptions(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Classify Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAPL,unknown,10,110,95\n"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["subscription_count"], 3)

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/tickers/AAPL/classify" % portfolio_id,
                {"ticker_type": "investor"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["ticker"]["type"], "investor")
            self.assertEqual(data["subscription_count"], 10)
            self.assertEqual(data["portfolio_detail"]["summary"]["classification_needed_count"], 0)
            self.assertIn("P1", data["portfolio_detail"]["tickers"][0]["enabled_rule_ids"])
        finally:
            server.shutdown()
            server.server_close()

    def test_update_ticker_setup_data_over_http(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Setup Data Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAOI,investor,55,178.60,\n"},
            )
            self.assertEqual(status, 200)

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/tickers/AAOI/setup-data" % portfolio_id,
                {"current_profit_lock": "155.25"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["ticker"]["ticker"], "AAOI")
            self.assertEqual(data["ticker"]["current_profit_lock"], "155.25")
            self.assertEqual(data["portfolio_detail"]["tickers"][0]["current_profit_lock"], "155.25")

            status, data = request(server, "GET", "/portfolios/%s/tickers/AAOI" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual(data["ticker"]["current_profit_lock"], "155.25")
        finally:
            server.shutdown()
            server.server_close()

    def test_update_ticker_setup_data_rejects_non_finite_numbers(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Setup Validation"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAOI,investor,55,178.60,\n"},
            )
            self.assertEqual(status, 200)

            for payload in (
                {"entry_price": "NaN"},
                {"entry_price": "Infinity"},
                {"current_profit_lock": "-Infinity"},
            ):
                status, data = request(
                    server,
                    "POST",
                    "/portfolios/%s/tickers/AAOI/setup-data" % portfolio_id,
                    payload,
                )
                self.assertEqual(status, 400)
                self.assertEqual(data["error"], "setup data values must be valid finite numbers")

            status, data = request(server, "GET", "/portfolios/%s/tickers/AAOI" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertIsNone(data["ticker"]["current_profit_lock"])
        finally:
            server.shutdown()
            server.server_close()

    def test_update_ticker_setup_data_resolves_missing_stop_alerts_in_response(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Setup Lifecycle"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAOI,investor,55,178.60,\n"},
            )
            self.assertEqual(status, 200)

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/evaluate" % portfolio_id,
                {"asof": "2026-05-19"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                sorted(alert["result"]["rule_id"] for alert in data["alerts"]),
                ["A1", "T1"],
            )

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/tickers/AAOI/setup-data" % portfolio_id,
                {"current_profit_lock": "155.25", "asof": "2026-05-19"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["ticker"]["current_profit_lock"], "155.25")
            self.assertEqual(data["portfolio_detail"]["tickers"][0]["open_alert_count"], 0)

            status, data = request(server, "GET", "/portfolios/%s/alerts" % portfolio_id)
            self.assertEqual(status, 200)
            open_rule_ids = sorted(
                alert["result"]["rule_id"]
                for alert in data["alerts"]
                if alert["status"] in {"new", "sent"}
            )
            self.assertEqual(open_rule_ids, [])
        finally:
            server.shutdown()
            server.server_close()

    def test_setup_alerts_are_not_chart_markers_without_market_date(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Setup Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,type,shares,entry_price,current_profit_lock\nAAPL,unknown,10,110,95\n"},
            )
            self.assertEqual(status, 200)

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/evaluate" % portfolio_id,
                {"asof": "2026-05-17"},
            )
            self.assertEqual(status, 200)
            self.assertEqual([alert["result"]["rule_id"] for alert in data["alerts"]], ["C1"])

            status, data = request(server, "GET", "/portfolios/%s/tickers/AAPL" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual([alert["result"]["rule_id"] for alert in data["alerts"]], ["C1"])
            self.assertEqual(data["chart_alerts"], [])
        finally:
            server.shutdown()
            server.server_close()

    def test_bulk_classify_unknown_tickers_over_http(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Bulk Classify"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {
                    "csv_text": (
                        "ticker,type,shares,entry_price,current_profit_lock\n"
                        "AAPL,unknown,10,110,95\nMSFT,unknown,5,300,280\n"
                    )
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["subscription_count"], 6)

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/tickers/classify-unknown" % portfolio_id,
                {"ticker_type": "investor"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["updated_count"], 2)
            self.assertEqual(data["subscription_count"], 20)
            self.assertEqual(data["portfolio_detail"]["summary"]["classification_needed_count"], 0)
        finally:
            server.shutdown()
            server.server_close()

    def test_generated_backfill_route_is_not_exposed(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Bars Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/backfill-generated" % portfolio_id,
                {"end": "2025-05-31", "lookback": 20},
            )
            self.assertEqual(status, 404)
            self.assertIn("No route", data["error"])
        finally:
            server.shutdown()
            server.server_close()

    def test_massive_backfill_requires_env_key(self):
        previous = os.environ.pop("MASSIVE_API_KEY", None)
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Massive Missing Key"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/backfill-massive" % portfolio_id,
                {"end": "2025-05-31"},
            )
            self.assertEqual(status, 400)
            self.assertIn("MASSIVE_API_KEY", data["error"])
        finally:
            if previous is not None:
                os.environ["MASSIVE_API_KEY"] = previous
            server.shutdown()
            server.server_close()

    def test_massive_backfill_reports_connectivity_before_per_ticker_fetches(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Massive Offline"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(
                server,
                "POST",
                "/portfolios/%s/import" % portfolio_id,
                {"csv_text": "ticker,shares,entry_price\nAAPL,10,110\n"},
            )
            self.assertEqual(status, 200)

            original_create_connection = socket.create_connection

            def fake_create_connection(address, *args, **kwargs):
                if address[0] == "api.massive.com":
                    raise OSError("offline")
                return original_create_connection(address, *args, **kwargs)

            with patch("sentinel_core.http_api._detect_proxy_url", return_value=None), patch(
                "sentinel_core.http_api.socket.create_connection",
                side_effect=fake_create_connection,
            ):
                status, data = request(
                    server,
                    "POST",
                    "/portfolios/%s/backfill-massive" % portfolio_id,
                    {"api_key": "secret", "end": "2026-05-17"},
                )

            self.assertEqual(status, 503)
            self.assertIn("Cannot reach Massive API", data["error"])

            status, data = request(server, "GET", "/portfolios/%s/tickers/AAPL" % portfolio_id)
            self.assertEqual(status, 200)
            self.assertEqual(data["market_data"]["last_attempt_source"], "massive-stocks-aggregates")
            self.assertEqual(data["market_data"]["last_attempt_status"], "failed")
            self.assertIn("Cannot reach Massive API", data["market_data"]["last_error"])
        finally:
            server.shutdown()
            server.server_close()

    def test_chart_scenario_route_is_not_exposed(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "POST", "/portfolios", {"name": "Chart Portfolio"})
            self.assertEqual(status, 201)
            portfolio_id = data["portfolio"]["portfolio_id"]

            status, data = request(server, "POST", "/portfolios/%s/load-chart-scenario" % portfolio_id, {})
            self.assertEqual(status, 404)
            self.assertIn("No route", data["error"])
        finally:
            server.shutdown()
            server.server_close()

    def test_dev_uploaded_portfolio_fixture_endpoint_is_not_exposed(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(server, "GET", "/dev/uploaded-portfolio-csv")
            self.assertEqual(status, 404)
            self.assertIn("No route", data["error"])
        finally:
            server.shutdown()
            server.server_close()

    def test_convert_xlsx_upload_to_portfolio_csv(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "portfolio.xlsx"
                write_minimal_xlsx(path)
                content_base64 = base64.b64encode(path.read_bytes()).decode("ascii")

            status, data = request(
                server,
                "POST",
                "/portfolio-file/convert",
                {"filename": "portfolio.xlsx", "content_base64": content_base64},
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["source_format"], "xlsx")
            self.assertEqual(data["sheet_name"], "Holdings")
            self.assertIn("AAPL,investor,10,100,", data["csv_text"])
            self.assertIn("QQQ,investor,3,400,", data["csv_text"])
        finally:
            server.shutdown()
            server.server_close()

    def test_legacy_xls_upload_gets_clear_error(self):
        server = create_server(db_path=":memory:", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data = request(
                server,
                "POST",
                "/portfolio-file/convert",
                {
                    "filename": "legacy.xls",
                    "content_base64": base64.b64encode(b"not really xls").decode("ascii"),
                },
            )
            self.assertEqual(status, 415)
            self.assertIn("Legacy .xls", data["error"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
