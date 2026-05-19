from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional, Tuple
from uuid import UUID


TickerType = Literal["investor", "trader", "index", "unknown"]
TickerStatus = Literal["active", "inactive", "closed"]
AlertKind = Literal[
    "exit",
    "distribution",
    "raise_lock",
    "rule_violation",
    "gate_blocker",
    "gate_warning",
    "setup",
]
Severity = Literal["info", "warning", "critical", "blocker"]
AlertStatus = Literal["new", "sent", "acknowledged", "resolved", "expired", "missed"]
AckKind = Literal["placed", "placed_with_modification", "ignored"]
NotificationChannel = Literal["in_app", "email", "telegram"]
NotificationStatus = Literal["queued", "sent", "failed"]
ScorecardEventKind = Literal["placed", "modified", "ignored", "deferred", "missed", "missing_protection"]
ValidationSeverity = Literal["blocker", "warning"]


@dataclass(frozen=True)
class Portfolio:
    portfolio_id: UUID
    user_id: UUID
    name: str
    status: Literal["active", "archived"] = "active"


@dataclass(frozen=True)
class Bar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal
    volume: int


@dataclass(frozen=True)
class Pivot:
    date: date
    kind: Literal["high", "low"]
    price: Decimal
    strength: int


@dataclass(frozen=True)
class PortfolioTickerView:
    portfolio_id: UUID
    portfolio_ticker_id: UUID
    user_id: UUID
    ticker: str
    type: TickerType = "investor"
    status: TickerStatus = "active"
    position_id: Optional[UUID] = None
    account_ids: Tuple[UUID, ...] = ()
    entry_date: Optional[date] = None
    entry_price: Optional[Decimal] = None
    shares: Optional[Decimal] = None
    current_profit_lock: Optional[Decimal] = None
    user_exit_price: Optional[Decimal] = None
    margin_used: bool = False
    notes: str = ""
    bars: Tuple[Bar, ...] = ()
    swing_pivots: Tuple[Pivot, ...] = ()

    @property
    def has_holding_metadata(self) -> bool:
        return self.shares is not None and self.entry_price is not None


@dataclass(frozen=True)
class AlertSubscription:
    subscription_id: UUID
    user_id: UUID
    portfolio_id: UUID
    portfolio_ticker_id: UUID
    ticker: str
    rule_id: str
    enabled: bool = True
    config: Dict[str, str] = field(default_factory=dict)
    created_from_import_id: Optional[UUID] = None


@dataclass(frozen=True)
class AlertSubscriptionView:
    subscription_id: UUID
    portfolio_id: UUID
    ticker: str
    rule_id: str
    enabled: bool
    config: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleResult:
    user_id: UUID
    portfolio_id: UUID
    portfolio_ticker_id: UUID
    ticker: str
    rule_id: str
    kind: AlertKind
    severity: Severity
    triggered: bool
    state_active: bool
    suggested_action: str
    payload: Dict[str, object]
    subscription_id: Optional[UUID] = None
    dedupe_key: str = ""


@dataclass(frozen=True)
class PlaybookRule:
    rule_id: str
    title: str
    pillar: Literal["classify", "protect", "take_profits", "automate"]
    short_summary: str
    rationale: str
    trigger_template: str
    recommended_action_template: str
    applies_to: Tuple[str, ...]
    severity_default: Severity
    source_section: str


@dataclass(frozen=True)
class AlertExplanation:
    rule_id: str
    title: str
    what_triggered: str
    rule_rationale: str
    evidence: Dict[str, object]
    recommended_action: str
    source_section: str


@dataclass(frozen=True)
class AccountAllocation:
    account_id: UUID
    qty: Decimal


@dataclass(frozen=True)
class OrderTicket:
    ticker: str
    action: Literal["sell", "place_stop", "modify_stop"]
    qty: Decimal
    order_type: Literal["market", "stop", "stop_limit"]
    rationale_rule_ids: Tuple[str, ...]
    copy_text: str
    account_allocations: Tuple[AccountAllocation, ...] = ()
    stop_price: Optional[Decimal] = None
    limit_price: Optional[Decimal] = None
    time_in_force: Literal["day", "gtc"] = "day"


@dataclass(frozen=True)
class AlertRecord:
    alert_id: UUID
    result: RuleResult
    explanation: AlertExplanation
    ticket: Optional[OrderTicket]
    status: AlertStatus
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    ack_kind: Optional[AckKind] = None
    ack_note: str = ""


@dataclass(frozen=True)
class NotificationRecord:
    notification_id: UUID
    portfolio_id: UUID
    alert_id: UUID
    ticker: str
    rule_id: str
    channel: NotificationChannel
    status: NotificationStatus
    subject: str
    body: str
    created_at: datetime
    error: str = ""
    retry_count: int = 0
    provider_response: str = ""


@dataclass(frozen=True)
class ScorecardEvent:
    event_id: UUID
    user_id: UUID
    portfolio_id: UUID
    portfolio_ticker_id: UUID
    ticker: str
    alert_id: UUID
    kind: ScorecardEventKind
    rule_id: str
    occurred_at: datetime
    note: str = ""


@dataclass(frozen=True)
class ValidationIssue:
    rule_id: str
    severity: ValidationSeverity
    message: str
    evidence: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    blockers: Tuple[ValidationIssue, ...] = ()
    warnings: Tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True)
class PortfolioReport:
    portfolio_id: UUID
    generated_at: datetime
    open_alert_count: int
    critical_alert_count: int
    setup_alert_count: int
    ticket_count: int
    scorecard_summary: Dict[str, int]
    alert_lines: Tuple[str, ...]


@dataclass(frozen=True)
class CsvImportIssue:
    row_number: int
    code: str
    message: str


@dataclass(frozen=True)
class CsvImportRowResult:
    row_number: int
    ticker: Optional[str]
    status: Literal["accepted", "rejected", "updated", "unchanged", "deactivated"]
    issues: Tuple[CsvImportIssue, ...] = ()


@dataclass(frozen=True)
class CsvImportReport:
    portfolio_id: UUID
    import_id: UUID
    imported_at: datetime
    tickers: Tuple[PortfolioTickerView, ...]
    row_results: Tuple[CsvImportRowResult, ...]
    created_count: int
    updated_count: int
    unchanged_count: int
    rejected_count: int
    deactivated_count: int = 0
