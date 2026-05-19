from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .models import AlertRecord, PortfolioReport, ScorecardEvent
from .scorecard import summarize_events


def build_portfolio_report(
    *,
    portfolio_id,
    alerts: Iterable[AlertRecord],
    scorecard_events: Iterable[ScorecardEvent] = (),
    generated_at: datetime | None = None,
) -> PortfolioReport:
    alert_list = list(alerts)
    open_alerts = [alert for alert in alert_list if alert.status in {"new", "sent"}]
    critical_alerts = [alert for alert in open_alerts if alert.result.severity in {"critical", "blocker"}]
    setup_alerts = [alert for alert in open_alerts if alert.result.kind == "setup"]
    tickets = [alert for alert in open_alerts if alert.ticket is not None]
    lines = tuple(
        "%s %s: %s" % (
            alert.result.ticker,
            alert.result.rule_id,
            alert.explanation.recommended_action,
        )
        for alert in open_alerts
    )
    return PortfolioReport(
        portfolio_id=portfolio_id,
        generated_at=generated_at or datetime.utcnow(),
        open_alert_count=len(open_alerts),
        critical_alert_count=len(critical_alerts),
        setup_alert_count=len(setup_alerts),
        ticket_count=len(tickets),
        scorecard_summary=summarize_events(scorecard_events),
        alert_lines=lines,
    )

