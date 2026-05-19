from __future__ import annotations

from typing import Iterable

from .models import AlertRecord, PortfolioTickerView

SETUP_RULE_IDS = {"C1", "T1", "A1"}
EXIT_RULE_IDS = {"P1", "P2", "T5"}
BEARISH_RULE_IDS = {"P7", "T4", "A6"}


def _clamp(value: float | int) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, round(number)))


def _rule_id(alert: AlertRecord) -> str:
    return alert.result.rule_id


def _max_rule_score(trigger_summary: dict, rule_ids: set[str]) -> int:
    items = trigger_summary.get("proximity_items") or ()
    scores = [
        int(item.get("score") or 0)
        for item in items
        if item.get("rule_id") in rule_ids
    ]
    return max(scores, default=0)


def _active_rule_count(trigger_summary: dict, rule_ids: set[str]) -> int:
    items = trigger_summary.get("proximity_items") or ()
    return len(
        [
            item
            for item in items
            if item.get("rule_id") in rule_ids and item.get("status") in {"triggered", "active"}
        ]
    )


def _score_payload(label: str, value: int, reason: str) -> dict:
    return {"label": label, "value": _clamp(value), "reason": reason}


def build_holding_scores(
    *,
    ticker: PortfolioTickerView,
    trigger_summary: dict,
    market_data_status: dict,
    open_alerts: Iterable[AlertRecord],
    missing_rule_ids: Iterable[str],
    bars_count: int,
) -> dict:
    alerts = tuple(open_alerts)
    setup_alert_count = len([alert for alert in alerts if _rule_id(alert) in SETUP_RULE_IDS])
    exit_alert_count = len([alert for alert in alerts if _rule_id(alert) in EXIT_RULE_IDS])
    bearish_alert_count = len([alert for alert in alerts if _rule_id(alert) in BEARISH_RULE_IDS])
    market_alert_count = len([alert for alert in alerts if _rule_id(alert) not in SETUP_RULE_IDS])
    missing_rules = tuple(missing_rule_ids)
    data_gap_count = int(trigger_summary.get("data_gap_count") or 0)
    proximity = _clamp(trigger_summary.get("max_proximity_score") or 0)
    massive_failed = (
        market_data_status.get("last_attempt_source") == "massive-stocks-aggregates"
        and market_data_status.get("last_attempt_status") == "failed"
    )
    missing_stop = ticker.type != "index" and ticker.current_profit_lock is None and ticker.user_exit_price is None

    setup = _clamp(
        max(
            70 if ticker.type == "unknown" else 0,
            65 if missing_stop else 0,
            55 + setup_alert_count * 12 if setup_alert_count else 0,
            52 if missing_rules else 0,
            min(82, data_gap_count * 22) if data_gap_count else 0,
        )
    )
    exit_score = _clamp(
        max(
            82 + min(12, exit_alert_count * 4) if exit_alert_count else 0,
            76 + _active_rule_count(trigger_summary, EXIT_RULE_IDS) * 8 if _active_rule_count(trigger_summary, EXIT_RULE_IDS) else 0,
            _max_rule_score(trigger_summary, EXIT_RULE_IDS),
        )
    )
    bearish = _clamp(
        max(
            65 + bearish_alert_count * 8 if bearish_alert_count else 0,
            _max_rule_score(trigger_summary, BEARISH_RULE_IDS),
        )
    )
    data = _clamp(max(70 if not bars_count else 0, 55 if massive_failed else 0, data_gap_count * 20))
    urgency = _clamp(
        max(
            90 + min(8, market_alert_count * 2) if market_alert_count else 0,
            80 if int(trigger_summary.get("action_count") or 0) else 0,
            65 + proximity * 0.3 if proximity >= 75 else proximity,
            58 + setup * 0.25 if setup >= 55 else 0,
            45 if data >= 55 else 0,
            18,
        )
    )
    health = _clamp(100 - max(exit_score, bearish) * 0.48 - setup * 0.32 - data * 0.28 - proximity * 0.18)
    bullish = _clamp(max(0, health - max(exit_score, bearish, setup) * 0.25))
    buy = None

    if market_alert_count or int(trigger_summary.get("action_count") or 0):
        rank = 0
        reason = "Market action is active now."
    elif proximity >= 75:
        rank = 1
        reason = "A watched trigger is close to firing."
    elif setup >= 55:
        rank = 2
        reason = "Setup or protection data needs attention."
    elif data >= 55:
        rank = 3
        reason = "Market data is missing or stale."
    else:
        rank = 4
        reason = "No current action; normal monitoring."

    return {
        "rank": rank,
        "reason": reason,
        "health": _score_payload("Health", health, "Overall condition after action, setup, and data penalties."),
        "proximity": _score_payload("Trigger Near", proximity, "Closest implemented trigger proximity."),
        "urgency": _score_payload("Urgency", urgency, reason),
        "setup": _score_payload("Setup", setup, "Missing setup, stop/profit-lock, classification, or data prerequisites."),
        "exit": _score_payload("Exit", exit_score, "Active or near exit-pressure rules."),
        "bearish": _score_payload("Bearish", bearish, "Distribution and bearish-pressure rules."),
        "bullish": _score_payload("Bullish", bullish, "Supportive state when risk and setup pressure are low."),
        "buy": {"label": "Buy", "value": buy, "reason": "No buy signal has been generated by the current monitor."},
        "components": {
            "setup_alert_count": setup_alert_count,
            "exit_alert_count": exit_alert_count,
            "bearish_alert_count": bearish_alert_count,
            "market_alert_count": market_alert_count,
            "data_gap_count": data_gap_count,
            "missing_rule_count": len(missing_rules),
            "missing_stop": missing_stop,
            "massive_failed": massive_failed,
            "bars_count": bars_count,
        },
    }
