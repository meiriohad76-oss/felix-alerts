from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Set
from uuid import NAMESPACE_URL, UUID, uuid5

from .models import AlertSubscription, PortfolioTickerView


UNKNOWN_RULES = ("C1", "P7", "T1")
INVESTOR_RULES = ("C1", "P1", "T4", "P7", "T1", "T5", "A1", "A5", "A6", "A8")
TRADER_RULES = ("C1", "P2", "T4", "P7", "T1", "T5", "A1", "A5", "A6", "A8")
INDEX_RULES = ("C1", "A7", "P7")


def applicable_rule_ids(ticker: PortfolioTickerView) -> Sequence[str]:
    if ticker.type == "investor":
        return INVESTOR_RULES
    if ticker.type == "trader":
        return TRADER_RULES
    if ticker.type == "index":
        return INDEX_RULES
    return UNKNOWN_RULES


def stable_subscription_id(portfolio_id: UUID, ticker: str, rule_id: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "sentinel:alert-subscription:%s:%s:%s" % (portfolio_id, ticker, rule_id),
    )


def create_subscriptions_for_ticker(
    ticker: PortfolioTickerView,
    *,
    created_from_import_id: Optional[UUID] = None,
    existing: Iterable[AlertSubscription] = (),
) -> List[AlertSubscription]:
    """Create missing subscriptions for a ticker.

    The return value contains existing matching subscriptions plus newly-created
    ones, deduped by `(portfolio_id, ticker, rule_id)`.
    """

    existing_by_rule = {
        subscription.rule_id: subscription
        for subscription in existing
        if subscription.portfolio_id == ticker.portfolio_id and subscription.ticker == ticker.ticker
    }
    output: List[AlertSubscription] = []
    for rule_id in applicable_rule_ids(ticker):
        existing_subscription = existing_by_rule.get(rule_id)
        if existing_subscription:
            output.append(existing_subscription)
            continue
        output.append(
            AlertSubscription(
                subscription_id=stable_subscription_id(ticker.portfolio_id, ticker.ticker, rule_id),
                user_id=ticker.user_id,
                portfolio_id=ticker.portfolio_id,
                portfolio_ticker_id=ticker.portfolio_ticker_id,
                ticker=ticker.ticker,
                rule_id=rule_id,
                enabled=True,
                created_from_import_id=created_from_import_id,
            )
        )
    return output


def create_subscriptions_for_portfolio(
    tickers: Iterable[PortfolioTickerView],
    *,
    created_from_import_id: Optional[UUID] = None,
    existing: Iterable[AlertSubscription] = (),
) -> List[AlertSubscription]:
    tickers_list = list(tickers)
    inactive = [t.ticker for t in tickers_list if t.status != "active"]
    if inactive:
        raise ValueError(
            "create_subscriptions_for_portfolio received inactive tickers: %s. "
            "Filter to active tickers before calling." % ", ".join(sorted(inactive))
        )
    existing_list = list(existing)
    subscriptions: List[AlertSubscription] = []
    seen: Set[UUID] = set()
    for ticker in tickers_list:
        for subscription in create_subscriptions_for_ticker(
            ticker,
            created_from_import_id=created_from_import_id,
            existing=existing_list + subscriptions,
        ):
            if subscription.subscription_id in seen:
                continue
            subscriptions.append(subscription)
            seen.add(subscription.subscription_id)
    return subscriptions

