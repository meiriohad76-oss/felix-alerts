from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .models import AlertExplanation, RuleResult
from .rule_catalog import get_rule


def _number(value: object, places: int = 2) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return f"{parsed:.{places}f}"


def _percent(value: object, places: int = 1, absolute: bool = False) -> str:
    try:
        parsed = Decimal(str(value)) * Decimal("100")
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if absolute:
        parsed = abs(parsed)
        return f"{parsed:.{places}f}%"
    sign = "+" if parsed > 0 else ""
    return f"{sign}{parsed:.{places}f}%"


def _missing_labels(evidence: dict) -> str:
    labels = {
        "type": "methodology style",
        "entry_price": "entry price",
        "current_profit_lock": "profit-lock/stop level",
    }
    return ", ".join(labels.get(str(item), str(item)) for item in evidence.get("missing", []))


def render_explanation(result: RuleResult) -> AlertExplanation:
    rule = get_rule(result.rule_id)
    evidence = dict(result.payload)
    ticker = result.ticker

    if result.rule_id in {"P1", "P2"}:
        what = "%s closed at %s, below its %s-day exit moving average at %s." % (
            ticker,
            _number(evidence.get("close")),
            evidence.get("exit_ma_period"),
            _number(evidence.get("exit_ma")),
        )
    elif result.rule_id == "P7":
        what = "%s traded at %sx its recent volume baseline and closed below the open." % (
            ticker,
            _number(evidence.get("volume_multiple"), 1),
        )
    elif result.rule_id == "T4":
        what = "%s has a confirmed swing low at %s, supporting a profit-lock raise from %s to %s." % (
            ticker,
            _number(evidence.get("swing_low_price")),
            _number(evidence.get("current_profit_lock")),
            _number(evidence.get("proposed_profit_lock")),
        )
    elif result.rule_id == "T5":
        what = "%s is down %s from entry: close %s vs entry %s. No primary exit alert handled the position first." % (
            ticker,
            _percent(evidence.get("drawdown_pct"), absolute=True),
            _number(evidence.get("close")),
            _number(evidence.get("entry_price")),
        )
    elif result.rule_id == "T1":
        missing = _missing_labels(evidence)
        what = (
            "%s needs setup data: the imported portfolio file did not include %s. "
            "Sentinel can watch price rules, but it cannot confirm position protection until this is entered."
        ) % (ticker, missing or "required setup fields")
        if evidence.get("suggested_stop"):
            what += " Sentinel suggests reviewing %s as the initial protective stop based on %s." % (
                _number(evidence.get("suggested_stop")),
                evidence.get("basis_rule") or "the methodology stop model",
            )
    elif result.rule_id == "A1":
        what = (
            "%s has shares recorded, but the imported portfolio file did not include a profit-lock/stop level. "
            "The position is missing a protective stop record."
        ) % ticker
        if evidence.get("suggested_stop"):
            what += " Sentinel suggests reviewing %s as the initial protective stop based on %s." % (
                _number(evidence.get("suggested_stop")),
                evidence.get("basis_rule") or "the methodology stop model",
            )
    elif result.rule_id == "C1":
        what = "%s needs setup data: choose Investor, Trader, or Index so Sentinel can apply the correct rules." % ticker
    elif result.rule_id == "A6":
        what = "%s is marked as using margin. The methodology treats margin as a risk blocker." % ticker
    else:
        what = rule.trigger_template.format(ticker=ticker)

    return AlertExplanation(
        rule_id=rule.rule_id,
        title=rule.title,
        what_triggered=what,
        rule_rationale=rule.rationale,
        evidence=evidence,
        recommended_action=result.suggested_action or rule.recommended_action_template,
        source_section=rule.source_section,
    )
