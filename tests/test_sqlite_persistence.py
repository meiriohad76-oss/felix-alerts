from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from sentinel_core.market_data import InMemoryMarketDataProvider
from sentinel_core.persistent_service import PersistentSentinelWorkspace
from sentinel_core.sqlite_store import SQLiteStore
from tests.bar_fixtures import p1_cross_below_sma150_bars
from tests.factories import flat_bars, make_bar


class SQLiteStoreTests(unittest.TestCase):
    def test_store_serializes_concurrent_reads_on_shared_connection(self):
        class GuardedConnection(sqlite3.Connection):
            pass

        conn = sqlite3.connect(
            ":memory:",
            check_same_thread=False,
            factory=GuardedConnection,
        )
        conn.guard_lock = threading.Lock()
        conn.active_portfolio_reads = 0
        conn.concurrent_portfolio_read_seen = False
        conn.first_portfolio_read_entered = threading.Event()
        conn.release_first_portfolio_read = threading.Event()

        original_execute = conn.execute

        def guarded_execute(sql, parameters=()):
            normalized = " ".join(str(sql).split()).upper()
            should_guard = normalized.startswith("SELECT * FROM PORTFOLIOS WHERE USER_ID")
            if not should_guard:
                return original_execute(sql, parameters)

            wait_for_release = False
            with conn.guard_lock:
                conn.active_portfolio_reads += 1
                if conn.active_portfolio_reads > 1:
                    conn.concurrent_portfolio_read_seen = True
                elif not conn.first_portfolio_read_entered.is_set():
                    conn.first_portfolio_read_entered.set()
                    wait_for_release = True

            if wait_for_release:
                conn.release_first_portfolio_read.wait(timeout=2)

            try:
                return original_execute(sql, parameters)
            finally:
                with conn.guard_lock:
                    conn.active_portfolio_reads -= 1

        conn.execute = guarded_execute

        user_id = uuid4()
        store = SQLiteStore(conn)
        workspace = PersistentSentinelWorkspace(store)
        workspace.create_portfolio(user_id=user_id, name="Core")

        errors = []

        def list_portfolios():
            try:
                store.list_portfolios(user_id)
            except Exception as exc:  # pragma: no cover - failure path is asserted below
                errors.append(exc)

        first = threading.Thread(target=list_portfolios)
        second = threading.Thread(target=list_portfolios)
        first.start()
        self.assertTrue(conn.first_portfolio_read_entered.wait(timeout=1))
        second.start()
        time.sleep(0.05)
        conn.release_first_portfolio_read.set()
        first.join(timeout=1)
        second.join(timeout=1)

        self.assertEqual(errors, [])
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertFalse(
            conn.concurrent_portfolio_read_seen,
            "SQLiteStore allowed overlapping use of one SQLite connection across threads",
        )

    def test_persistent_import_survives_reopen(self):
        user_id = uuid4()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sentinel.db"
            store = SQLiteStore(db_path)
            workspace = PersistentSentinelWorkspace(store)
            portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
            report, subscriptions = workspace.import_csv(
                user_id=user_id,
                portfolio_id=portfolio.portfolio_id,
                csv_text="ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n",
            )
            store.conn.close()

            reopened = SQLiteStore(db_path)
            try:
                self.assertEqual(reopened.get_portfolio(portfolio.portfolio_id).name, "Core")
                self.assertEqual(reopened.list_tickers(portfolio.portfolio_id)[0].ticker, "AAPL")
                self.assertIn("P1", [item.rule_id for item in reopened.list_subscriptions(portfolio.portfolio_id)])
            finally:
                reopened.close()

    def test_persistent_evaluate_ack_report_flow(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n",
        )
        provider = InMemoryMarketDataProvider.from_items([("AAPL", p1_cross_below_sma150_bars())])
        workspace.backfill_market_data(
            portfolio_id=portfolio.portfolio_id,
            provider=provider,
            end=date(2025, 5, 31),
        )

        alerts = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2025, 5, 31))
        self.assertEqual(len(alerts), 1)

        updated = workspace.acknowledge_alert(
            portfolio_id=portfolio.portfolio_id,
            alert_id=alerts[0].alert_id,
            ack_kind="placed",
        )
        report = workspace.build_report(portfolio_id=portfolio.portfolio_id)

        self.assertEqual(updated.status, "acknowledged")
        self.assertEqual(report.open_alert_count, 0)
        self.assertEqual(report.scorecard_summary, {"placed": 1})

    def test_evaluate_persists_run_receipt_items_and_alert_events(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n",
        )
        provider = InMemoryMarketDataProvider.from_items([("AAPL", p1_cross_below_sma150_bars())])
        workspace.backfill_market_data(
            portfolio_id=portfolio.portfolio_id,
            provider=provider,
            end=date(2025, 5, 31),
        )

        created = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2025, 5, 31))
        latest = store.latest_monitor_run(portfolio.portfolio_id)
        events = store.list_alert_events(portfolio.portfolio_id)
        items = store.list_monitor_run_items(latest["run_id"])

        self.assertEqual(len(created), 1)
        self.assertEqual(latest["status"], "success")
        self.assertEqual(latest["stage"], "evaluate")
        self.assertEqual(latest["ticker_count"], 1)
        self.assertEqual(latest["alerts_created_count"], 1)
        self.assertEqual(latest["alerts_refreshed_count"], 0)
        self.assertEqual(latest["alerts_resolved_count"], 0)
        self.assertEqual([event["kind"] for event in events], ["created", "notification_queued"])
        self.assertEqual(events[0]["alert_id"], created[0].alert_id)
        self.assertEqual(events[0]["run_id"], latest["run_id"])
        self.assertEqual([(item["status"], item["rule_id"]) for item in items], [("created", "P1")])

    def test_notification_settings_are_durable_per_portfolio(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")

        default_settings = store.get_notification_settings(portfolio.portfolio_id)
        self.assertFalse(default_settings["email_enabled"])
        self.assertEqual(default_settings["email_recipients"], ())
        self.assertFalse(default_settings["telegram_enabled"])
        self.assertEqual(default_settings["telegram_chat_id"], "")

        saved = store.save_notification_settings(
            portfolio.portfolio_id,
            email_enabled=True,
            email_recipients=("ops@example.com", "owner@example.com"),
            telegram_enabled=True,
            telegram_chat_id="12345",
        )
        reloaded = store.get_notification_settings(portfolio.portfolio_id)

        self.assertEqual(saved, reloaded)
        self.assertTrue(reloaded["email_enabled"])
        self.assertEqual(reloaded["email_recipients"], ("ops@example.com", "owner@example.com"))
        self.assertTrue(reloaded["telegram_enabled"])
        self.assertEqual(reloaded["telegram_chat_id"], "12345")

    def test_alert_event_log_records_resolution_and_acknowledgement(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAEM,unknown,10,110,95\n",
        )

        created = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2026, 5, 17))
        workspace.classify_ticker(
            portfolio_id=portfolio.portfolio_id,
            ticker="AEM",
            ticker_type="investor",
        )
        workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2026, 5, 17))
        workspace.acknowledge_alert(
            portfolio_id=portfolio.portfolio_id,
            alert_id=created[0].alert_id,
            ack_kind="placed",
        )

        events = store.list_alert_events(portfolio.portfolio_id)
        self.assertEqual([event["kind"] for event in events], [
            "created",
            "notification_queued",
            "resolved",
            "acknowledged",
        ])
        self.assertEqual([event["rule_id"] for event in events], ["C1", "C1", "C1", "C1"])

    def test_open_alert_dedupe_persists(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAAPL,investor,10,110,95\n",
        )
        provider = InMemoryMarketDataProvider.from_items([("AAPL", p1_cross_below_sma150_bars())])
        workspace.backfill_market_data(
            portfolio_id=portfolio.portfolio_id,
            provider=provider,
            end=date(2025, 5, 31),
        )
        first = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2025, 5, 31))
        second = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2025, 5, 31))

        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())

    def test_active_setup_alert_refreshes_when_market_data_adds_suggested_stop(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nCGDV,investor,10,125,\n",
        )

        first = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2025, 5, 31))
        self.assertEqual([alert.result.rule_id for alert in first], ["T1", "A1"])
        self.assertNotIn("suggested_stop", first[1].result.payload)

        bars = list(flat_bars(150, close=100))
        bars.append(make_bar(date(2025, 5, 31), 130))
        provider = InMemoryMarketDataProvider.from_items([("CGDV", bars)])
        workspace.backfill_market_data(
            portfolio_id=portfolio.portfolio_id,
            provider=provider,
            end=date(2025, 5, 31),
        )
        second = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2025, 5, 31))

        alerts = store.list_alerts(portfolio.portfolio_id)
        refreshed_a1 = [alert for alert in alerts if alert.result.rule_id == "A1"][0]
        self.assertEqual(second, ())
        self.assertEqual(refreshed_a1.result.payload["suggested_stop"], "99.20")
        self.assertEqual(str(refreshed_a1.ticket.stop_price), "99.20")

    def test_reimport_removes_stale_subscriptions(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nVOO,index,10,400,\n",
        )
        self.assertIn("A7", [item.rule_id for item in store.list_subscriptions(portfolio.portfolio_id)])

        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nVOO,unknown,10,400,\n",
        )

        rule_ids = [item.rule_id for item in store.list_subscriptions(portfolio.portfolio_id)]
        self.assertNotIn("A7", rule_ids)
        self.assertIn("C1", rule_ids)

    def test_classifying_ticker_rebuilds_playbook_subscriptions(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAAPL,unknown,10,110,95\n",
        )
        self.assertEqual(
            [item.rule_id for item in store.list_subscriptions(portfolio.portfolio_id)],
            ["C1", "P7", "T1"],
        )

        ticker, subscriptions = workspace.classify_ticker(
            portfolio_id=portfolio.portfolio_id,
            ticker="AAPL",
            ticker_type="investor",
        )

        rule_ids = [item.rule_id for item in subscriptions]
        self.assertEqual(ticker.type, "investor")
        self.assertIn("P1", rule_ids)
        self.assertNotIn("P2", rule_ids)
        self.assertEqual(len(rule_ids), 10)

    def test_bulk_classify_unknown_tickers_rebuilds_subscriptions(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAAPL,unknown,10,110,95\nMSFT,unknown,5,300,280\n",
        )

        updated, subscriptions = workspace.classify_unknown_tickers(
            portfolio_id=portfolio.portfolio_id,
            ticker_type="investor",
        )

        self.assertEqual(len(updated), 2)
        self.assertEqual({ticker.type for ticker in store.list_tickers(portfolio.portfolio_id)}, {"investor"})
        self.assertEqual(len(subscriptions), 20)

    def test_replace_mode_import_deletes_subscriptions_for_inactive_tickers(self):
        from sentinel_core.persistent_service import PersistentSentinelWorkspace
        from sentinel_core.sqlite_store import SQLiteStore
        from uuid import uuid4

        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        user_id = uuid4()
        portfolio = workspace.create_portfolio(user_id=user_id, name="Test")
        pid = portfolio.portfolio_id

        # Import AAPL and MSFT in merge mode (default)
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=pid,
            csv_text="ticker\nAAPL\nMSFT\n",
        )
        subs_before = store.list_subscriptions(pid)
        msft_before = [s for s in subs_before if s.ticker == "MSFT"]
        self.assertGreater(len(msft_before), 0, "MSFT should have subscriptions after initial import")

        # Replace-import with AAPL only — MSFT becomes inactive
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=pid,
            csv_text="ticker\nAAPL\n",
            mode="replace",
        )
        subs_after = store.list_subscriptions(pid)
        aapl_after = [s for s in subs_after if s.ticker == "AAPL"]
        msft_after = [s for s in subs_after if s.ticker == "MSFT"]

        self.assertGreater(len(aapl_after), 0, "AAPL subscriptions must be preserved")
        self.assertEqual(len(msft_after), 0, "MSFT subscriptions must be deleted when ticker goes inactive")

    def test_evaluate_resolves_setup_alert_after_condition_is_fixed(self):
        user_id = uuid4()
        store = SQLiteStore.in_memory()
        workspace = PersistentSentinelWorkspace(store)
        portfolio = workspace.create_portfolio(user_id=user_id, name="Core")
        workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio.portfolio_id,
            csv_text="ticker,type,shares,entry_price,current_profit_lock\nAEM,unknown,10,110,95\n",
        )

        created = workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2026, 5, 17))
        self.assertEqual([alert.result.rule_id for alert in created], ["C1"])
        self.assertEqual(store.list_alerts(portfolio.portfolio_id)[0].status, "new")

        workspace.classify_ticker(
            portfolio_id=portfolio.portfolio_id,
            ticker="AEM",
            ticker_type="investor",
        )
        workspace.evaluate_portfolio(portfolio_id=portfolio.portfolio_id, asof=date(2026, 5, 17))

        alerts = store.list_alerts(portfolio.portfolio_id)
        self.assertEqual([(alert.result.rule_id, alert.status) for alert in alerts], [("C1", "resolved")])


if __name__ == "__main__":
    unittest.main()
