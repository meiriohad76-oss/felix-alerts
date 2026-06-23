from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from .models import (
    AccountAllocation,
    AlertExplanation,
    AlertRecord,
    AlertSubscription,
    Bar,
    NotificationRecord,
    OrderTicket,
    Portfolio,
    PortfolioTickerView,
    RuleResult,
    ScorecardEvent,
)
from .notifications import normalize_email_recipients
from .serialization import to_jsonable


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS portfolios (
  portfolio_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_tickers (
  portfolio_ticker_id TEXT PRIMARY KEY,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  type TEXT NOT NULL,
  status TEXT NOT NULL,
  position_id TEXT,
  account_ids_json TEXT NOT NULL,
  entry_date TEXT,
  entry_price TEXT,
  shares TEXT,
  current_profit_lock TEXT,
  user_exit_price TEXT,
  margin_used INTEGER NOT NULL,
  notes TEXT NOT NULL,
  UNIQUE(portfolio_id, ticker)
);

CREATE TABLE IF NOT EXISTS alert_subscriptions (
  subscription_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  portfolio_ticker_id TEXT NOT NULL REFERENCES portfolio_tickers(portfolio_ticker_id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  enabled INTEGER NOT NULL,
  config_json TEXT NOT NULL,
  created_from_import_id TEXT,
  UNIQUE(portfolio_id, ticker, rule_id)
);

CREATE TABLE IF NOT EXISTS bars (
  ticker TEXT NOT NULL,
  date TEXT NOT NULL,
  open TEXT NOT NULL,
  high TEXT NOT NULL,
  low TEXT NOT NULL,
  close TEXT NOT NULL,
  adj_close TEXT NOT NULL,
  volume INTEGER NOT NULL,
  PRIMARY KEY(ticker, date)
);

CREATE TABLE IF NOT EXISTS market_data_status (
  ticker TEXT PRIMARY KEY,
  data_source TEXT NOT NULL,
  data_source_label TEXT NOT NULL,
  data_loaded_at TEXT,
  bars_start_date TEXT,
  bars_end_date TEXT,
  bars_count INTEGER NOT NULL,
  last_attempt_source TEXT NOT NULL,
  last_attempt_label TEXT NOT NULL,
  last_attempt_at TEXT,
  last_attempt_status TEXT NOT NULL,
  last_error TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id TEXT PRIMARY KEY,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  portfolio_ticker_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  acknowledged_at TEXT,
  ack_kind TEXT,
  ack_note TEXT NOT NULL,
  record_json TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_open_dedupe
ON alerts(portfolio_id, dedupe_key)
WHERE status IN ('new', 'sent');

CREATE TABLE IF NOT EXISTS notification_log (
  notification_id TEXT PRIMARY KEY,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  alert_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  status TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  error TEXT NOT NULL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  provider_response TEXT NOT NULL DEFAULT '',
  UNIQUE(alert_id, channel)
);

CREATE TABLE IF NOT EXISTS notification_settings (
  portfolio_id TEXT PRIMARY KEY REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  email_enabled INTEGER NOT NULL,
  email_recipients_json TEXT NOT NULL,
  telegram_enabled INTEGER NOT NULL,
  telegram_chat_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scorecard_events (
  event_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  portfolio_ticker_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  alert_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_runs (
  run_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  asof TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  provider TEXT NOT NULL,
  ticker_count INTEGER NOT NULL,
  market_data_updated_count INTEGER NOT NULL,
  market_data_failed_count INTEGER NOT NULL,
  alerts_created_count INTEGER NOT NULL,
  alerts_refreshed_count INTEGER NOT NULL,
  alerts_resolved_count INTEGER NOT NULL,
  notifications_count INTEGER NOT NULL,
  error TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_run_items (
  run_item_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES monitor_runs(run_id) ON DELETE CASCADE,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  portfolio_ticker_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  status TEXT NOT NULL,
  alert_id TEXT,
  dedupe_key TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_events (
  event_id TEXT PRIMARY KEY,
  alert_id TEXT NOT NULL,
  run_id TEXT,
  user_id TEXT NOT NULL,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
  portfolio_ticker_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
"""


def _uuid(value: str) -> UUID:
    return UUID(value)


def _optional_uuid(value: Optional[str]) -> Optional[UUID]:
    return UUID(value) if value else None


def _decimal(value: Optional[str]) -> Optional[Decimal]:
    return Decimal(value) if value is not None else None


def _date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _datetime(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _bar_from_row(row: sqlite3.Row) -> Bar:
    return Bar(
        date=date.fromisoformat(row["date"]),
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        close=Decimal(row["close"]),
        adj_close=Decimal(row["adj_close"]),
        volume=int(row["volume"]),
    )


def _rule_result_from_dict(data: dict) -> RuleResult:
    return RuleResult(
        user_id=_uuid(data["user_id"]),
        portfolio_id=_uuid(data["portfolio_id"]),
        portfolio_ticker_id=_uuid(data["portfolio_ticker_id"]),
        ticker=data["ticker"],
        rule_id=data["rule_id"],
        kind=data["kind"],
        severity=data["severity"],
        triggered=bool(data["triggered"]),
        state_active=bool(data["state_active"]),
        suggested_action=data["suggested_action"],
        payload=data["payload"],
        subscription_id=_optional_uuid(data.get("subscription_id")),
        dedupe_key=data.get("dedupe_key", ""),
    )


def _explanation_from_dict(data: dict) -> AlertExplanation:
    return AlertExplanation(
        rule_id=data["rule_id"],
        title=data["title"],
        what_triggered=data["what_triggered"],
        rule_rationale=data["rule_rationale"],
        evidence=data["evidence"],
        recommended_action=data["recommended_action"],
        source_section=data["source_section"],
    )


def _ticket_from_dict(data: Optional[dict]) -> Optional[OrderTicket]:
    if data is None:
        return None
    allocations = tuple(
        AccountAllocation(_uuid(item["account_id"]), Decimal(item["qty"]))
        for item in data.get("account_allocations", [])
    )
    return OrderTicket(
        ticker=data["ticker"],
        action=data["action"],
        qty=Decimal(data["qty"]),
        order_type=data["order_type"],
        rationale_rule_ids=tuple(data["rationale_rule_ids"]),
        copy_text=data["copy_text"],
        account_allocations=allocations,
        stop_price=_decimal(data.get("stop_price")),
        limit_price=_decimal(data.get("limit_price")),
        time_in_force=data.get("time_in_force", "day"),
    )


def _alert_from_dict(data: dict) -> AlertRecord:
    return AlertRecord(
        alert_id=_uuid(data["alert_id"]),
        result=_rule_result_from_dict(data["result"]),
        explanation=_explanation_from_dict(data["explanation"]),
        ticket=_ticket_from_dict(data.get("ticket")),
        status=data["status"],
        created_at=datetime.fromisoformat(data["created_at"]),
        acknowledged_at=_datetime(data.get("acknowledged_at")),
        ack_kind=data.get("ack_kind"),
        ack_note=data.get("ack_note", ""),
    )


def _notification_from_row(row: sqlite3.Row) -> NotificationRecord:
    keys = set(row.keys())
    return NotificationRecord(
        notification_id=_uuid(row["notification_id"]),
        portfolio_id=_uuid(row["portfolio_id"]),
        alert_id=_uuid(row["alert_id"]),
        ticker=row["ticker"],
        rule_id=row["rule_id"],
        channel=row["channel"],
        status=row["status"],
        subject=row["subject"],
        body=row["body"],
        created_at=datetime.fromisoformat(row["created_at"]),
        error=row["error"],
        retry_count=int(row["retry_count"]) if "retry_count" in keys else 0,
        provider_response=row["provider_response"] if "provider_response" in keys else "",
    )


def _default_notification_settings(portfolio_id: UUID) -> dict:
    return {
        "portfolio_id": portfolio_id,
        "email_enabled": False,
        "email_recipients": (),
        "telegram_enabled": False,
        "telegram_chat_id": "",
        "created_at": None,
        "updated_at": None,
    }


def _notification_settings_from_row(row: sqlite3.Row) -> dict:
    return {
        "portfolio_id": _uuid(row["portfolio_id"]),
        "email_enabled": bool(row["email_enabled"]),
        "email_recipients": tuple(json.loads(row["email_recipients_json"])),
        "telegram_enabled": bool(row["telegram_enabled"]),
        "telegram_chat_id": row["telegram_chat_id"],
        "created_at": datetime.fromisoformat(row["created_at"]),
        "updated_at": datetime.fromisoformat(row["updated_at"]),
    }


def _market_data_status_from_row(row: sqlite3.Row) -> dict:
    return {
        "ticker": row["ticker"],
        "data_source": row["data_source"],
        "data_source_label": row["data_source_label"],
        "data_loaded_at": row["data_loaded_at"],
        "bars_start_date": row["bars_start_date"],
        "bars_end_date": row["bars_end_date"],
        "bars_count": int(row["bars_count"]),
        "last_attempt_source": row["last_attempt_source"],
        "last_attempt_label": row["last_attempt_label"],
        "last_attempt_at": row["last_attempt_at"],
        "last_attempt_status": row["last_attempt_status"],
        "last_error": row["last_error"],
    }


def _monitor_run_from_row(row: sqlite3.Row) -> dict:
    return {
        "run_id": _uuid(row["run_id"]),
        "user_id": _uuid(row["user_id"]),
        "portfolio_id": _uuid(row["portfolio_id"]),
        "asof": date.fromisoformat(row["asof"]),
        "stage": row["stage"],
        "status": row["status"],
        "started_at": datetime.fromisoformat(row["started_at"]),
        "completed_at": _datetime(row["completed_at"]),
        "provider": row["provider"],
        "ticker_count": int(row["ticker_count"]),
        "market_data_updated_count": int(row["market_data_updated_count"]),
        "market_data_failed_count": int(row["market_data_failed_count"]),
        "alerts_created_count": int(row["alerts_created_count"]),
        "alerts_refreshed_count": int(row["alerts_refreshed_count"]),
        "alerts_resolved_count": int(row["alerts_resolved_count"]),
        "notifications_count": int(row["notifications_count"]),
        "error": row["error"],
    }


def _monitor_run_item_from_row(row: sqlite3.Row) -> dict:
    return {
        "run_item_id": _uuid(row["run_item_id"]),
        "run_id": _uuid(row["run_id"]),
        "portfolio_id": _uuid(row["portfolio_id"]),
        "portfolio_ticker_id": _uuid(row["portfolio_ticker_id"]),
        "ticker": row["ticker"],
        "rule_id": row["rule_id"],
        "status": row["status"],
        "alert_id": _optional_uuid(row["alert_id"]),
        "dedupe_key": row["dedupe_key"],
        "evidence": json.loads(row["evidence_json"]),
        "created_at": datetime.fromisoformat(row["created_at"]),
    }


def _alert_event_from_row(row: sqlite3.Row) -> dict:
    return {
        "event_id": _uuid(row["event_id"]),
        "alert_id": _uuid(row["alert_id"]),
        "run_id": _optional_uuid(row["run_id"]),
        "user_id": _uuid(row["user_id"]),
        "portfolio_id": _uuid(row["portfolio_id"]),
        "portfolio_ticker_id": _uuid(row["portfolio_ticker_id"]),
        "ticker": row["ticker"],
        "rule_id": row["rule_id"],
        "kind": row["kind"],
        "occurred_at": datetime.fromisoformat(row["occurred_at"]),
        "payload": json.loads(row["payload_json"]),
    }


class SQLiteStore:
    def __init__(self, path: str | Path | sqlite3.Connection) -> None:
        if isinstance(path, sqlite3.Connection):
            self.conn = path
        else:
            self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        self._closed = False
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    @classmethod
    def in_memory(cls) -> "SQLiteStore":
        return cls(sqlite3.connect(":memory:", check_same_thread=False))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self.conn.close()
            self._closed = True

    def init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._ensure_column(
                "notification_log",
                "retry_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                "notification_log",
                "provider_response",
                "TEXT NOT NULL DEFAULT ''",
            )
            self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        }
        if column not in existing:
            self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, definition))

    def save_portfolio(self, portfolio: Portfolio) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO portfolios(portfolio_id, user_id, name, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(portfolio_id) DO UPDATE SET
                  name=excluded.name,
                  status=excluded.status
                """,
                (str(portfolio.portfolio_id), str(portfolio.user_id), portfolio.name, portfolio.status),
            )
            self.conn.commit()

    def get_portfolio(self, portfolio_id: UUID) -> Optional[Portfolio]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM portfolios WHERE portfolio_id = ?",
                (str(portfolio_id),),
            ).fetchone()
            if row is None:
                return None
            return Portfolio(
                portfolio_id=_uuid(row["portfolio_id"]),
                user_id=_uuid(row["user_id"]),
                name=row["name"],
                status=row["status"],
            )

    def list_portfolios(self, user_id: UUID) -> Tuple[Portfolio, ...]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM portfolios WHERE user_id = ? ORDER BY name",
                (str(user_id),),
            ).fetchall()
            return tuple(
                Portfolio(_uuid(row["portfolio_id"]), _uuid(row["user_id"]), row["name"], row["status"])
                for row in rows
            )

    def save_tickers(self, tickers: Iterable[PortfolioTickerView]) -> None:
        with self._lock:
            with self.conn:
                for ticker in tickers:
                    self.conn.execute(
                        """
                        INSERT INTO portfolio_tickers(
                          portfolio_ticker_id, portfolio_id, user_id, ticker, type, status,
                          position_id, account_ids_json, entry_date, entry_price, shares,
                          current_profit_lock, user_exit_price, margin_used, notes
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(portfolio_ticker_id) DO UPDATE SET
                          type=excluded.type,
                          status=excluded.status,
                          position_id=excluded.position_id,
                          account_ids_json=excluded.account_ids_json,
                          entry_date=excluded.entry_date,
                          entry_price=excluded.entry_price,
                          shares=excluded.shares,
                          current_profit_lock=excluded.current_profit_lock,
                          user_exit_price=excluded.user_exit_price,
                          margin_used=excluded.margin_used,
                          notes=excluded.notes
                        """,
                        (
                            str(ticker.portfolio_ticker_id),
                            str(ticker.portfolio_id),
                            str(ticker.user_id),
                            ticker.ticker,
                            ticker.type,
                            ticker.status,
                            str(ticker.position_id) if ticker.position_id else None,
                            json.dumps([str(item) for item in ticker.account_ids]),
                            ticker.entry_date.isoformat() if ticker.entry_date else None,
                            str(ticker.entry_price) if ticker.entry_price is not None else None,
                            str(ticker.shares) if ticker.shares is not None else None,
                            str(ticker.current_profit_lock) if ticker.current_profit_lock is not None else None,
                            str(ticker.user_exit_price) if ticker.user_exit_price is not None else None,
                            1 if ticker.margin_used else 0,
                            ticker.notes,
                        ),
                    )

    def list_tickers(self, portfolio_id: UUID, *, include_inactive: bool = True) -> Tuple[PortfolioTickerView, ...]:
        with self._lock:
            if include_inactive:
                rows = self.conn.execute(
                    "SELECT * FROM portfolio_tickers WHERE portfolio_id = ? ORDER BY ticker",
                    (str(portfolio_id),),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM portfolio_tickers WHERE portfolio_id = ? AND status = 'active' ORDER BY ticker",
                    (str(portfolio_id),),
                ).fetchall()
            return tuple(self._ticker_from_row(row) for row in rows)

    def _ticker_from_row(self, row: sqlite3.Row) -> PortfolioTickerView:
        account_ids = tuple(UUID(value) for value in json.loads(row["account_ids_json"]))
        bars = self.get_bars(row["ticker"], end=date.max)
        return PortfolioTickerView(
            portfolio_id=_uuid(row["portfolio_id"]),
            portfolio_ticker_id=_uuid(row["portfolio_ticker_id"]),
            user_id=_uuid(row["user_id"]),
            ticker=row["ticker"],
            type=row["type"],
            status=row["status"],
            position_id=_optional_uuid(row["position_id"]),
            account_ids=account_ids,
            entry_date=_date(row["entry_date"]),
            entry_price=_decimal(row["entry_price"]),
            shares=_decimal(row["shares"]),
            current_profit_lock=_decimal(row["current_profit_lock"]),
            user_exit_price=_decimal(row["user_exit_price"]),
            margin_used=bool(row["margin_used"]),
            notes=row["notes"],
            bars=bars,
        )

    def save_subscriptions(self, subscriptions: Iterable[AlertSubscription]) -> None:
        with self._lock:
            with self.conn:
                for subscription in subscriptions:
                    self.conn.execute(
                        """
                        INSERT INTO alert_subscriptions(
                          subscription_id, user_id, portfolio_id, portfolio_ticker_id,
                          ticker, rule_id, enabled, config_json, created_from_import_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(subscription_id) DO UPDATE SET
                          enabled=excluded.enabled,
                          config_json=excluded.config_json
                        """,
                        (
                            str(subscription.subscription_id),
                            str(subscription.user_id),
                            str(subscription.portfolio_id),
                            str(subscription.portfolio_ticker_id),
                            subscription.ticker,
                            subscription.rule_id,
                            1 if subscription.enabled else 0,
                            json.dumps(subscription.config, sort_keys=True),
                            str(subscription.created_from_import_id)
                            if subscription.created_from_import_id
                            else None,
                        ),
                    )

    def replace_subscriptions(self, portfolio_id: UUID, subscriptions: Iterable[AlertSubscription]) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    "DELETE FROM alert_subscriptions WHERE portfolio_id = ?",
                    (str(portfolio_id),),
                )
                for subscription in subscriptions:
                    self.conn.execute(
                        """
                        INSERT INTO alert_subscriptions(
                          subscription_id, user_id, portfolio_id, portfolio_ticker_id,
                          ticker, rule_id, enabled, config_json, created_from_import_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(subscription.subscription_id),
                            str(subscription.user_id),
                            str(subscription.portfolio_id),
                            str(subscription.portfolio_ticker_id),
                            subscription.ticker,
                            subscription.rule_id,
                            1 if subscription.enabled else 0,
                            json.dumps(subscription.config, sort_keys=True),
                            str(subscription.created_from_import_id)
                            if subscription.created_from_import_id
                            else None,
                        ),
                    )

    def list_subscriptions(self, portfolio_id: UUID) -> Tuple[AlertSubscription, ...]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM alert_subscriptions WHERE portfolio_id = ? ORDER BY ticker, rule_id",
                (str(portfolio_id),),
            ).fetchall()
            return tuple(
                AlertSubscription(
                    subscription_id=_uuid(row["subscription_id"]),
                    user_id=_uuid(row["user_id"]),
                    portfolio_id=_uuid(row["portfolio_id"]),
                    portfolio_ticker_id=_uuid(row["portfolio_ticker_id"]),
                    ticker=row["ticker"],
                    rule_id=row["rule_id"],
                    enabled=bool(row["enabled"]),
                    config=json.loads(row["config_json"]),
                    created_from_import_id=_optional_uuid(row["created_from_import_id"]),
                )
                for row in rows
            )

    def save_bars(
        self,
        ticker: str,
        bars: Iterable[Bar],
        *,
        source: Optional[str] = None,
        source_label: Optional[str] = None,
    ) -> None:
        with self._lock:
            symbol = ticker.upper()
            bars_tuple = tuple(bars)
            with self.conn:
                for bar in bars_tuple:
                    self.conn.execute(
                        """
                        INSERT INTO bars(ticker, date, open, high, low, close, adj_close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(ticker, date) DO UPDATE SET
                          open=excluded.open,
                          high=excluded.high,
                          low=excluded.low,
                          close=excluded.close,
                          adj_close=excluded.adj_close,
                          volume=excluded.volume
                        """,
                        (
                            symbol,
                            bar.date.isoformat(),
                            str(bar.open),
                            str(bar.high),
                            str(bar.low),
                            str(bar.close),
                            str(bar.adj_close),
                            bar.volume,
                        ),
                    )
                if source is not None:
                    self._record_market_data_success(
                        symbol,
                        bars_tuple,
                        source=source,
                        source_label=source_label or source,
                    )

    def get_bars(self, ticker: str, *, end: date, lookback: int = 250) -> Tuple[Bar, ...]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT * FROM bars
                WHERE ticker = ? AND date <= ?
                ORDER BY date DESC
                LIMIT ?
                """,
                (ticker.upper(), end.isoformat(), lookback),
            ).fetchall()
            return tuple(reversed([_bar_from_row(row) for row in rows]))

    def _bar_summary(self, ticker: str) -> dict:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT COUNT(*) AS bars_count, MIN(date) AS bars_start_date, MAX(date) AS bars_end_date
                FROM bars
                WHERE ticker = ?
                """,
                (ticker.upper(),),
            ).fetchone()
            return {
                "bars_count": int(row["bars_count"] or 0),
                "bars_start_date": row["bars_start_date"],
                "bars_end_date": row["bars_end_date"],
            }

    def _record_market_data_success(
        self,
        ticker: str,
        bars: Sequence[Bar],
        *,
        source: str,
        source_label: str,
    ) -> None:
        with self._lock:
            symbol = ticker.upper()
            if not bars:
                return
            ordered = sorted(bars, key=lambda bar: bar.date)
            loaded_at = _utc_now_iso()
            self.conn.execute(
                """
                INSERT INTO market_data_status(
                  ticker, data_source, data_source_label, data_loaded_at,
                  bars_start_date, bars_end_date, bars_count,
                  last_attempt_source, last_attempt_label, last_attempt_at,
                  last_attempt_status, last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                  data_source=excluded.data_source,
                  data_source_label=excluded.data_source_label,
                  data_loaded_at=excluded.data_loaded_at,
                  bars_start_date=excluded.bars_start_date,
                  bars_end_date=excluded.bars_end_date,
                  bars_count=excluded.bars_count,
                  last_attempt_source=excluded.last_attempt_source,
                  last_attempt_label=excluded.last_attempt_label,
                  last_attempt_at=excluded.last_attempt_at,
                  last_attempt_status=excluded.last_attempt_status,
                  last_error=excluded.last_error
                """,
                (
                    symbol,
                    source,
                    source_label,
                    loaded_at,
                    ordered[0].date.isoformat(),
                    ordered[-1].date.isoformat(),
                    len(ordered),
                    source,
                    source_label,
                    loaded_at,
                    "ok",
                    "",
                ),
            )

    def record_market_data_failure(
        self,
        ticker: str,
        *,
        source: str,
        source_label: str,
        error: str,
    ) -> None:
        with self._lock:
            symbol = ticker.upper()
            attempted_at = _utc_now_iso()
            existing = self.conn.execute(
                "SELECT * FROM market_data_status WHERE ticker = ?",
                (symbol,),
            ).fetchone()
            if existing:
                self.conn.execute(
                    """
                    UPDATE market_data_status
                    SET last_attempt_source = ?,
                        last_attempt_label = ?,
                        last_attempt_at = ?,
                        last_attempt_status = 'failed',
                        last_error = ?
                    WHERE ticker = ?
                    """,
                    (source, source_label, attempted_at, error, symbol),
                )
                self.conn.commit()
                return

            summary = self._bar_summary(symbol)
            has_bars = summary["bars_count"] > 0
            self.conn.execute(
                """
                INSERT INTO market_data_status(
                  ticker, data_source, data_source_label, data_loaded_at,
                  bars_start_date, bars_end_date, bars_count,
                  last_attempt_source, last_attempt_label, last_attempt_at,
                  last_attempt_status, last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    "unknown" if has_bars else "none",
                    "Unknown stored bars" if has_bars else "No stored bars",
                    None,
                    summary["bars_start_date"],
                    summary["bars_end_date"],
                    summary["bars_count"],
                    source,
                    source_label,
                    attempted_at,
                    "failed",
                    error,
                ),
            )
            self.conn.commit()

    def get_market_data_status(self, ticker: str) -> dict:
        with self._lock:
            symbol = ticker.upper()
            row = self.conn.execute(
                "SELECT * FROM market_data_status WHERE ticker = ?",
                (symbol,),
            ).fetchone()
            if row is not None:
                return _market_data_status_from_row(row)

            summary = self._bar_summary(symbol)
            if summary["bars_count"] > 0:
                return {
                    "ticker": symbol,
                    "data_source": "unknown",
                    "data_source_label": "Unknown stored bars",
                    "data_loaded_at": None,
                    "bars_start_date": summary["bars_start_date"],
                    "bars_end_date": summary["bars_end_date"],
                    "bars_count": summary["bars_count"],
                    "last_attempt_source": "",
                    "last_attempt_label": "",
                    "last_attempt_at": None,
                    "last_attempt_status": "none",
                    "last_error": "",
                }
            return {
                "ticker": symbol,
                "data_source": "none",
                "data_source_label": "No stored bars",
                "data_loaded_at": None,
                "bars_start_date": None,
                "bars_end_date": None,
                "bars_count": 0,
                "last_attempt_source": "",
                "last_attempt_label": "",
                "last_attempt_at": None,
                "last_attempt_status": "none",
                "last_error": "",
            }

    def save_alerts(self, alerts: Iterable[AlertRecord]) -> None:
        with self._lock:
            with self.conn:
                for alert in alerts:
                    self.save_alert(alert, commit=False)

    def save_alert(self, alert: AlertRecord, *, commit: bool = True) -> None:
        with self._lock:
            record_json = json.dumps(to_jsonable(alert), sort_keys=True)
            self.conn.execute(
                """
                INSERT INTO alerts(
                  alert_id, portfolio_id, portfolio_ticker_id, ticker, rule_id, dedupe_key,
                  status, created_at, acknowledged_at, ack_kind, ack_note, record_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                  status=excluded.status,
                  acknowledged_at=excluded.acknowledged_at,
                  ack_kind=excluded.ack_kind,
                  ack_note=excluded.ack_note,
                  record_json=excluded.record_json
                """,
                (
                    str(alert.alert_id),
                    str(alert.result.portfolio_id),
                    str(alert.result.portfolio_ticker_id),
                    alert.result.ticker,
                    alert.result.rule_id,
                    alert.result.dedupe_key,
                    alert.status,
                    alert.created_at.isoformat(),
                    alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                    alert.ack_kind,
                    alert.ack_note,
                    record_json,
                ),
            )
            if commit:
                self.conn.commit()

    def list_alerts(self, portfolio_id: UUID) -> Tuple[AlertRecord, ...]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT record_json FROM alerts WHERE portfolio_id = ? ORDER BY created_at, alert_id",
                (str(portfolio_id),),
            ).fetchall()
            return tuple(_alert_from_dict(json.loads(row["record_json"])) for row in rows)

    def resolve_stale_open_alerts(
        self,
        portfolio_id: UUID,
        active_dedupe_keys: Iterable[str],
    ) -> Tuple[AlertRecord, ...]:
        with self._lock:
            active_keys = set(active_dedupe_keys)
            open_alerts = [
                alert
                for alert in self.list_alerts(portfolio_id)
                if alert.status in {"new", "sent"} and alert.result.dedupe_key not in active_keys
            ]
            if not open_alerts:
                return ()

            with self.conn:
                for alert in open_alerts:
                    self.save_alert(replace(alert, status="resolved"), commit=False)
            return tuple(replace(alert, status="resolved") for alert in open_alerts)

    def get_alert(self, portfolio_id: UUID, alert_id: UUID) -> Optional[AlertRecord]:
        with self._lock:
            row = self.conn.execute(
                "SELECT record_json FROM alerts WHERE portfolio_id = ? AND alert_id = ?",
                (str(portfolio_id), str(alert_id)),
            ).fetchone()
            if row is None:
                return None
            return _alert_from_dict(json.loads(row["record_json"]))

    def save_notifications(self, notifications: Iterable[NotificationRecord]) -> None:
        with self._lock:
            with self.conn:
                for notification in notifications:
                    self.conn.execute(
                        """
                        INSERT INTO notification_log(
                          notification_id, portfolio_id, alert_id, ticker, rule_id,
                          channel, status, subject, body, created_at, error,
                          retry_count, provider_response
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(alert_id, channel) DO UPDATE SET
                          status=excluded.status,
                          subject=excluded.subject,
                          body=excluded.body,
                          error=excluded.error,
                          retry_count=excluded.retry_count,
                          provider_response=excluded.provider_response
                        """,
                        (
                            str(notification.notification_id),
                            str(notification.portfolio_id),
                            str(notification.alert_id),
                            notification.ticker,
                            notification.rule_id,
                            notification.channel,
                            notification.status,
                            notification.subject,
                            notification.body,
                            notification.created_at.isoformat(),
                            notification.error,
                            notification.retry_count,
                            notification.provider_response,
                        ),
                    )

    def list_notifications(self, portfolio_id: UUID) -> Tuple[NotificationRecord, ...]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT * FROM notification_log
                WHERE portfolio_id = ?
                ORDER BY created_at DESC, notification_id DESC
                """,
                (str(portfolio_id),),
            ).fetchall()
            return tuple(_notification_from_row(row) for row in rows)

    def get_notification_settings(self, portfolio_id: UUID) -> dict:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM notification_settings WHERE portfolio_id = ?",
                (str(portfolio_id),),
            ).fetchone()
            if row is None:
                return _default_notification_settings(portfolio_id)
            return _notification_settings_from_row(row)

    def save_notification_settings(
        self,
        portfolio_id: UUID,
        *,
        email_enabled: bool = False,
        email_recipients: Iterable[str] = (),
        telegram_enabled: bool = False,
        telegram_chat_id: str = "",
    ) -> dict:
        with self._lock:
            now = datetime.utcnow().replace(microsecond=0)
            current = self.get_notification_settings(portfolio_id)
            created_at = current["created_at"] or now
            recipients = normalize_email_recipients(email_recipients)
            self.conn.execute(
                """
                INSERT INTO notification_settings(
                  portfolio_id, email_enabled, email_recipients_json,
                  telegram_enabled, telegram_chat_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(portfolio_id) DO UPDATE SET
                  email_enabled=excluded.email_enabled,
                  email_recipients_json=excluded.email_recipients_json,
                  telegram_enabled=excluded.telegram_enabled,
                  telegram_chat_id=excluded.telegram_chat_id,
                  updated_at=excluded.updated_at
                """,
                (
                    str(portfolio_id),
                    1 if email_enabled else 0,
                    json.dumps(recipients),
                    1 if telegram_enabled else 0,
                    str(telegram_chat_id or "").strip(),
                    created_at.isoformat(),
                    now.isoformat(),
                ),
            )
            self.conn.commit()
            return self.get_notification_settings(portfolio_id)

    def save_scorecard_event(self, event: ScorecardEvent) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO scorecard_events(
                  event_id, user_id, portfolio_id, portfolio_ticker_id, ticker,
                  alert_id, kind, rule_id, occurred_at, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (
                    str(event.event_id),
                    str(event.user_id),
                    str(event.portfolio_id),
                    str(event.portfolio_ticker_id),
                    event.ticker,
                    str(event.alert_id),
                    event.kind,
                    event.rule_id,
                    event.occurred_at.isoformat(),
                    event.note,
                ),
            )
            self.conn.commit()

    def save_scorecard_event_if_not_exists(self, event: ScorecardEvent) -> bool:
        """Write event only if no event with the same (alert_id, kind) exists.

        Returns True if the event was written, False if already present.
        This prevents duplicate deferred/missed events on repeated evaluate runs.
        """
        with self._lock:
            existing = self.conn.execute(
                "SELECT 1 FROM scorecard_events WHERE alert_id = ? AND kind = ?",
                (str(event.alert_id), event.kind),
            ).fetchone()
            if existing is not None:
                return False
            self.save_scorecard_event(event)
            return True

    def list_scorecard_events(self, portfolio_id: UUID) -> Tuple[ScorecardEvent, ...]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM scorecard_events WHERE portfolio_id = ? ORDER BY occurred_at, event_id",
                (str(portfolio_id),),
            ).fetchall()
            return tuple(
                ScorecardEvent(
                    event_id=_uuid(row["event_id"]),
                    user_id=_uuid(row["user_id"]),
                    portfolio_id=_uuid(row["portfolio_id"]),
                    portfolio_ticker_id=_uuid(row["portfolio_ticker_id"]),
                    ticker=row["ticker"],
                    alert_id=_uuid(row["alert_id"]),
                    kind=row["kind"],
                    rule_id=row["rule_id"],
                    occurred_at=datetime.fromisoformat(row["occurred_at"]),
                    note=row["note"],
                )
                for row in rows
            )

    def start_monitor_run(
        self,
        *,
        user_id: UUID,
        portfolio_id: UUID,
        asof: date,
        stage: str = "evaluate",
        provider: str = "stored-bars",
        ticker_count: int = 0,
    ) -> dict:
        with self._lock:
            run_id = uuid4()
            started_at = datetime.utcnow().replace(microsecond=0)
            self.conn.execute(
                """
                INSERT INTO monitor_runs(
                  run_id, user_id, portfolio_id, asof, stage, status, started_at,
                  completed_at, provider, ticker_count, market_data_updated_count,
                  market_data_failed_count, alerts_created_count, alerts_refreshed_count,
                  alerts_resolved_count, notifications_count, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_id),
                    str(user_id),
                    str(portfolio_id),
                    asof.isoformat(),
                    stage,
                    "running",
                    started_at.isoformat(),
                    None,
                    provider,
                    ticker_count,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    "",
                ),
            )
            self.conn.commit()
            return self.get_monitor_run(run_id)

    def finish_monitor_run(
        self,
        run_id: UUID,
        *,
        status: str,
        alerts_created_count: int = 0,
        alerts_refreshed_count: int = 0,
        alerts_resolved_count: int = 0,
        notifications_count: int = 0,
        market_data_updated_count: int = 0,
        market_data_failed_count: int = 0,
        error: str = "",
    ) -> dict:
        with self._lock:
            completed_at = datetime.utcnow().replace(microsecond=0).isoformat()
            self.conn.execute(
                """
                UPDATE monitor_runs
                SET status = ?,
                    completed_at = ?,
                    alerts_created_count = ?,
                    alerts_refreshed_count = ?,
                    alerts_resolved_count = ?,
                    notifications_count = ?,
                    market_data_updated_count = ?,
                    market_data_failed_count = ?,
                    error = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    completed_at,
                    alerts_created_count,
                    alerts_refreshed_count,
                    alerts_resolved_count,
                    notifications_count,
                    market_data_updated_count,
                    market_data_failed_count,
                    error,
                    str(run_id),
                ),
            )
            self.conn.commit()
            return self.get_monitor_run(run_id)

    def get_monitor_run(self, run_id: UUID) -> dict:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM monitor_runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown monitor run id: %s" % run_id)
            return _monitor_run_from_row(row)

    def latest_monitor_run(self, portfolio_id: UUID) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT * FROM monitor_runs
                WHERE portfolio_id = ?
                ORDER BY started_at DESC, run_id DESC
                LIMIT 1
                """,
                (str(portfolio_id),),
            ).fetchone()
            return _monitor_run_from_row(row) if row is not None else None

    def list_monitor_runs(self, portfolio_id: UUID, *, limit: int = 20) -> Tuple[dict, ...]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT * FROM monitor_runs
                WHERE portfolio_id = ?
                ORDER BY started_at DESC, run_id DESC
                LIMIT ?
                """,
                (str(portfolio_id), limit),
            ).fetchall()
            return tuple(_monitor_run_from_row(row) for row in rows)

    def save_monitor_run_item(
        self,
        *,
        run_id: UUID,
        alert: AlertRecord,
        status: str,
    ) -> dict:
        with self._lock:
            run_item_id = uuid4()
            created_at = datetime.utcnow().replace(microsecond=0)
            self.conn.execute(
                """
                INSERT INTO monitor_run_items(
                  run_item_id, run_id, portfolio_id, portfolio_ticker_id, ticker,
                  rule_id, status, alert_id, dedupe_key, evidence_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_item_id),
                    str(run_id),
                    str(alert.result.portfolio_id),
                    str(alert.result.portfolio_ticker_id),
                    alert.result.ticker,
                    alert.result.rule_id,
                    status,
                    str(alert.alert_id),
                    alert.result.dedupe_key,
                    json.dumps(to_jsonable(alert.explanation.evidence), sort_keys=True),
                    created_at.isoformat(),
                ),
            )
            self.conn.commit()
            return self.list_monitor_run_items(run_id)[-1]

    def list_monitor_run_items(self, run_id: UUID) -> Tuple[dict, ...]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT * FROM monitor_run_items
                WHERE run_id = ?
                ORDER BY created_at, run_item_id
                """,
                (str(run_id),),
            ).fetchall()
            return tuple(_monitor_run_item_from_row(row) for row in rows)

    def save_alert_event(
        self,
        alert: AlertRecord,
        *,
        kind: str,
        run_id: Optional[UUID] = None,
        payload: Optional[dict] = None,
    ) -> dict:
        with self._lock:
            event_id = uuid4()
            occurred_at = datetime.utcnow()
            event_payload = payload or {}
            self.conn.execute(
                """
                INSERT INTO alert_events(
                  event_id, alert_id, run_id, user_id, portfolio_id,
                  portfolio_ticker_id, ticker, rule_id, kind, occurred_at, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event_id),
                    str(alert.alert_id),
                    str(run_id) if run_id else None,
                    str(alert.result.user_id),
                    str(alert.result.portfolio_id),
                    str(alert.result.portfolio_ticker_id),
                    alert.result.ticker,
                    alert.result.rule_id,
                    kind,
                    occurred_at.isoformat(),
                    json.dumps(to_jsonable(event_payload), sort_keys=True),
                ),
            )
            self.conn.commit()
            return self.list_alert_events(alert.result.portfolio_id)[-1]

    def list_alert_events(self, portfolio_id: UUID, *, ticker: Optional[str] = None) -> Tuple[dict, ...]:
        with self._lock:
            if ticker:
                rows = self.conn.execute(
                    """
                    SELECT * FROM alert_events
                    WHERE portfolio_id = ? AND ticker = ?
                    ORDER BY occurred_at, event_id
                    """,
                    (str(portfolio_id), ticker.upper()),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """
                    SELECT * FROM alert_events
                    WHERE portfolio_id = ?
                    ORDER BY occurred_at, event_id
                    """,
                    (str(portfolio_id),),
                ).fetchall()
            return tuple(_alert_event_from_row(row) for row in rows)
