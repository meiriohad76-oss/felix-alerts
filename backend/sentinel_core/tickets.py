from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .models import AccountAllocation, OrderTicket, PortfolioTickerView, RuleResult


def _shares_for_ticket(ticker: PortfolioTickerView) -> Optional[Decimal]:
    if ticker.shares is None or ticker.shares <= 0:
        return None
    return ticker.shares


def generate_order_ticket(ticker: PortfolioTickerView, result: RuleResult) -> Optional[OrderTicket]:
    shares = _shares_for_ticket(ticker)
    if shares is None:
        return None

    allocations = ()
    if ticker.account_ids:
        per_account = shares / Decimal(len(ticker.account_ids))
        allocations = tuple(AccountAllocation(account_id, per_account) for account_id in ticker.account_ids)

    if result.kind == "exit":
        return OrderTicket(
            ticker=ticker.ticker,
            action="sell",
            qty=shares,
            order_type="market",
            rationale_rule_ids=(result.rule_id,),
            account_allocations=allocations,
            copy_text="SELL %s %s MARKET" % (shares, ticker.ticker),
        )

    if result.kind == "raise_lock":
        proposed = result.payload.get("proposed_profit_lock")
        if proposed is None:
            return None
        stop_price = Decimal(str(proposed))
        return OrderTicket(
            ticker=ticker.ticker,
            action="modify_stop",
            qty=shares,
            order_type="stop",
            stop_price=stop_price,
            time_in_force="gtc",
            rationale_rule_ids=(result.rule_id,),
            account_allocations=allocations,
            copy_text="MODIFY %s STOP TO %s FOR %s SHARES" % (ticker.ticker, stop_price, shares),
        )

    if result.rule_id == "A1":
        suggested_stop = result.payload.get("suggested_stop") or ticker.current_profit_lock
        if suggested_stop is None:
            return None
        stop_price = Decimal(str(suggested_stop))
        return OrderTicket(
            ticker=ticker.ticker,
            action="place_stop",
            qty=shares,
            order_type="stop",
            stop_price=stop_price,
            time_in_force="gtc",
            rationale_rule_ids=(result.rule_id,),
            account_allocations=allocations,
            copy_text="PLACE STOP %s AT %s FOR %s SHARES" % (ticker.ticker, stop_price, shares),
        )

    return None

