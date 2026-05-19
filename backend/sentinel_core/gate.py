from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, Optional

from .indicators import distance_pct, index_at_or_before, sma_adj_close
from .models import Bar, TickerType, ValidationIssue, ValidationResult

BROAD_INDEX_ETFS = {"VOO", "IVV", "VTI", "VT", "VXUS", "ITOT", "SCHB", "DIA"}


def classify_ticker(ticker: str, *, realized_volatility_60d: Optional[Decimal] = None) -> TickerType:
    symbol = ticker.upper()
    if symbol in BROAD_INDEX_ETFS:
        return "index"
    if realized_volatility_60d is not None and realized_volatility_60d > Decimal("0.35"):
        return "trader"
    return "unknown"


def validate_new_position(
    *,
    ticker: str,
    ticker_type: TickerType,
    qty: Decimal,
    entry_price: Decimal,
    exit_price: Optional[Decimal],
    portfolio_value: Decimal,
    cash_available: Optional[Decimal] = None,
    bars: Iterable[Bar] = (),
    margin_used: bool = False,
    fundamentals_ok: bool = True,
) -> ValidationResult:
    blockers = []
    warnings = []
    bars_tuple = tuple(bars)
    symbol = ticker.upper()

    if ticker_type == "unknown":
        blockers.append(
            ValidationIssue(
                "C1",
                "blocker",
                "Classify %s as Investor, Trader, or Index before entry." % symbol,
            )
        )

    if exit_price is None:
        blockers.append(
            ValidationIssue(
                "T1",
                "blocker",
                "Enter an exit/profit-lock price before opening %s." % symbol,
            )
        )

    if ticker_type in {"investor", "trader"} and bars_tuple:
        idx = len(bars_tuple) - 1
        period = 150 if ticker_type == "investor" else 50
        exit_ma = sma_adj_close(bars_tuple, idx, period)
        if exit_ma is not None and bars_tuple[idx].adj_close < exit_ma:
            blockers.append(
                ValidationIssue(
                    "P4",
                    "blocker",
                    "%s is below its %s-day exit moving average." % (symbol, period),
                    {
                        "close": str(bars_tuple[idx].adj_close),
                        "exit_ma": str(exit_ma),
                        "distance_pct": str(distance_pct(bars_tuple[idx].adj_close, exit_ma)),
                    },
                )
            )

    notional = qty * entry_price
    if portfolio_value > 0 and notional > portfolio_value * Decimal("0.05"):
        blockers.append(
            ValidationIssue(
                "A5",
                "blocker",
                "%s exceeds the 5%% notional position cap." % symbol,
                {"notional": str(notional), "portfolio_value": str(portfolio_value)},
            )
        )

    if exit_price is not None and portfolio_value > 0:
        position_risk = max(entry_price - exit_price, Decimal("0")) * qty
        if position_risk > portfolio_value * Decimal("0.015"):
            blockers.append(
                ValidationIssue(
                    "A5",
                    "blocker",
                    "%s exceeds the 1.5%% portfolio risk cap." % symbol,
                    {"position_risk": str(position_risk), "portfolio_value": str(portfolio_value)},
                )
            )
        elif position_risk > portfolio_value * Decimal("0.01"):
            warnings.append(
                ValidationIssue(
                    "A5",
                    "warning",
                    "%s is above the preferred 1%% risk target." % symbol,
                    {"position_risk": str(position_risk), "portfolio_value": str(portfolio_value)},
                )
            )

    if margin_used or (cash_available is not None and notional > cash_available):
        blockers.append(
            ValidationIssue(
                "A6",
                "blocker",
                "%s would require or use margin." % symbol,
                {"notional": str(notional), "cash_available": str(cash_available) if cash_available is not None else None},
            )
        )

    if not fundamentals_ok:
        warnings.append(
            ValidationIssue(
                "T3",
                "warning",
                "%s has a fundamentals warning. This does not change exit rules." % symbol,
            )
        )

    return ValidationResult(ok=not blockers, blockers=tuple(blockers), warnings=tuple(warnings))
