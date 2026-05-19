from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, List, Optional, Set
from uuid import UUID

from .indicators import (
    average_volume_previous,
    crossed_below,
    detect_swing_pivots,
    distance_pct,
    index_at_or_before,
    latest_pivot_low,
    quantize_price,
    sma_adj_close,
)
from .models import AlertSubscription, PortfolioTickerView, RuleResult

DEFAULT_STOP_BUFFER = Decimal("0.01")


def _subscription_id_for(rule_id: str, subscriptions: Iterable[AlertSubscription]) -> Optional[UUID]:
    for subscription in subscriptions:
        if subscription.rule_id == rule_id and subscription.enabled:
            return subscription.subscription_id
    return None


def _enabled_rule_ids(subscriptions: Optional[Iterable[AlertSubscription]]) -> Optional[Set[str]]:
    if subscriptions is None:
        return None
    return {subscription.rule_id for subscription in subscriptions if subscription.enabled}


def _is_enabled(rule_id: str, enabled_rule_ids: Optional[Set[str]]) -> bool:
    return enabled_rule_ids is None or rule_id in enabled_rule_ids


def _result(
    ticker: PortfolioTickerView,
    rule_id: str,
    kind,
    severity,
    triggered: bool,
    state_active: bool,
    suggested_action: str,
    payload: dict,
    *,
    subscriptions: Iterable[AlertSubscription] = (),
    dedupe_key: str = "",
) -> RuleResult:
    return RuleResult(
        user_id=ticker.user_id,
        portfolio_id=ticker.portfolio_id,
        portfolio_ticker_id=ticker.portfolio_ticker_id,
        ticker=ticker.ticker,
        rule_id=rule_id,
        kind=kind,
        severity=severity,
        triggered=triggered,
        state_active=state_active,
        suggested_action=suggested_action,
        payload=payload,
        subscription_id=_subscription_id_for(rule_id, subscriptions),
        dedupe_key=dedupe_key or "%s:%s:%s" % (ticker.portfolio_id, ticker.ticker, rule_id),
    )


def _exit_ma_period(ticker: PortfolioTickerView) -> Optional[int]:
    if ticker.type == "investor":
        return 150
    if ticker.type == "trader":
        return 50
    return None


def _exit_rule_id(ticker: PortfolioTickerView) -> Optional[str]:
    if ticker.type == "investor":
        return "P1"
    if ticker.type == "trader":
        return "P2"
    return None


def _initial_profit_lock_suggestion(ticker: PortfolioTickerView, asof: date) -> dict:
    if ticker.type not in {"investor", "trader"} or ticker.current_profit_lock is not None:
        return {}

    bars = ticker.bars
    idx = index_at_or_before(bars, asof)
    exit_period = _exit_ma_period(ticker)
    if idx is None or exit_period is None:
        return {
            "stop_suggestion_status": "unavailable",
            "stop_suggestion_reason": "Market data is required before Sentinel can suggest a protective stop.",
        }

    current_bar = bars[idx]
    current_sma = sma_adj_close(bars, idx, exit_period)
    if current_sma is None:
        return {
            "asof": current_bar.date.isoformat(),
            "close": str(current_bar.adj_close),
            "exit_ma_period": exit_period,
            "stop_suggestion_status": "unavailable",
            "stop_suggestion_reason": "More daily bars are required before the exit moving average can be calculated.",
        }

    pivots = ticker.swing_pivots or detect_swing_pivots(bars)
    latest_low = latest_pivot_low(pivots, current_bar.date)
    if latest_low is not None and latest_low.price > current_sma:
        candidate_base = latest_low.price
        basis_rule = "swing low above SMA%s" % exit_period
    else:
        candidate_base = current_sma
        basis_rule = "SMA%s" % exit_period

    suggested_stop = quantize_price(candidate_base * (Decimal("1") - DEFAULT_STOP_BUFFER))
    payload = {
        "asof": current_bar.date.isoformat(),
        "close": str(current_bar.adj_close),
        "exit_ma": str(quantize_price(current_sma)),
        "exit_ma_period": exit_period,
        "buffer_pct": str(DEFAULT_STOP_BUFFER),
        "basis_rule": basis_rule,
        "stop_suggestion_status": "available",
        "suggested_stop": str(suggested_stop),
    }
    if latest_low is not None:
        payload.update(
            {
                "swing_low_date": latest_low.date.isoformat(),
                "swing_low_price": str(latest_low.price),
            }
        )
    if suggested_stop >= current_bar.adj_close:
        payload["stop_suggestion_status"] = "review_required"
        payload["stop_suggestion_reason"] = (
            "The calculated protective stop is not below the latest close. Review the active exit rules before saving it."
        )
    return payload


