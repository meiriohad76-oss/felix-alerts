"""Core Sentinel domain logic.

This package intentionally starts dependency-light. The modules here are pure
or near-pure building blocks that can later sit behind FastAPI endpoints,
workers, and a frontend without changing the methodology contract.
"""

from .models import (
    AlertExplanation,
    AlertRecord,
    AlertSubscription,
    Bar,
    NotificationRecord,
    OrderTicket,
    Pivot,
    PlaybookRule,
    Portfolio,
    PortfolioReport,
    PortfolioTickerView,
    RuleResult,
    ScorecardEvent,
    ValidationIssue,
    ValidationResult,
)
from .persistent_service import PersistentSentinelWorkspace
from .sqlite_store import SQLiteStore

__all__ = [
    "AlertExplanation",
    "AlertRecord",
    "AlertSubscription",
    "Bar",
    "NotificationRecord",
    "OrderTicket",
    "Pivot",
    "PlaybookRule",
    "Portfolio",
    "PortfolioReport",
    "PortfolioTickerView",
    "RuleResult",
    "ScorecardEvent",
    "ValidationIssue",
    "ValidationResult",
    "PersistentSentinelWorkspace",
    "SQLiteStore",
]
