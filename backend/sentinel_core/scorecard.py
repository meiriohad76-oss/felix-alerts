from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple, cast
from uuid import uuid4

from .models import AckKind, AlertRecord, ScorecardEvent, ScorecardEventKind

VALID_ACK_KINDS = {"placed", "placed_with_modification", "ignored"}


def acknowledge_alert(
    alert: AlertRecord,
    *,
    ack_kind: AckKind,
    note: str = "",
    acknowledged_at: Optional[datetime] = None,
) -> Tuple[AlertRecord, Optional[ScorecardEvent]]:
    if ack_kind not in VALID_ACK_KINDS:
        raise ValueError("ack_kind must be placed, placed_with_modification, or ignored")
    if ack_kind in {"placed_with_modification", "ignored"} and not note.strip():
        raise ValueError("%s acknowledgement requires a note" % ack_kind)

    when = acknowledged_at or datetime.utcnow()
    updated = replace(
        alert,
        status="acknowledged",
        acknowledged_at=when,
        ack_kind=ack_kind,
        ack_note=note.strip(),
    )

    event_kind = None
    if ack_kind == "placed":
        event_kind = "placed"
    elif ack_kind == "placed_with_modification":
        event_kind = "modified"
    elif ack_kind == "ignored":
        event_kind = "ignored"

    event = None
    if event_kind is not None:
        event = ScorecardEvent(
            event_id=uuid4(),
            user_id=alert.result.user_id,
            portfolio_id=alert.result.portfolio_id,
            portfolio_ticker_id=alert.result.portfolio_ticker_id,
            ticker=alert.result.ticker,
            alert_id=alert.alert_id,
            kind=cast(ScorecardEventKind, event_kind),
            rule_id=alert.result.rule_id,
            occurred_at=when,
            note=note.strip(),
        )
    return updated, event


def stale_exit_events(
    alerts: Iterable[AlertRecord],
    *,
    now: Optional[datetime] = None,
    deferred_after: timedelta = timedelta(hours=48),
    missed_after: timedelta = timedelta(days=7),
) -> List[ScorecardEvent]:
    when = now or datetime.utcnow()
    events: List[ScorecardEvent] = []
    for alert in alerts:
        if alert.result.kind != "exit" or alert.status not in {"new", "sent"}:
            continue
        age = when - alert.created_at
        if age >= missed_after:
            kind = "missed"
        elif age >= deferred_after:
            kind = "deferred"
        else:
            continue
        events.append(
            ScorecardEvent(
                event_id=uuid4(),
                user_id=alert.result.user_id,
                portfolio_id=alert.result.portfolio_id,
                portfolio_ticker_id=alert.result.portfolio_ticker_id,
                ticker=alert.result.ticker,
                alert_id=alert.alert_id,
                kind=cast(ScorecardEventKind, kind),
                rule_id=alert.result.rule_id,
                occurred_at=when,
                note="Exit alert open for %s" % age,
            )
        )
    return events


def summarize_events(events: Iterable[ScorecardEvent]) -> Dict[str, int]:
    counts = Counter(event.kind for event in events)
    return dict(counts)