def evaluate_ticker(
    ticker: PortfolioTickerView,
    *,
    asof: date,
    subscriptions: Optional[Iterable[AlertSubscription]] = None,
) -> List[RuleResult]:
    """Evaluate all enabled rules for a portfolio ticker."""

    subscription_list = tuple(subscriptions or ())
    enabled = _enabled_rule_ids(subscription_list if subscriptions is not None else None)
    results: List[RuleResult] = []

    if ticker.status != "active":
        return results

    initial_stop_suggestion = _initial_profit_lock_suggestion(ticker, asof)

    if ticker.type == "unknown" and _is_enabled("C1", enabled):
        results.append(
            _result(
                ticker,
                "C1",
                "setup",
                "blocker",
                False,
                True,
                "Classify the ticker as Investor, Trader, or Index.",
                {"missing": ["type"]},
                subscriptions=subscription_list,
            )
        )

    if _is_enabled("T1", enabled):
        missing = []
        if ticker.entry_price is None:
            missing.append("entry_price")
        if ticker.current_profit_lock is None and ticker.type != "index":
            missing.append("current_profit_lock")
        if missing:
            payload = {"missing": missing}
            if "current_profit_lock" in missing:
                payload.update(initial_stop_suggestion)
            results.append(
                _result(
                    ticker,
                    "T1",
                    "setup",
                    "critical",
                    False,
                    True,
                    "Review the suggested protective stop, adjust if needed, then save it before treating this ticker as fully monitored."
                    if payload.get("suggested_stop")
                    else "Enter the missing setup data before treating this ticker as fully monitored.",
                    payload,
                    subscriptions=subscription_list,
                )
            )

    if (
        ticker.type in {"investor", "trader"}
        and ticker.shares is not None
        and ticker.current_profit_lock is None
        and _is_enabled("A1", enabled)
    ):
        results.append(
            _result(
                ticker,
                "A1",
                "rule_violation",
                "critical",
                False,
                True,
                "Review the suggested protective stop, adjust if needed, then save it as this holding's monitored stop. Sentinel does not place broker orders."
                if initial_stop_suggestion.get("suggested_stop")
                else "Place or record the protective stop for this holding.",
                {"missing": ["current_profit_lock"], "shares": str(ticker.shares), **initial_stop_suggestion},
                subscriptions=subscription_list,
            )
        )

    if ticker.margin_used and _is_enabled("A6", enabled):
        results.append(
            _result(
                ticker,
                "A6",
                "rule_violation",
                "critical",
                False,
                True,
                "Remove margin exposure before treating the portfolio as methodology-compliant.",
                {"margin_used": True},
                subscriptions=subscription_list,
            )
        )

    bars = ticker.bars
    idx = index_at_or_before(bars, asof)
    if idx is None:
        return results

    current_bar = bars[idx]
    exit_result_fired = False
    exit_period = _exit_ma_period(ticker)
    exit_rule = _exit_rule_id(ticker)

    if exit_period and exit_rule and _is_enabled(exit_rule, enabled):
        current_sma = sma_adj_close(bars, idx, exit_period)
        previous_sma = sma_adj_close(bars, idx - 1, exit_period) if idx > 0 else None
        if current_sma is not None:
            state_active = current_bar.adj_close < current_sma
            triggered = False
            if previous_sma is not None and idx > 0:
                previous_bar = bars[idx - 1]
                triggered = crossed_below(
                    previous_bar.adj_close,
                    previous_sma,
                    current_bar.adj_close,
                    current_sma,
                )
            if state_active or triggered:
                exit_result_fired = True
                payload = {
                    "asof": current_bar.date.isoformat(),
                    "close": str(current_bar.adj_close),
                    "exit_ma": str(quantize_price(current_sma)),
                    "exit_ma_period": exit_period,
                    "distance_pct": str(distance_pct(current_bar.adj_close, current_sma)),
                    "shares": str(ticker.shares) if ticker.shares is not None else None,
                }
                results.append(
                    _result(
                        ticker,
                        exit_rule,
                        "exit",
                        "critical",
                        triggered,
                        state_active,
                        "Sell the full position." if ticker.shares is not None else "Do not enter or add while below the exit moving average.",
                        payload,
                        subscriptions=subscription_list,
                        dedupe_key="%s:%s:exit" % (ticker.portfolio_id, ticker.ticker),
                    )
                )

    if _is_enabled("P7", enabled):
        volume_baseline = average_volume_previous(bars, idx, 50)
        if volume_baseline is not None and volume_baseline > 0:
            volume_multiple = Decimal(current_bar.volume) / volume_baseline
            if volume_multiple > Decimal("5") and current_bar.close < current_bar.open:
                results.append(
                    _result(
                        ticker,
                        "P7",
                        "distribution",
                        "warning",
                        True,
                        True,
                        "Investigate distribution; do not add unless the setup still passes the methodology gate.",
                        {
                            "asof": current_bar.date.isoformat(),
                            "volume": current_bar.volume,
                            "volume_sma50_previous": str(quantize_price(volume_baseline)),
                            "volume_multiple": str(volume_multiple),
                            "open": str(current_bar.open),
                            "close": str(current_bar.close),
                            "supports_exit": exit_result_fired,
                        },
                        subscriptions=subscription_list,
                        dedupe_key="%s:%s:P7:%s-W%s"
                        % (
                            ticker.portfolio_id,
                            ticker.ticker,
                            current_bar.date.isocalendar()[0],
                            current_bar.date.isocalendar()[1],
                        ),
                    )
                )

    if (
        ticker.type in {"investor", "trader"}
        and ticker.current_profit_lock is not None
        and _is_enabled("T4", enabled)
    ):
        exit_period = _exit_ma_period(ticker)
        current_sma = sma_adj_close(bars, idx, exit_period) if exit_period else None
        pivots = ticker.swing_pivots or detect_swing_pivots(bars)
        latest_low = latest_pivot_low(pivots, current_bar.date)
        if current_sma is not None and latest_low is not None and latest_low.price > current_sma:
            candidate_base = max(current_sma, latest_low.price)
            proposed = quantize_price(candidate_base * (Decimal("1") - DEFAULT_STOP_BUFFER))
            if proposed > ticker.current_profit_lock:
                results.append(
                    _result(
                        ticker,
                        "T4",
                        "raise_lock",
                        "warning",
                        True,
                        True,
                        "Raise the profit lock.",
                        {
                            "asof": current_bar.date.isoformat(),
                            "current_profit_lock": str(ticker.current_profit_lock),
                            "proposed_profit_lock": str(proposed),
                            "swing_low_date": latest_low.date.isoformat(),
                            "swing_low_price": str(latest_low.price),
                            "exit_ma": str(quantize_price(current_sma)),
                            "buffer_pct": str(DEFAULT_STOP_BUFFER),
                            "shares": str(ticker.shares) if ticker.shares is not None else None,
                        },
                        subscriptions=subscription_list,
                        dedupe_key="%s:%s:T4:%s"
                        % (ticker.portfolio_id, ticker.ticker, latest_low.date.isoformat()),
                    )
                )

    if (
        ticker.type in {"investor", "trader"}
        and ticker.entry_price is not None
        and not exit_result_fired
        and _is_enabled("T5", enabled)
    ):
        drawdown = (current_bar.adj_close / ticker.entry_price) - Decimal("1")
        if drawdown <= Decimal("-0.15"):
            results.append(
                _result(
                    ticker,
                    "T5",
                    "rule_violation",
                    "critical",
                    True,
                    True,
                    "Review missing or misplaced protection immediately.",
                    {
                        "asof": current_bar.date.isoformat(),
                        "entry_price": str(ticker.entry_price),
                        "close": str(current_bar.adj_close),
                        "drawdown_pct": str(drawdown),
                        "current_profit_lock": str(ticker.current_profit_lock)
                        if ticker.current_profit_lock is not None
                        else None,
                    },
                    subscriptions=subscription_list,
                )
            )

    return results
