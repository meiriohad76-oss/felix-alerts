from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable, List, Sequence
from uuid import uuid4

from .explanations import render_explanation
from .models import AlertRecord, PortfolioTickerView, RuleResult
from .tickets import generate_order_ticket

OPEN_STATUSES = {"new", "sent"}


def suppress_supporting_distribution(results: Sequence[RuleResult]) -> List[RuleResult]:
    """Avoid a separate P7 alert when it merely supports a same-day exit."""

    output: List[RuleResult] = []
    for result in results:
        if result.rule_id == "P7" and result.payload.get("supports_exit") is True:
            continue
        output.append(result)
    return output


def refresh_existing_open_alerts(
    *,
    ticker: PortfolioTickerView,
    results: Sequence[RuleResult],
    existing_alerts: Iterable[AlertRecord] = (),
) -> List[AlertRecord]:
    active_results_by_key = {
        result.dedupe_key: result
        for result in suppress_supporting_distribution(results)
        if result.triggered or result.state_active
    }
    refreshed: List[AlertRecord] = []
    for alert in existing_alerts:
        if alert.status not in OPEN_STATUSES:
            continue
        result = active_results_by_key.get(alert.result.dedupe_key)
        if result is None or result.portfolio_ticker_id != ticker.portfolio_ticker_id:
            continue
        explanation = render_explanation(result)
        ticket = generate_order_ticket(ticker, result)
        if alert.result != result or alert.explanation != explanation or alert.ticket != ticket:
            refreshed.append(replace(alert, result=result, explanation=explanation, ticket=ticket))
    return refreshed


def materialize_alerts(
    *,
    ticker: PortfolioTickerView,
    results: Sequence[RuleResult],
    existing_alerts: Iterable[AlertRecord] = (),
) -> List[AlertRecord]:
    existing_open_keys = {
        alert.result.dedupe_key
        for alert in existing_alerts
        if alert.status in OPEN_STATUSES and alert.result.portfolio_id == ticker.portfolio_id
    }
    records: List[AlertRecord] = []
    for result in suppress_supporting_distribution(results):
        if not (result.triggered or result.state_active):
            continue
        if result.dedupe_key in existing_open_keys:
            continue
        explanation = render_explanation(result)
        ticket = generate_order_ticket(ticker, result)
        records.append(
            AlertRecord(
                alert_id=uuid4(),
                result=result,
                explanation=explanation,
                ticket=ticket,
                status="new",
                created_at=datetime.utcnow(),
            )
        )
        existing_open_keys.add(result.dedupe_key)
    return records
