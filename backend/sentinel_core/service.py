from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import UUID, uuid4

from .alerts import materialize_alerts, refresh_existing_open_alerts
from .csv_import import import_portfolio_csv
from .models import AlertRecord, AlertSubscription, Bar, Pivot, Portfolio, PortfolioTickerView
from .market_data import MarketDataPort
from .reports import build_portfolio_report
from .scorecard import acknowledge_alert
from .signals import evaluate_ticker
from .subscriptions import create_subscriptions_for_portfolio


class SentinelWorkspace:
    """Small in-memory application service for the first vertical slice.

    This is not the final persistence layer. It lets us exercise the product
    flow end to end while database/API tickets are still pending.
    """

    def __init__(self) -> None:
        self.portfolios: Dict[UUID, Portfolio] = {}
        self.tickers_by_portfolio: Dict[UUID, Dict[str, PortfolioTickerView]] = {}
        self.subscriptions_by_portfolio: Dict[UUID, List[AlertSubscription]] = {}
        self.alerts_by_portfolio: Dict[UUID, List[AlertRecord]] = {}
        self.scorecard_events_by_portfolio = {}

    def create_portfolio(self, *, user_id: UUID, name: str) -> Portfolio:
        portfolio = Portfolio(portfolio_id=uuid4(), user_id=user_id, name=name)
        self.portfolios[portfolio.portfolio_id] = portfolio
        self.tickers_by_portfolio[portfolio.portfolio_id] = {}
        self.subscriptions_by_portfolio[portfolio.portfolio_id] = []
        self.alerts_by_portfolio[portfolio.portfolio_id] = []
        self.scorecard_events_by_portfolio[portfolio.portfolio_id] = []
        return portfolio

    def import_csv(
        self,
        *,
        user_id: UUID,
        portfolio_id: UUID,
        csv_text: str,
        mode: str = "merge",
    ):
        existing = tuple(self.tickers_by_portfolio.get(portfolio_id, {}).values())
        report = import_portfolio_csv(
            csv_text,
            user_id=user_id,
            portfolio_id=portfolio_id,
            existing=existing,
            mode=mode,
        )
        self.tickers_by_portfolio[portfolio_id] = {ticker.ticker: ticker for ticker in report.tickers}
        subscriptions = create_subscriptions_for_portfolio(
            report.tickers,
            created_from_import_id=report.import_id,
            existing=self.subscriptions_by_portfolio.get(portfolio_id, ()),
        )
        self.subscriptions_by_portfolio[portfolio_id] = subscriptions
        return report, subscriptions

    def preview_csv(
        self,
        *,
        user_id: UUID,
        portfolio_id: UUID,
        csv_text: str,
        mode: str = "merge",
    ):
        existing = tuple(self.tickers_by_portfolio.get(portfolio_id, {}).values())
        return import_portfolio_csv(
            csv_text,
            user_id=user_id,
            portfolio_id=portfolio_id,
            existing=existing,
            mode=mode,
        )

    def set_market_data(
        self,
        *,
        portfolio_id: UUID,
        ticker_symbol: str,
        bars: Iterable[Bar],
        pivots: Iterable[Pivot] = (),
    ) -> PortfolioTickerView:
        ticker_key = ticker_symbol.upper()
        ticker = self.tickers_by_portfolio[portfolio_id][ticker_key]
        updated = replace(ticker, bars=tuple(bars), swing_pivots=tuple(pivots))
        self.tickers_by_portfolio[portfolio_id][ticker_key] = updated
        return updated

    def backfill_market_data(
        self,
        *,
        portfolio_id: UUID,
        provider: MarketDataPort,
        end: date,
        lookback: int = 250,
    ) -> Tuple[str, ...]:
        updated_symbols = []
        for ticker_symbol in sorted(self.tickers_by_portfolio.get(portfolio_id, {})):
            if not provider.validate_symbol(ticker_symbol):
                continue
            bars = provider.get_bars(ticker_symbol, end=end, lookback=lookback)
            if not bars:
                continue
            self.set_market_data(portfolio_id=portfolio_id, ticker_symbol=ticker_symbol, bars=bars)
            updated_symbols.append(ticker_symbol)
        return tuple(updated_symbols)

    def update_ticker(self, *, portfolio_id: UUID, ticker_symbol: str, **changes) -> PortfolioTickerView:
        ticker_key = ticker_symbol.upper()
        ticker = self.tickers_by_portfolio[portfolio_id][ticker_key]
        updated = replace(ticker, **changes)
        self.tickers_by_portfolio[portfolio_id][ticker_key] = updated
        self.subscriptions_by_portfolio[portfolio_id] = create_subscriptions_for_portfolio(
            self.tickers_by_portfolio[portfolio_id].values(),
            existing=self.subscriptions_by_portfolio.get(portfolio_id, ()),
        )
        return updated

    def evaluate_portfolio(self, *, portfolio_id: UUID, asof: date) -> List[AlertRecord]:
        created: List[AlertRecord] = []
        existing_alerts = self.alerts_by_portfolio.get(portfolio_id, [])
        subscriptions = self.subscriptions_by_portfolio.get(portfolio_id, [])
        for ticker in self.tickers_by_portfolio.get(portfolio_id, {}).values():
            ticker_subscriptions = [
                subscription
                for subscription in subscriptions
                if subscription.portfolio_ticker_id == ticker.portfolio_ticker_id
            ]
            results = evaluate_ticker(ticker, asof=asof, subscriptions=ticker_subscriptions)
            refreshed = refresh_existing_open_alerts(
                ticker=ticker,
                results=results,
                existing_alerts=existing_alerts,
            )
            if refreshed:
                by_id = {alert.alert_id: alert for alert in existing_alerts}
                by_id.update({alert.alert_id: alert for alert in refreshed})
                existing_alerts = list(by_id.values())
            records = materialize_alerts(
                ticker=ticker,
                results=results,
                existing_alerts=existing_alerts + created,
            )
            created.extend(records)
        if created or existing_alerts:
            self.alerts_by_portfolio[portfolio_id] = existing_alerts + created
        return created

    def list_alerts(self, *, portfolio_id: UUID) -> Tuple[AlertRecord, ...]:
        return tuple(self.alerts_by_portfolio.get(portfolio_id, ()))

    def acknowledge_alert(self, *, portfolio_id: UUID, alert_id: UUID, ack_kind, note: str = "") -> AlertRecord:
        alerts = self.alerts_by_portfolio.get(portfolio_id, [])
        for idx, alert in enumerate(alerts):
            if alert.alert_id != alert_id:
                continue
            updated, event = acknowledge_alert(alert, ack_kind=ack_kind, note=note)
            alerts[idx] = updated
            if event is not None:
                self.scorecard_events_by_portfolio.setdefault(portfolio_id, []).append(event)
            return updated
        raise KeyError("Unknown alert id for portfolio: %s" % alert_id)

    def list_scorecard_events(self, *, portfolio_id: UUID):
        return tuple(self.scorecard_events_by_portfolio.get(portfolio_id, ()))

    def build_report(self, *, portfolio_id: UUID):
        return build_portfolio_report(
            portfolio_id=portfolio_id,
            alerts=self.alerts_by_portfolio.get(portfolio_id, ()),
            scorecard_events=self.scorecard_events_by_portfolio.get(portfolio_id, ()),
        )
