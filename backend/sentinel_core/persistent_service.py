from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Tuple
from uuid import UUID, uuid4

from .alerts import materialize_alerts, refresh_existing_open_alerts
from .csv_import import import_portfolio_csv
from .market_data import MarketDataPort
from .models import AlertRecord, Portfolio
from .notifications import (
    email_provider_from_environment,
    external_notifications_for_alerts,
    notifications_for_alerts,
    render_alert_email,
    render_alert_telegram,
    telegram_provider_from_environment,
)
from .reports import build_portfolio_report
from .scorecard import acknowledge_alert, stale_exit_events
from .signals import evaluate_ticker
from .sqlite_store import SQLiteStore
from .subscriptions import create_subscriptions_for_portfolio

VALID_TICKER_TYPES = {"investor", "trader", "index", "unknown"}


class PersistentSentinelWorkspace:
    def __init__(self, store: SQLiteStore, *, email_provider=None, telegram_provider=None) -> None:
        self.store = store
        self.email_provider = email_provider if email_provider is not None else email_provider_from_environment()
        self.telegram_provider = telegram_provider if telegram_provider is not None else telegram_provider_from_environment()

    def create_portfolio(self, *, user_id: UUID, name: str) -> Portfolio:
        portfolio = Portfolio(portfolio_id=uuid4(), user_id=user_id, name=name)
        self.store.save_portfolio(portfolio)
        return portfolio

    def import_csv(self, *, user_id: UUID, portfolio_id: UUID, csv_text: str, mode: str = "merge"):
        existing = self.store.list_tickers(portfolio_id)
        report = import_portfolio_csv(
            csv_text,
            user_id=user_id,
            portfolio_id=portfolio_id,
            existing=existing,
            mode=mode,
        )
        self.store.save_tickers(report.tickers)
        active_tickers = [t for t in report.tickers if t.status == "active"]
        subscriptions = create_subscriptions_for_portfolio(
            active_tickers,
            created_from_import_id=report.import_id,
            existing=self.store.list_subscriptions(portfolio_id),
        )
        self.store.replace_subscriptions(portfolio_id, subscriptions)
        return report, tuple(subscriptions)

    def preview_csv(self, *, user_id: UUID, portfolio_id: UUID, csv_text: str, mode: str = "merge"):
        return import_portfolio_csv(
            csv_text,
            user_id=user_id,
            portfolio_id=portfolio_id,
            existing=self.store.list_tickers(portfolio_id),
            mode=mode,
        )

    def classify_ticker(self, *, portfolio_id: UUID, ticker: str, ticker_type: str):
        if ticker_type not in VALID_TICKER_TYPES:
            raise ValueError("ticker_type must be investor, trader, index, or unknown")

        symbol = ticker.strip().upper()
        current = None
        for portfolio_ticker in self.store.list_tickers(portfolio_id):
            if portfolio_ticker.ticker == symbol:
                current = portfolio_ticker
                break
        if current is None:
            raise KeyError("Unknown ticker for portfolio: %s" % symbol)

        updated = replace(current, type=ticker_type)
        self.store.save_tickers([updated])
        tickers = self.store.list_tickers(portfolio_id)
        active_tickers = [t for t in tickers if t.status == "active"]
        subscriptions = create_subscriptions_for_portfolio(
            active_tickers,
            existing=self.store.list_subscriptions(portfolio_id),
        )
        self.store.replace_subscriptions(portfolio_id, subscriptions)
        return updated, tuple(subscriptions)

    def classify_unknown_tickers(self, *, portfolio_id: UUID, ticker_type: str = "investor"):
        if ticker_type not in {"investor", "trader", "index"}:
            raise ValueError("ticker_type must be investor, trader, or index")

        tickers = self.store.list_tickers(portfolio_id)
        updated = [replace(ticker, type=ticker_type) for ticker in tickers if ticker.type == "unknown"]
        if updated:
            self.store.save_tickers(updated)
            tickers = self.store.list_tickers(portfolio_id)
            active_tickers = [t for t in tickers if t.status == "active"]
            subscriptions = create_subscriptions_for_portfolio(
                active_tickers,
                existing=self.store.list_subscriptions(portfolio_id),
            )
            self.store.replace_subscriptions(portfolio_id, subscriptions)
        else:
            subscriptions = self.store.list_subscriptions(portfolio_id)
        return tuple(updated), tuple(subscriptions)

    def update_ticker_setup_data(
        self,
        *,
        portfolio_id: UUID,
        ticker: str,
        entry_price: Decimal | None = None,
        current_profit_lock: Decimal | None = None,
    ):
        symbol = ticker.strip().upper()
        current = None
        for portfolio_ticker in self.store.list_tickers(portfolio_id):
            if portfolio_ticker.ticker == symbol:
                current = portfolio_ticker
                break
        if current is None:
            raise KeyError("Unknown ticker for portfolio: %s" % symbol)

        updated = replace(
            current,
            entry_price=entry_price if entry_price is not None else current.entry_price,
            current_profit_lock=(
                current_profit_lock
                if current_profit_lock is not None
                else current.current_profit_lock
            ),
            user_exit_price=(
                current_profit_lock
                if current_profit_lock is not None
                else current.user_exit_price
            ),
        )
        self.store.save_tickers([updated])
        return updated

    def backfill_market_data(
        self,
        *,
        portfolio_id: UUID,
        provider: MarketDataPort,
        end: date,
        lookback: int = 250,
        source: str | None = None,
        source_label: str | None = None,
    ) -> Tuple[str, ...]:
        updated = []
        for ticker in self.store.list_tickers(portfolio_id, include_inactive=False):
            if not provider.validate_symbol(ticker.ticker):
                continue
            bars = provider.get_bars(ticker.ticker, end=end, lookback=lookback)
            if not bars:
                continue
            self.store.save_bars(
                ticker.ticker,
                bars,
                source=source,
                source_label=source_label,
            )
            updated.append(ticker.ticker)
        return tuple(updated)

    def evaluate_portfolio(self, *, portfolio_id: UUID, asof: date) -> Tuple[AlertRecord, ...]:
        created = []
        refreshed = []
        active_dedupe_keys = set()
        existing_alerts = list(self.store.list_alerts(portfolio_id))
        subscriptions = self.store.list_subscriptions(portfolio_id)
        tickers = self.store.list_tickers(portfolio_id, include_inactive=False)
        user_id = tickers[0].user_id if tickers else self.store.get_portfolio(portfolio_id).user_id
        run = self.store.start_monitor_run(
            user_id=user_id,
            portfolio_id=portfolio_id,
            asof=asof,
            ticker_count=len(tickers),
        )
        run_id = run["run_id"]
        try:
            for ticker in tickers:
                ticker_subscriptions = tuple(
                    subscription
                    for subscription in subscriptions
                    if subscription.portfolio_ticker_id == ticker.portfolio_ticker_id
                )
                results = evaluate_ticker(ticker, asof=asof, subscriptions=ticker_subscriptions)
                active_dedupe_keys.update(
                    result.dedupe_key for result in results if result.triggered or result.state_active
                )
                refreshed.extend(
                    refresh_existing_open_alerts(
                        ticker=ticker,
                        results=results,
                        existing_alerts=existing_alerts,
                    )
                )
                records = materialize_alerts(
                    ticker=ticker,
                    results=results,
                    existing_alerts=existing_alerts + created,
                )
                created.extend(records)
            resolved = self.store.resolve_stale_open_alerts(portfolio_id, active_dedupe_keys)
            self.store.save_alerts(refreshed)
            self.store.save_alerts(created)
            # Wire stale exit scorecard events — deferred (48 h) and missed (7 d)
            # Uses existing_alerts (pre-run snapshot) so resolved alerts are still included.
            open_exit_alerts = [
                a for a in existing_alerts
                if a.status in {"new", "sent"} and a.result.kind == "exit"
            ]
            for stale_event in stale_exit_events(open_exit_alerts):
                self.store.save_scorecard_event_if_not_exists(stale_event)
            notification_settings = self.store.get_notification_settings(portfolio_id)
            notifications = (
                notifications_for_alerts(created)
                + external_notifications_for_alerts(created, notification_settings)
            )
            self.store.save_notifications(notifications)
            for alert in created:
                self.store.save_monitor_run_item(run_id=run_id, alert=alert, status="created")
                self.store.save_alert_event(alert, kind="created", run_id=run_id)
            for alert in refreshed:
                self.store.save_monitor_run_item(run_id=run_id, alert=alert, status="refreshed")
                self.store.save_alert_event(alert, kind="refreshed", run_id=run_id)
            for alert in resolved:
                self.store.save_monitor_run_item(run_id=run_id, alert=alert, status="resolved")
                self.store.save_alert_event(alert, kind="resolved", run_id=run_id)
            alert_by_id = {alert.alert_id: alert for alert in created}
            for notification in notifications:
                alert = alert_by_id.get(notification.alert_id)
                if alert is not None:
                    self.store.save_alert_event(
                        alert,
                        kind="notification_queued",
                        run_id=run_id,
                        payload={"channel": notification.channel, "notification_id": notification.notification_id},
                    )
            delivered_notifications = self._deliver_external_notifications(
                notifications,
                alert_by_id=alert_by_id,
                settings=notification_settings,
                run_id=run_id,
            )
            if delivered_notifications:
                self.store.save_notifications(delivered_notifications)
            self.store.finish_monitor_run(
                run_id,
                status="success",
                alerts_created_count=len(created),
                alerts_refreshed_count=len(refreshed),
                alerts_resolved_count=len(resolved),
                notifications_count=len(notifications),
            )
            return tuple(created)
        except Exception as exc:
            self.store.finish_monitor_run(run_id, status="failed", error=str(exc))
            raise

    def _deliver_external_notifications(
        self,
        notifications,
        *,
        alert_by_id: dict,
        settings: dict,
        run_id: UUID,
    ) -> Tuple[object, ...]:
        delivered = []
        email_recipients = tuple(settings.get("email_recipients") or ())
        telegram_chat_id = str(settings.get("telegram_chat_id") or "").strip()
        for notification in notifications:
            if notification.channel not in {"email", "telegram"}:
                continue
            alert = alert_by_id.get(notification.alert_id)
            if alert is None:
                continue
            try:
                if notification.channel == "email":
                    if self.email_provider is None:
                        raise RuntimeError("Email provider is not configured.")
                    provider_response = self.email_provider.send(render_alert_email(alert), email_recipients)
                else:
                    if self.telegram_provider is None:
                        raise RuntimeError("Telegram provider is not configured.")
                    provider_response = self.telegram_provider.send(
                        telegram_chat_id,
                        render_alert_telegram(alert),
                    )
                updated = replace(
                    notification,
                    status="sent",
                    error="",
                    provider_response=str(provider_response or ""),
                )
                event_kind = "notification_sent"
                event_payload = {
                    "channel": notification.channel,
                    "notification_id": notification.notification_id,
                    "provider_response": str(provider_response or ""),
                }
            except Exception as exc:
                updated = replace(
                    notification,
                    status="failed",
                    retry_count=notification.retry_count + 1,
                    error=str(exc),
                )
                event_kind = "notification_failed"
                event_payload = {
                    "channel": notification.channel,
                    "notification_id": notification.notification_id,
                    "error": str(exc),
                }
            delivered.append(updated)
            self.store.save_alert_event(alert, kind=event_kind, run_id=run_id, payload=event_payload)
        return tuple(delivered)

    def acknowledge_alert(self, *, portfolio_id: UUID, alert_id: UUID, ack_kind, note: str = "") -> AlertRecord:
        alert = self.store.get_alert(portfolio_id, alert_id)
        if alert is None:
            raise KeyError("Unknown alert id for portfolio: %s" % alert_id)
        updated, event = acknowledge_alert(alert, ack_kind=ack_kind, note=note)
        self.store.save_alert(updated)
        self.store.save_alert_event(updated, kind="acknowledged", payload={"ack_kind": ack_kind, "note": note})
        if event is not None:
            self.store.save_scorecard_event(event)
        return updated

    def list_alerts(self, *, portfolio_id: UUID):
        return self.store.list_alerts(portfolio_id)

    def list_notifications(self, *, portfolio_id: UUID):
        return self.store.list_notifications(portfolio_id)

    def build_report(self, *, portfolio_id: UUID):
        return build_portfolio_report(
            portfolio_id=portfolio_id,
            alerts=self.store.list_alerts(portfolio_id),
            scorecard_events=self.store.list_scorecard_events(portfolio_id),
        )
