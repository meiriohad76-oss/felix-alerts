from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sentinel_core.models import Bar, Pivot, PortfolioTickerView


USER_ID = uuid4()
PORTFOLIO_ID = uuid4()


def dec(value) -> Decimal:
    return Decimal(str(value))


def make_bar(day: date, close, open_price=None, high=None, low=None, volume=1000) -> Bar:
    close_d = dec(close)
    open_d = dec(open_price if open_price is not None else close)
    high_d = dec(high if high is not None else max(open_d, close_d))
    low_d = dec(low if low is not None else min(open_d, close_d))
    return Bar(day, open_d, high_d, low_d, close_d, close_d, int(volume))


def flat_bars(count: int, close=100, volume=1000, start=date(2025, 1, 1)):
    return tuple(make_bar(start + timedelta(days=idx), close, volume=volume) for idx in range(count))


def ticker_view(ticker="AAPL", type="investor", **kwargs) -> PortfolioTickerView:
    return PortfolioTickerView(
        portfolio_id=kwargs.pop("portfolio_id", PORTFOLIO_ID),
        portfolio_ticker_id=kwargs.pop("portfolio_ticker_id", uuid4()),
        user_id=kwargs.pop("user_id", USER_ID),
        ticker=ticker,
        type=type,
        **kwargs,
    )


def pivot_low(day: date, price) -> Pivot:
    return Pivot(day, "low", dec(price), 2)

