"""Alert management handlers.

Extracted from http_api.py — no behaviour change.
"""
from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from .scorecard import stale_exit_events


def handle_list_alerts(portfolio_id: UUID, workspace) -> tuple:
    """GET /portfolios/{id}/alerts"""
    return HTTPStatus.OK, {"alerts": workspace.list_alerts(portfolio_id=portfolio_id)}


def handle_list_alert_events(portfolio_id: UUID, ticker, workspace) -> tuple:
    """GET /portfolios/{id}/alert-events"""
    return HTTPStatus.OK, {
        "events": workspace.store.list_alert_events(portfolio_id, ticker=ticker)
    }


def handle_maintenance_scorecard(portfolio_id: UUID, workspace) -> tuple:
    """POST /portfolios/{id}/maintenance/scorecard — sweep stale exit alerts."""
    open_exit_alerts = [
        a for a in workspace.store.list_alerts(portfolio_id)
        if a.status in {"new", "sent"} and a.result.kind == "exit"
    ]
    events = stale_exit_events(open_exit_alerts)
    deferred_written = 0
    missed_written = 0
    for event in events:
        written = workspace.store.save_scorecard_event_if_not_exists(event)
        if written:
            if event.kind == "deferred":
                deferred_written += 1
            elif event.kind == "missed":
                missed_written += 1
    return HTTPStatus.OK, {"deferred_written": deferred_written, "missed_written": missed_written}
