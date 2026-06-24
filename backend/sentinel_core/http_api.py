from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import os
import re
import socket
import subprocess
from datetime import date
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import urlopen
from uuid import UUID

from .holding_scores import build_holding_scores
from .indicators import average_volume_previous, distance_pct, quantize_price, sma_adj_close
from .market_data import (
    MassiveMarketDataProvider,
    YahooChartMarketDataProvider,
)
from .notifications import EmailMessage
from .persistent_service import PersistentSentinelWorkspace
from .rule_catalog import get_rule
from .scorecard import stale_exit_events
from .serialization import to_jsonable
from .sqlite_store import SQLiteStore
from .subscriptions import applicable_rule_ids
from .xlsx_import import xlsx_bytes_to_sentinel_csv


DEFAULT_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_MAX_JSON_BODY_BYTES = 2 * 1024 * 1024
VALID_ACK_KINDS = {"placed", "placed_with_modification", "ignored"}
_PROXY_CACHE_READY = False
_PROXY_CACHE_VALUE: Optional[str] = None


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _parse_positive_finite_decimal(value, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception as exc:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "setup data values must be valid finite numbers",
        ) from exc
    if not parsed.is_finite():
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "setup data values must be valid finite numbers",
        )
    if parsed <= 0:
        raise ApiError(HTTPStatus.BAD_REQUEST, "%s must be greater than zero" % field_name)
    return parsed


def _configured_max_json_body_bytes() -> int:
    raw = os.environ.get("SENTINEL_MAX_JSON_BODY_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_JSON_BODY_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_JSON_BODY_BYTES
    return value if value > 0 else DEFAULT_MAX_JSON_BODY_BYTES


def _configured_cors_origin() -> str:
    origin = os.environ.get("SENTINEL_ALLOWED_ORIGIN", "").strip()
    return "" if origin == "*" else origin


def _parse_iso_date(value, field_name: str) -> date:
    try:
        return date.fromisoformat(value or date.today().isoformat())
    except (TypeError, ValueError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "%s must be YYYY-MM-DD" % field_name) from exc


def _parse_limited_int(
    value,
    field_name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "%s must be an integer" % field_name) from exc
    if parsed < minimum or parsed > maximum:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "%s must be between %s and %s" % (field_name, minimum, maximum),
        )
    return parsed


def _parse_uuid(value: str, field_name: str) -> "UUID":
    """Parse a UUID string, raising ApiError 400 on invalid input.

    Use this for all route, query, and body UUID parameters instead of
    calling UUID() directly — UUID() raises ValueError which maps to 500.
    """
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "Invalid %s: must be a valid UUID" % field_name,
        ) from exc


class SentinelApi:
    def __init__(self, workspace: PersistentSentinelWorkspace) -> None:
        self.workspace = workspace

    def handle(self, method: str, path: str, query: dict, body: dict) -> tuple[HTTPStatus, dict]:
        if method == "GET" and path == "/health":
            return HTTPStatus.OK, {"ok": True}
        if method == "GET" and path == "/market-data/config":
            return HTTPStatus.OK, self.market_data_config()
        if method == "POST" and path == "/portfolio-file/convert":
            return HTTPStatus.OK, self.convert_portfolio_file(body)
        if method == "POST" and path == "/portfolios":
            return HTTPStatus.CREATED, self.create_portfolio(body)
        if method == "GET" and path == "/portfolios":
            user_id = _parse_uuid(query.get("user_id", [str(DEFAULT_USER_ID)])[0], "user_id")
            return HTTPStatus.OK, {"portfolios": self.workspace.store.list_portfolios(user_id)}

        match = re.fullmatch(r"/portfolios/([^/]+)", path)
        if method == "GET" and match:
            return HTTPStatus.OK, self.portfolio_detail(_parse_uuid(match.group(1), "portfolio_id"))

        match = re.fullmatch(r"/portfolios/([^/]+)/preview", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.preview_csv(_parse_uuid(match.group(1), "portfolio_id"), body)

        match = re.fullmatch(r"/portfolios/([^/]+)/import", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.import_csv(_parse_uuid(match.group(1), "portfolio_id"), body)

        match = re.fullmatch(r"/portfolios/([^/]+)/tickers/([^/]+)", path)
        if method == "GET" and match:
            return HTTPStatus.OK, self.ticker_detail(_parse_uuid(match.group(1), "portfolio_id"), unquote(match.group(2)))

        match = re.fullmatch(r"/portfolios/([^/]+)/tickers/([^/]+)/classify", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.classify_ticker(_parse_uuid(match.group(1), "portfolio_id"), unquote(match.group(2)), body)

        match = re.fullmatch(r"/portfolios/([^/]+)/tickers/([^/]+)/setup-data", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.update_ticker_setup_data(
                _parse_uuid(match.group(1), "portfolio_id"),
                unquote(match.group(2)),
                body,
            )

        match = re.fullmatch(r"/portfolios/([^/]+)/tickers/classify-unknown", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.classify_unknown_tickers(_parse_uuid(match.group(1), "portfolio_id"), body)

        match = re.fullmatch(r"/portfolios/([^/]+)/backfill-online", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.backfill_online(_parse_uuid(match.group(1), "portfolio_id"), body)

        match = re.fullmatch(r"/portfolios/([^/]+)/backfill-massive", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.backfill_massive(_parse_uuid(match.group(1), "portfolio_id"), body)

        match = re.fullmatch(r"/portfolios/([^/]+)/evaluate", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.evaluate(_parse_uuid(match.group(1), "portfolio_id"), body)

        match = re.fullmatch(r"/portfolios/([^/]+)/runs/latest", path)
        if method == "GET" and match:
            run = self.workspace.store.latest_monitor_run(_parse_uuid(match.group(1), "portfolio_id"))
            return HTTPStatus.OK, {"run": run}

        match = re.fullmatch(r"/portfolios/([^/]+)/runs", path)
        if method == "GET" and match:
            return HTTPStatus.OK, {"runs": self.workspace.store.list_monitor_runs(_parse_uuid(match.group(1), "portfolio_id"))}

        match = re.fullmatch(r"/portfolios/([^/]+)/alerts", path)
        if method == "GET" and match:
            portfolio_id = _parse_uuid(match.group(1), "portfolio_id")
            return HTTPStatus.OK, {"alerts": self.workspace.list_alerts(portfolio_id=portfolio_id)}

        match = re.fullmatch(r"/portfolios/([^/]+)/alert-events", path)
        if method == "GET" and match:
            portfolio_id = _parse_uuid(match.group(1), "portfolio_id")
            ticker = query.get("ticker", [""])[0].strip().upper() or None
            return HTTPStatus.OK, {
                "events": self.workspace.store.list_alert_events(portfolio_id, ticker=ticker)
            }

        match = re.fullmatch(r"/portfolios/([^/]+)/notification-settings", path)
        if method == "GET" and match:
            return HTTPStatus.OK, self.notification_settings(_parse_uuid(match.group(1), "portfolio_id"))
        if method == "POST" and match:
            return HTTPStatus.OK, self.save_notification_settings(_parse_uuid(match.group(1), "portfolio_id"), body)

        match = re.fullmatch(r"/portfolios/([^/]+)/notification-settings/test", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.test_notification_settings(_parse_uuid(match.group(1), "portfolio_id"))

        match = re.fullmatch(r"/portfolios/([^/]+)/notifications", path)
        if method == "GET" and match:
            portfolio_id = _parse_uuid(match.group(1), "portfolio_id")
            return HTTPStatus.OK, {
                "notifications": self.workspace.list_notifications(portfolio_id=portfolio_id)
            }

        match = re.fullmatch(r"/portfolios/([^/]+)/alerts/([^/]+)/ack", path)
        if method == "POST" and match:
            return HTTPStatus.OK, self.acknowledge(
                _parse_uuid(match.group(1), "portfolio_id"),
                _parse_uuid(match.group(2), "alert_id"),
                body,
            )

        match = re.fullmatch(r"/portfolios/([^/]+)/maintenance/scorecard", path)
        if method == "POST" and match:
            portfolio_id = _parse_uuid(match.group(1), "portfolio_id")
            return HTTPStatus.OK, self.maintenance_scorecard(portfolio_id)

        match = re.fullmatch(r"/portfolios/([^/]+)/report", path)
        if method == "GET" and match:
            portfolio_id = _parse_uuid(match.group(1), "portfolio_id")
            return HTTPStatus.OK, {"report": self.workspace.build_report(portfolio_id=portfolio_id)}

        match = re.fullmatch(r"/jobs/([^/]+)", path)
        if method == "GET" and match:
            job_id = _parse_uuid(match.group(1), "job_id")
            job = self.workspace.store.get_job(job_id)
            if job is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "Job not found: %s" % job_id)
            return HTTPStatus.OK, {"job": job}

        raise ApiError(HTTPStatus.NOT_FOUND, "No route for %s %s" % (method, path))

    def create_portfolio(self, body: dict) -> dict:
        user_id = _parse_uuid(body.get("user_id", str(DEFAULT_USER_ID)), "user_id")
        name = body.get("name") or "Portfolio"
        portfolio = self.workspace.create_portfolio(user_id=user_id, name=name)
        return {"portfolio": portfolio}

    def notification_delivery_status(self) -> dict:
        return {
            "email_configured": self.workspace.email_provider is not None,
            "telegram_configured": self.workspace.telegram_provider is not None,
        }

    def notification_settings(self, portfolio_id: UUID) -> dict:
        return {
            "settings": self.workspace.store.get_notification_settings(portfolio_id),
            "delivery_status": self.notification_delivery_status(),
        }

    def save_notification_settings(self, portfolio_id: UUID, body: dict) -> dict:
        settings = self.workspace.store.save_notification_settings(
            portfolio_id,
            email_enabled=bool(body.get("email_enabled")),
            email_recipients=body.get("email_recipients") or (),
            telegram_enabled=bool(body.get("telegram_enabled")),
            telegram_chat_id=str(body.get("telegram_chat_id") or "").strip(),
        )
        return {
            "settings": settings,
            "delivery_status": self.notification_delivery_status(),
        }

    def test_notification_settings(self, portfolio_id: UUID) -> dict:
        settings = self.workspace.store.get_notification_settings(portfolio_id)
        portfolio = self.workspace.store.get_portfolio(portfolio_id)
        portfolio_name = portfolio.name if portfolio else "Portfolio"
        results = []
        if settings.get("email_enabled"):
            recipients = tuple(settings.get("email_recipients") or ())
            if not recipients:
                results.append({"channel": "email", "status": "failed", "error": "No email recipients are saved."})
            elif self.workspace.email_provider is None:
                results.append({"channel": "email", "status": "failed", "error": "Email provider is not configured."})
            else:
                try:
                    response = self.workspace.email_provider.send(
                        EmailMessage(
                            subject="[Sentinel] Sentinel test notification",
                            text_body=(
                                "Sentinel test notification for %s.\n\n"
                                "Email alert delivery is configured. Sentinel does not place broker orders."
                            )
                            % portfolio_name,
                        ),
                        recipients,
                    )
                    results.append({"channel": "email", "status": "sent", "provider_response": str(response or "")})
                except Exception as exc:
                    results.append({"channel": "email", "status": "failed", "error": str(exc)})
        if settings.get("telegram_enabled"):
            chat_id = str(settings.get("telegram_chat_id") or "").strip()
            if not chat_id:
                results.append({"channel": "telegram", "status": "failed", "error": "No Telegram chat id is saved."})
            elif self.workspace.telegram_provider is None:
                results.append({"channel": "telegram", "status": "failed", "error": "Telegram provider is not configured."})
            else:
                try:
                    response = self.workspace.telegram_provider.send(
                        chat_id,
                        (
                            "Sentinel test notification for %s.\n"
                            "Telegram alert delivery is configured. Sentinel does not place broker orders."
                        )
                        % portfolio_name,
                    )
                    results.append({"channel": "telegram", "status": "sent", "provider_response": str(response or "")})
                except Exception as exc:
                    results.append({"channel": "telegram", "status": "failed", "error": str(exc)})
        if not results:
            results.append({
                "channel": "none",
                "status": "failed",
                "error": "Enable email or Telegram alerts before sending a test notification.",
            })
        return {"results": tuple(results), "delivery_status": self.notification_delivery_status()}

    def maintenance_scorecard(self, portfolio_id: UUID) -> dict:
        """Sweep open exit alerts and write deferred/missed scorecard events.

        Idempotent: safe to call from a daily cron job on the Pi.
        Returns counts of newly written events only (not skipped duplicates).
        """
        open_exit_alerts = [
            a for a in self.workspace.store.list_alerts(portfolio_id)
            if a.status in {"new", "sent"} and a.result.kind == "exit"
        ]
        events = stale_exit_events(open_exit_alerts)
        deferred_written = 0
        missed_written = 0
        for event in events:
            written = self.workspace.store.save_scorecard_event_if_not_exists(event)
            if written:
                if event.kind == "deferred":
                    deferred_written += 1
                elif event.kind == "missed":
                    missed_written += 1
        return {"deferred_written": deferred_written, "missed_written": missed_written}

    def market_data_config(self) -> dict:
        massive_configured = bool(os.environ.get("MASSIVE_API_KEY", "").strip())
        return {
            "massive_configured": massive_configured,
            "massive_key_source": "server_env" if massive_configured else "none",
        }

    def convert_portfolio_file(self, body: dict) -> dict:
        filename = (body.get("filename") or "").strip()
        content_base64 = body.get("content_base64")
        if not filename:
            raise ApiError(HTTPStatus.BAD_REQUEST, "filename is required")
        if not content_base64:
            raise ApiError(HTTPStatus.BAD_REQUEST, "content_base64 is required")

        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "content_base64 is not valid base64") from exc

        extension = Path(filename).suffix.lower()
        if extension in {".csv", ".txt"}:
            return {
                "csv_text": _decode_text_file(content),
                "source_format": extension.lstrip(".") or "csv",
                "filename": filename,
            }
        if extension == ".tsv":
            return {
                "csv_text": _tsv_to_csv(_decode_text_file(content)),
                "source_format": "tsv",
                "filename": filename,
            }
        if extension in {".xlsx", ".xlsm"}:
            try:
                sheet_name, csv_text = xlsx_bytes_to_sentinel_csv(
                    content,
                    preferred_sheet_name=body.get("sheet_name") or "Holdings",
                )
            except (KeyError, ValueError, OSError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
            return {
                "csv_text": csv_text,
                "source_format": extension.lstrip("."),
                "filename": filename,
                "sheet_name": sheet_name,
            }
        if extension == ".xls":
            raise ApiError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "Legacy .xls workbooks are not supported in this standard-library prototype. Save the workbook as .xlsx or .csv, or add an .xls parser dependency later.",
            )
        raise ApiError(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            "Unsupported portfolio file type '%s'. Use .csv, .tsv, .xlsx, or .xlsm." % extension,
        )

    def portfolio_detail(self, portfolio_id: UUID) -> dict:
        portfolio = self.workspace.store.get_portfolio(portfolio_id)
        if portfolio is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "Unknown portfolio id: %s" % portfolio_id)

        tickers = self.workspace.store.list_tickers(portfolio_id)
        subscriptions = self.workspace.store.list_subscriptions(portfolio_id)
        alerts = self.workspace.store.list_alerts(portfolio_id)
        open_statuses = {"new", "sent"}

        subscriptions_by_ticker: dict[str, list] = {}
        for subscription in subscriptions:
            subscriptions_by_ticker.setdefault(subscription.ticker, []).append(subscription)

        open_alert_count_by_ticker: dict[str, int] = {}
        open_alerts_by_ticker: dict[str, list] = {}
        for alert in alerts:
            if alert.status not in open_statuses:
                continue
            ticker = alert.result.ticker
            open_alert_count_by_ticker[ticker] = open_alert_count_by_ticker.get(ticker, 0) + 1
            open_alerts_by_ticker.setdefault(ticker, []).append(alert)

        ticker_rows = []
        subscription_summary = []
        for ticker in tickers:
            ticker_subscriptions = subscriptions_by_ticker.get(ticker.ticker, [])
            enabled_rule_ids = sorted(
                subscription.rule_id for subscription in ticker_subscriptions if subscription.enabled
            )
            expected_rule_ids = tuple(applicable_rule_ids(ticker))
            latest_bar_date = ticker.bars[-1].date if ticker.bars else None
            missing_rule_ids = sorted(set(expected_rule_ids) - set(enabled_rule_ids))
            market_data_status = self.workspace.store.get_market_data_status(ticker.ticker)
            trigger_summary = _trigger_summary(ticker, ticker_subscriptions)
            holding_scores = build_holding_scores(
                ticker=ticker,
                trigger_summary=trigger_summary,
                market_data_status=market_data_status,
                open_alerts=open_alerts_by_ticker.get(ticker.ticker, ()),
                missing_rule_ids=missing_rule_ids,
                bars_count=len(ticker.bars),
            )

            ticker_rows.append(
                {
                    "portfolio_ticker_id": ticker.portfolio_ticker_id,
                    "ticker": ticker.ticker,
                    "type": ticker.type,
                    "status": ticker.status,
                    "shares": ticker.shares,
                    "entry_date": ticker.entry_date,
                    "entry_price": ticker.entry_price,
                    "current_profit_lock": ticker.current_profit_lock,
                    "notes": ticker.notes,
                    "bars_count": len(ticker.bars),
                    "latest_bar_date": latest_bar_date,
                    "market_data_status": market_data_status,
                    "expected_rule_count": len(expected_rule_ids),
                    "enabled_subscription_count": len(enabled_rule_ids),
                    "enabled_rule_ids": enabled_rule_ids,
                    "missing_rule_ids": missing_rule_ids,
                    "open_alert_count": open_alert_count_by_ticker.get(ticker.ticker, 0),
                    "trigger_summary": trigger_summary,
                    "holding_scores": holding_scores,
                }
            )
            subscription_summary.append(
                {
                    "ticker": ticker.ticker,
                    "enabled_rule_ids": enabled_rule_ids,
                    "enabled_count": len(enabled_rule_ids),
                    "expected_count": len(expected_rule_ids),
                    "missing_rule_ids": missing_rule_ids,
                }
            )

        open_alerts = [alert for alert in alerts if alert.status in open_statuses]
        summary = {
            "ticker_count": len(tickers),
            "active_ticker_count": len([ticker for ticker in tickers if ticker.status == "active"]),
            "classification_needed_count": len([ticker for ticker in tickers if ticker.type == "unknown"]),
            "total_subscription_count": len(subscriptions),
            "enabled_subscription_count": len(
                [subscription for subscription in subscriptions if subscription.enabled]
            ),
            "market_data_ticker_count": len([ticker for ticker in ticker_rows if ticker["bars_count"] > 0]),
            "open_alert_count": len(open_alerts),
            "ticket_count": len([alert for alert in open_alerts if alert.ticket]),
        }
        return {
            "portfolio": portfolio,
            "summary": summary,
            "qa_summary": _portfolio_qa_summary(portfolio, ticker_rows, summary),
            "latest_run": self.workspace.store.latest_monitor_run(portfolio_id),
            "tickers": ticker_rows,
            "subscription_summary": subscription_summary,
            "subscriptions": [
                {
                    "subscription_id": subscription.subscription_id,
                    "ticker": subscription.ticker,
                    "rule_id": subscription.rule_id,
                    "enabled": subscription.enabled,
                }
                for subscription in subscriptions
            ],
        }

    def preview_csv(self, portfolio_id: UUID, body: dict) -> dict:
        user_id = _parse_uuid(body.get("user_id", str(DEFAULT_USER_ID)), "user_id")
        csv_text = body.get("csv_text")
        if not csv_text:
            raise ApiError(HTTPStatus.BAD_REQUEST, "csv_text is required")
        report = self.workspace.preview_csv(
            user_id=user_id,
            portfolio_id=portfolio_id,
            csv_text=csv_text,
            mode=body.get("mode", "merge"),
        )
        return {"import_report": report}

    def import_csv(self, portfolio_id: UUID, body: dict) -> dict:
        user_id = _parse_uuid(body.get("user_id", str(DEFAULT_USER_ID)), "user_id")
        csv_text = body.get("csv_text")
        if not csv_text:
            raise ApiError(HTTPStatus.BAD_REQUEST, "csv_text is required")
        report, subscriptions = self.workspace.import_csv(
            user_id=user_id,
            portfolio_id=portfolio_id,
            csv_text=csv_text,
            mode=body.get("mode", "merge"),
        )
        return {"import_report": report, "subscription_count": len(subscriptions)}

    def ticker_detail(self, portfolio_id: UUID, ticker: str) -> dict:
        symbol = ticker.strip().upper()
        portfolio_ticker = None
        for item in self.workspace.store.list_tickers(portfolio_id):
            if item.ticker == symbol:
                portfolio_ticker = item
                break
        if portfolio_ticker is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "Unknown ticker for portfolio: %s" % symbol)

        alerts = [
            alert
            for alert in self.workspace.store.list_alerts(portfolio_id)
            if alert.result.ticker == symbol
        ]
        subscriptions = [
            subscription
            for subscription in self.workspace.store.list_subscriptions(portfolio_id)
            if subscription.ticker == symbol
        ]
        bars = [
            {
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adj_close": bar.adj_close,
                "volume": bar.volume,
            }
            for bar in portfolio_ticker.bars
        ]
        chart_alerts = []
        for alert in alerts:
            marker_date = alert.explanation.evidence.get("asof")
            if not marker_date:
                continue
            chart_alerts.append(
                {
                    "alert_id": alert.alert_id,
                    "ticker": symbol,
                    "rule_id": alert.explanation.rule_id,
                    "title": alert.explanation.title,
                    "severity": alert.result.severity,
                    "status": alert.status,
                    "date": marker_date,
                    "has_exact_date": "asof" in alert.explanation.evidence,
                    "what_triggered": alert.explanation.what_triggered,
                    "rule_rationale": alert.explanation.rule_rationale,
                    "recommended_action": alert.explanation.recommended_action,
                    "evidence": alert.explanation.evidence,
                }
            )

        chart_context = _chart_context(portfolio_ticker, subscriptions)
        return {
            "ticker": portfolio_ticker,
            "bars": bars,
            "market_data": self.workspace.store.get_market_data_status(symbol),
            "alerts": alerts,
            "alert_events": self.workspace.store.list_alert_events(portfolio_id, ticker=symbol),
            "chart_alerts": chart_alerts,
            "indicator_series": chart_context["indicator_series"],
            "watched_levels": chart_context["watched_levels"],
            "potential_triggers": chart_context["potential_triggers"],
            "subscriptions": [_subscription_detail(subscription) for subscription in subscriptions],
        }

    def classify_ticker(self, portfolio_id: UUID, ticker: str, body: dict) -> dict:
        ticker_type = body.get("ticker_type") or body.get("type")
        if not ticker_type:
            raise ApiError(HTTPStatus.BAD_REQUEST, "ticker_type is required")
        try:
            updated, subscriptions = self.workspace.classify_ticker(
                portfolio_id=portfolio_id,
                ticker=ticker,
                ticker_type=ticker_type,
            )
        except KeyError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        return {
            "ticker": updated,
            "subscription_count": len(subscriptions),
            "portfolio_detail": self.portfolio_detail(portfolio_id),
        }

    def update_ticker_setup_data(self, portfolio_id: UUID, ticker: str, body: dict) -> dict:
        provided = {
            key: body.get(key)
            for key in ("entry_price", "current_profit_lock")
            if key in body and body.get(key) not in (None, "")
        }
        if not provided:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "entry_price or current_profit_lock is required",
            )
        entry_price = (
            _parse_positive_finite_decimal(provided["entry_price"], "entry_price")
            if "entry_price" in provided
            else None
        )
        current_profit_lock = (
            _parse_positive_finite_decimal(provided["current_profit_lock"], "current_profit_lock")
            if "current_profit_lock" in provided
            else None
        )
        try:
            updated = self.workspace.update_ticker_setup_data(
                portfolio_id=portfolio_id,
                ticker=ticker,
                entry_price=entry_price,
                current_profit_lock=current_profit_lock,
            )
        except KeyError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc
        try:
            asof = _parse_iso_date(body.get("asof"), "asof")
        except ApiError:
            raise
        self.workspace.evaluate_portfolio(portfolio_id=portfolio_id, asof=asof)
        return {
            "ticker": updated,
            "portfolio_detail": self.portfolio_detail(portfolio_id),
        }

    def classify_unknown_tickers(self, portfolio_id: UUID, body: dict) -> dict:
        ticker_type = body.get("ticker_type") or "investor"
        try:
            updated, subscriptions = self.workspace.classify_unknown_tickers(
                portfolio_id=portfolio_id,
                ticker_type=ticker_type,
            )
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        return {
            "updated_count": len(updated),
            "ticker_type": ticker_type,
            "subscription_count": len(subscriptions),
            "portfolio_detail": self.portfolio_detail(portfolio_id),
        }

    def backfill_online(self, portfolio_id: UUID, body: dict) -> dict:
        """Enqueue an online (Yahoo Chart) backfill job and return immediately."""
        end = _parse_iso_date(body.get("end"), "end")
        lookback = _parse_limited_int(body.get("lookback"), "lookback", default=250, minimum=1, maximum=1000)
        job = self.workspace.store.enqueue_job(
            portfolio_id,
            kind="backfill_online",
            params={"lookback": lookback, "end": end.isoformat()},
        )
        return {"job": job}

    def backfill_massive(self, portfolio_id: UUID, body: dict) -> dict:
        """Enqueue a Massive backfill job and return immediately.

        The API key is read from the MASSIVE_API_KEY environment variable by the
        background worker at execution time — it is never accepted from the
        request body so that browser-held secrets cannot reach the server.
        """
        end = _parse_iso_date(body.get("end"), "end")
        lookback = _parse_limited_int(body.get("lookback"), "lookback", default=250, minimum=1, maximum=1000)
        job = self.workspace.store.enqueue_job(
            portfolio_id,
            kind="backfill_massive",
            params={"lookback": lookback, "end": end.isoformat()},
        )
        return {"job": job}

    def evaluate(self, portfolio_id: UUID, body: dict) -> dict:
        asof = _parse_iso_date(body.get("asof"), "asof")
        alerts = self.workspace.evaluate_portfolio(portfolio_id=portfolio_id, asof=asof)
        run = self.workspace.store.latest_monitor_run(portfolio_id)
        notifications = [
            notification
            for notification in self.workspace.list_notifications(portfolio_id=portfolio_id)
            if notification.alert_id in {alert.alert_id for alert in alerts}
        ]
        return {"alerts": alerts, "notifications": tuple(notifications), "run": run}

    def acknowledge(self, portfolio_id: UUID, alert_id: UUID, body: dict) -> dict:
        ack_kind = body.get("ack_kind")
        if not ack_kind:
            raise ApiError(HTTPStatus.BAD_REQUEST, "ack_kind is required")
        if ack_kind not in VALID_ACK_KINDS:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "ack_kind must be placed, placed_with_modification, or ignored",
            )
        try:
            alert = self.workspace.acknowledge_alert(
                portfolio_id=portfolio_id,
                alert_id=alert_id,
                ack_kind=ack_kind,
                note=body.get("note", ""),
            )
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        except KeyError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc
        return {"alert": alert}


def _decode_text_file(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ApiError(HTTPStatus.BAD_REQUEST, "File could not be decoded as text")


def _tsv_to_csv(tsv_text: str) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for row in csv.reader(io.StringIO(tsv_text), delimiter="\t"):
        writer.writerow(row)
    return output.getvalue()


def _redact_secret(message: str, secret: str) -> str:
    return message.replace(secret, "[redacted]") if secret else message


def _detect_proxy_url(*, force_refresh: bool = False) -> Optional[str]:
    global _PROXY_CACHE_READY, _PROXY_CACHE_VALUE
    environment_proxy = _proxy_from_environment()
    if environment_proxy:
        _PROXY_CACHE_VALUE = environment_proxy
        _PROXY_CACHE_READY = True
        return environment_proxy
    if _PROXY_CACHE_READY and _PROXY_CACHE_VALUE and not force_refresh:
        return _PROXY_CACHE_VALUE

    proxy_url = _proxy_from_macos_settings()
    if proxy_url:
        _PROXY_CACHE_VALUE = proxy_url
        _PROXY_CACHE_READY = True
        return proxy_url

    # A PAC/WPAD lookup can fail transiently. Do not cache a miss forever; the
    # next market-data run should get another chance before falling back direct.
    _PROXY_CACHE_VALUE = None
    _PROXY_CACHE_READY = False
    return None


def _proxy_from_environment() -> Optional[str]:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(key)
        if value:
            return value
    return None


def _proxy_from_macos_settings() -> Optional[str]:
    try:
        completed = subprocess.run(
            ("scutil", "--proxy"),
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    output = completed.stdout or ""
    explicit_proxy = _explicit_https_proxy_from_scutil(output)
    if explicit_proxy:
        return explicit_proxy

    match = re.search(r"ProxyAutoConfigURLString\s*:\s*(\S+)", output)
    if not match:
        return None
    pac_text = ""
    pac_url = match.group(1)
    # Corporate WPAD endpoints can rotate across reachable and unreachable
    # internal IPs. Retry before falling back to direct internet.
    for _attempt in range(4):
        try:
            with urlopen(pac_url, timeout=5) as response:
                pac_text = response.read().decode("utf-8", "replace")
            if pac_text.strip():
                break
        except OSError:
            continue
    if not pac_text.strip():
        return None
    for host, port_text in re.findall(r"PROXY\s+([^;\s]+):(\d+)", pac_text, flags=re.IGNORECASE):
        port = int(port_text)
        if _can_open_tcp(host, port, timeout_seconds=3):
            return "http://%s:%s" % (host, port)
    return None


def _explicit_https_proxy_from_scutil(output: str) -> Optional[str]:
    if not re.search(r"HTTPSEnable\s*:\s*1", output):
        return None
    host_match = re.search(r"HTTPSProxy\s*:\s*(\S+)", output)
    port_match = re.search(r"HTTPSPort\s*:\s*(\d+)", output)
    if not host_match:
        return None
    return "http://%s:%s" % (host_match.group(1), port_match.group(1) if port_match else "80")


def _can_open_tcp(host: str, port: int, *, timeout_seconds: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _https_connectivity_error(
    base_url: str,
    *,
    timeout_seconds: int,
    service_label: str,
    proxy_url: Optional[str] = None,
) -> Optional[str]:
    if proxy_url:
        parsed_proxy = urlparse(proxy_url)
        proxy_host = parsed_proxy.hostname
        proxy_port = parsed_proxy.port or 80
        if not proxy_host:
            return "Configured proxy for %s is invalid: %s" % (service_label, proxy_url)
        if _can_open_tcp(proxy_host, proxy_port, timeout_seconds=timeout_seconds):
            return None
        return (
            "Cannot reach the configured proxy for %s at %s:%s. "
            "Check VPN, corporate proxy, or network settings, then run the monitor again."
            % (service_label, proxy_host, proxy_port)
        )

    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port or 443
    if not host:
        return "%s host is not configured." % service_label
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return None
    except OSError as exc:
        return (
            "Cannot reach %s at %s:%s from this computer (%s). "
            "Check internet access, VPN, firewall, proxy, or DNS settings, then run the monitor again."
            % (service_label, host, port, exc)
        )


def _https_connectivity_error_with_proxy_retry(
    base_url: str,
    *,
    timeout_seconds: int,
    service_label: str,
    proxy_url: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    connectivity_error = _https_connectivity_error(
        base_url,
        timeout_seconds=timeout_seconds,
        service_label=service_label,
        proxy_url=proxy_url,
    )
    if not connectivity_error or proxy_url:
        return connectivity_error, proxy_url

    refreshed_proxy_url = _detect_proxy_url(force_refresh=True)
    if not refreshed_proxy_url:
        return connectivity_error, proxy_url

    retry_error = _https_connectivity_error(
        base_url,
        timeout_seconds=timeout_seconds,
        service_label=service_label,
        proxy_url=refreshed_proxy_url,
    )
    return retry_error, refreshed_proxy_url


def _indicator_series(ticker, period: int) -> tuple[dict, ...]:
    return tuple(
        {
            "date": bar.date,
            "value": quantize_price(value) if value is not None else None,
        }
        for idx, bar in enumerate(ticker.bars)
        for value in (sma_adj_close(ticker.bars, idx, period),)
    )


def _latest_indicator(series: tuple[dict, ...]):
    for item in reversed(series):
        if item["value"] is not None:
            return item
    return None


def _trigger_watch(rule_id: str, *, condition: str, status: str, evidence: dict) -> dict:
    rule = get_rule(rule_id)
    return {
        "rule_id": rule.rule_id,
        "title": rule.title,
        "condition": condition,
        "status": status,
        "severity": rule.severity_default,
        "rule_rationale": rule.rationale,
        "recommended_action": rule.recommended_action_template,
        "evidence": evidence,
    }


def _portfolio_qa_summary(portfolio, ticker_rows: list[dict], summary: dict) -> dict:
    massive_failed_rows = [
        row
        for row in ticker_rows
        if row["market_data_status"].get("last_attempt_source") == "massive-stocks-aggregates"
        and row["market_data_status"].get("last_attempt_status") == "failed"
    ]
    no_market_data_rows = [row for row in ticker_rows if not row["bars_count"]]
    setup_needed_rows = [
        row
        for row in ticker_rows
        if (
            row["type"] == "unknown"
            or row["entry_price"] is None
            or row["current_profit_lock"] is None
            or row["trigger_summary"].get("data_gap_count", 0) > 0
            or row["missing_rule_ids"]
        )
    ]
    near_trigger_rows = [
        row
        for row in ticker_rows
        if (row["trigger_summary"].get("max_proximity_score") or 0) >= 75
    ]

    next_steps = []
    if massive_failed_rows:
        next_steps.append("Retry failed Massive symbols")
    if no_market_data_rows:
        next_steps.append("Load market data for symbols without bars")
    if setup_needed_rows:
        next_steps.append("Enter missing stop/profit-lock setup data")
    if summary.get("classification_needed_count"):
        next_steps.append("Classify unknown ticker styles")
    if summary.get("open_alert_count"):
        next_steps.append("Review open alert queue")
    if not next_steps:
        next_steps.append("Portfolio QA is clear")

    return {
        "portfolio_name": portfolio.name,
        "ticker_count": summary.get("ticker_count", len(ticker_rows)),
        "active_ticker_count": summary.get("active_ticker_count", 0),
        "market_data_ticker_count": summary.get("market_data_ticker_count", 0),
        "open_alert_count": summary.get("open_alert_count", 0),
        "classification_needed_count": summary.get("classification_needed_count", 0),
        "massive_failed_count": len(massive_failed_rows),
        "no_market_data_count": len(no_market_data_rows),
        "setup_needed_count": len(setup_needed_rows),
        "near_trigger_count": len(near_trigger_rows),
        "massive_failed_tickers": tuple(row["ticker"] for row in massive_failed_rows),
        "no_market_data_tickers": tuple(row["ticker"] for row in no_market_data_rows),
        "setup_needed_tickers": tuple(row["ticker"] for row in setup_needed_rows),
        "near_trigger_tickers": tuple(row["ticker"] for row in near_trigger_rows),
        "next_steps": tuple(next_steps),
    }


def _subscription_detail(subscription) -> dict:
    rule = get_rule(subscription.rule_id)
    return {
        "subscription_id": subscription.subscription_id,
        "rule_id": subscription.rule_id,
        "enabled": subscription.enabled,
        "config": subscription.config,
        "title": rule.title,
        "category": rule.pillar,
        "definition": rule.trigger_template,
        "short_summary": rule.short_summary,
        "rule_rationale": rule.rationale,
        "recommended_action": rule.recommended_action_template,
        "severity": rule.severity_default,
    }


def _exit_trigger_watch(ticker, rule_id: str, period: int) -> dict:
    rule_label = "SMA%s" % period
    if not ticker.bars:
        return _trigger_watch(
            rule_id,
            condition="Daily close below %s." % rule_label,
            status="no_data",
            evidence={"exit_ma_period": period},
        )

    idx = len(ticker.bars) - 1
    current_bar = ticker.bars[idx]
    current_sma = sma_adj_close(ticker.bars, idx, period)
    previous_sma = sma_adj_close(ticker.bars, idx - 1, period) if idx > 0 else None
    if current_sma is None:
        return _trigger_watch(
            rule_id,
            condition="Daily close below %s." % rule_label,
            status="insufficient_history",
            evidence={
                "asof": current_bar.date.isoformat(),
                "close": str(current_bar.adj_close),
                "exit_ma_period": period,
                "bars_available": len(ticker.bars),
            },
        )

    previous_close = ticker.bars[idx - 1].adj_close if idx > 0 else None
    crossed_now = (
        previous_sma is not None
        and previous_close is not None
        and previous_close >= previous_sma
        and current_bar.adj_close < current_sma
    )
    state_active = current_bar.adj_close < current_sma
    return _trigger_watch(
        rule_id,
        condition="Daily close below %s." % rule_label,
        status="triggered" if crossed_now else "active" if state_active else "watching",
        evidence={
            "asof": current_bar.date.isoformat(),
            "close": str(current_bar.adj_close),
            "exit_ma": str(quantize_price(current_sma)),
            "exit_ma_period": period,
            "distance_pct": str(distance_pct(current_bar.adj_close, current_sma)),
        },
    )


def _p7_trigger_watch(ticker) -> dict:
    if not ticker.bars:
        return _trigger_watch(
            "P7",
            condition="Volume above 5x the previous 50-day average on a down day.",
            status="no_data",
            evidence={},
        )

    idx = len(ticker.bars) - 1
    current_bar = ticker.bars[idx]
    baseline = average_volume_previous(ticker.bars, idx, 50)
    if baseline is None or baseline <= 0:
        return _trigger_watch(
            "P7",
            condition="Volume above 5x the previous 50-day average on a down day.",
            status="insufficient_history",
            evidence={"asof": current_bar.date.isoformat(), "bars_available": len(ticker.bars)},
        )

    volume_multiple = Decimal(current_bar.volume) / baseline
    is_down_day = current_bar.close < current_bar.open
    is_active = volume_multiple > Decimal("5") and is_down_day
    return _trigger_watch(
        "P7",
        condition="Volume above 5x the previous 50-day average on a down day.",
        status="active" if is_active else "watching",
        evidence={
            "asof": current_bar.date.isoformat(),
            "volume": current_bar.volume,
            "volume_sma50_previous": str(quantize_price(baseline)),
            "volume_multiple": str(volume_multiple),
            "open": str(current_bar.open),
            "close": str(current_bar.close),
        },
    )


def _t5_trigger_watch(ticker, *, primary_exit_rule_id: Optional[str] = None) -> dict:
    if not ticker.bars:
        return _trigger_watch(
            "T5",
            condition="Close is down 15% or more from entry without a primary exit alert.",
            status="no_data",
            evidence={"entry_price": str(ticker.entry_price) if ticker.entry_price is not None else None},
        )
    current_bar = ticker.bars[-1]
    if ticker.entry_price is None:
        return _trigger_watch(
            "T5",
            condition="Close is down 15% or more from entry without a primary exit alert.",
            status="missing_setup",
            evidence={"asof": current_bar.date.isoformat(), "missing": ["entry_price"]},
        )
    drawdown = (current_bar.adj_close / ticker.entry_price) - Decimal("1")
    status = "active" if drawdown <= Decimal("-0.15") else "watching"
    if status == "active" and primary_exit_rule_id:
        status = "covered_by_primary_exit"
    return _trigger_watch(
        "T5",
        condition="Close is down 15% or more from entry without a primary exit alert.",
        status=status,
        evidence={
            "asof": current_bar.date.isoformat(),
            "entry_price": str(ticker.entry_price),
            "close": str(current_bar.adj_close),
            "drawdown_pct": str(drawdown),
            "current_profit_lock": str(ticker.current_profit_lock)
            if ticker.current_profit_lock is not None
            else None,
            "primary_exit_rule_id": primary_exit_rule_id,
        },
    )


def _portfolio_trigger_watches(ticker, subscriptions) -> tuple[dict, ...]:
    enabled_rule_ids = {subscription.rule_id for subscription in subscriptions if subscription.enabled}
    potential_triggers = []
    if "P1" in enabled_rule_ids:
        potential_triggers.append(_exit_trigger_watch(ticker, "P1", 150))
    if "P2" in enabled_rule_ids:
        potential_triggers.append(_exit_trigger_watch(ticker, "P2", 50))
    primary_exit_rule_id = next(
        (
            trigger["rule_id"]
            for trigger in potential_triggers
            if trigger["status"] in {"triggered", "active"}
        ),
        None,
    )
    if "P7" in enabled_rule_ids:
        potential_triggers.append(_p7_trigger_watch(ticker))
    if "T5" in enabled_rule_ids:
        potential_triggers.append(_t5_trigger_watch(ticker, primary_exit_rule_id=primary_exit_rule_id))
    return tuple(potential_triggers)


def _float_or_none(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trigger_proximity_score(trigger: dict) -> Optional[int]:
    if trigger["status"] in {"triggered", "active"}:
        return 100
    evidence = trigger.get("evidence", {})
    rule_id = trigger["rule_id"]
    if rule_id in {"P1", "P2"}:
        distance = _float_or_none(evidence.get("distance_pct"))
        if distance is None:
            return None
        if distance <= 0:
            return 100
        return int(max(0, min(100, (1 - (distance / 0.10)) * 100)))
    if rule_id == "T5":
        drawdown = _float_or_none(evidence.get("drawdown_pct"))
        if drawdown is None:
            return None
        if drawdown <= -0.15:
            return 100
        if drawdown >= 0:
            return 0
        return int(max(0, min(100, abs(drawdown) / 0.15 * 100)))
    if rule_id == "P7":
        multiple = _float_or_none(evidence.get("volume_multiple"))
        if multiple is None:
            return None
        down_day = (
            _float_or_none(evidence.get("close")) is not None
            and _float_or_none(evidence.get("open")) is not None
            and _float_or_none(evidence.get("close")) < _float_or_none(evidence.get("open"))
        )
        score = int(max(0, min(100, multiple / 5 * 100)))
        return score if down_day else min(score, 45)
    return None


def _trigger_summary(ticker, subscriptions) -> dict:
    triggers = _portfolio_trigger_watches(ticker, subscriptions)
    proximity_items = [
        {
            "rule_id": trigger["rule_id"],
            "status": trigger["status"],
            "score": score,
        }
        for trigger in triggers
        for score in [_trigger_proximity_score(trigger)]
        if score is not None
    ]
    highest = max(proximity_items, key=lambda item: item["score"], default=None)
    action_count = len([trigger for trigger in triggers if trigger["status"] in {"triggered", "active"}])
    data_gap_count = len(
        [
            trigger
            for trigger in triggers
            if trigger["status"] in {"no_data", "insufficient_history", "missing_setup"}
        ]
    )
    return {
        "watched_count": len(triggers),
        "action_count": action_count,
        "data_gap_count": data_gap_count,
        "max_proximity_score": highest["score"] if highest else None,
        "max_proximity_rule_id": highest["rule_id"] if highest else None,
        "trigger_status_counts": {
            status: len([trigger for trigger in triggers if trigger["status"] == status])
            for status in sorted({trigger["status"] for trigger in triggers})
        },
        "proximity_items": tuple(proximity_items),
    }


def _chart_context(ticker, subscriptions) -> dict:
    sma50 = _indicator_series(ticker, 50)
    sma150 = _indicator_series(ticker, 150)
    latest_sma50 = _latest_indicator(sma50)
    latest_sma150 = _latest_indicator(sma150)

    watched_levels = []
    if latest_sma50:
        watched_levels.append(
            {
                "label": "SMA50",
                "kind": "moving_average",
                "rule_id": "P2",
                "value": latest_sma50["value"],
                "date": latest_sma50["date"],
                "description": "Trader exit moving average watch.",
            }
        )
    if latest_sma150:
        watched_levels.append(
            {
                "label": "SMA150",
                "kind": "moving_average",
                "rule_id": "P1",
                "value": latest_sma150["value"],
                "date": latest_sma150["date"],
                "description": "Investor exit moving average watch.",
            }
        )
    if ticker.entry_price is not None:
        watched_levels.append(
            {
                "label": "Entry",
                "kind": "position_level",
                "rule_id": "T5",
                "value": ticker.entry_price,
                "date": ticker.entry_date,
                "description": "Position entry baseline for drawdown and recovery-zone checks.",
            }
        )
    if ticker.current_profit_lock is not None:
        watched_levels.append(
            {
                "label": "Profit Lock",
                "kind": "position_level",
                "rule_id": "A1",
                "value": ticker.current_profit_lock,
                "date": None,
                "description": "Current recorded stop/profit-lock level.",
            }
        )

    potential_triggers = _portfolio_trigger_watches(ticker, subscriptions)

    return {
        "indicator_series": {"sma50": sma50, "sma150": sma150},
        "watched_levels": tuple(watched_levels),
        "potential_triggers": tuple(potential_triggers),
    }


def make_handler(api: SentinelApi, static_dir: Optional[Path] = None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._dispatch()

        def do_HEAD(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def log_message(self, format: str, *args) -> None:
            return

        def _dispatch(self) -> None:
            parsed = urlparse(self.path)
            if self.command in {"GET", "HEAD"} and static_dir:
                static_path = self._static_path(parsed.path)
                if static_path:
                    self._send_static(static_path)
                    return
            try:
                body = self._read_json_body()
                api_method = "GET" if self.command == "HEAD" else self.command
                status, payload = api.handle(
                    api_method,
                    parsed.path,
                    parse_qs(parsed.query),
                    body,
                )
                self._send_json(status, payload)
            except ApiError as exc:
                self._send_json(exc.status, {"error": exc.message})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def _static_path(self, request_path: str) -> Optional[Path]:
            if not static_dir:
                return None
            if request_path == "/":
                sidebar_entrypoint = static_dir / "sidebar.html"
                return sidebar_entrypoint if sidebar_entrypoint.is_file() else static_dir / "index.html"
            if request_path == "/index.html":
                return static_dir / "index.html"
            relative = Path(unquote(request_path).lstrip("/"))
            if not relative.name or ".." in relative.parts:
                return None
            candidate = static_dir / relative
            try:
                candidate.resolve().relative_to(static_dir.resolve())
            except (OSError, ValueError):
                return None
            return candidate if candidate.is_file() else None

        def _read_json_body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Content-Length must be an integer") from exc
            if length == 0:
                return {}
            max_length = _configured_max_json_body_bytes()
            if length > max_length:
                raise ApiError(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "request body is too large; limit is %s bytes" % max_length,
                )
            try:
                raw = self.rfile.read(length).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "request body must be UTF-8 JSON") from exc
            if not raw:
                return {}
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "request body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "request body must be a JSON object")
            return payload

        def _write_response_body(self, raw: bytes) -> None:
            chunk_size = 16 * 1024
            for offset in range(0, len(raw), chunk_size):
                self.wfile.write(raw[offset : offset + chunk_size])
            self.wfile.flush()

        def _send_json(self, status: HTTPStatus, payload: dict) -> None:
            raw = json.dumps(to_jsonable(payload), indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            cors_origin = _configured_cors_origin()
            if cors_origin:
                self.send_header("Access-Control-Allow-Origin", cors_origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            if self.command != "HEAD":
                self._write_response_body(raw)

        def _send_static(self, path: Path) -> None:
            if not path.exists():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "static file not found"})
                return
            raw = path.read_bytes()
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            if self.command != "HEAD":
                self._write_response_body(raw)

    Handler.api = api
    return Handler


class SentinelHTTPServer(ThreadingHTTPServer):
    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            api = getattr(self.RequestHandlerClass, "api", None)
            if api is not None:
                api.workspace.store.close()


def _run_job_worker(api: SentinelApi) -> None:
    """Background daemon thread: process queued monitor jobs one at a time."""
    import time as _time

    while True:
        _time.sleep(1)
        try:
            job = api.workspace.store.dequeue_next_job()
            if job is None:
                continue
            _execute_job(api, job)
        except Exception:
            pass  # worker must never crash


def _execute_job(api: SentinelApi, job: dict) -> None:
    """Execute a single job, updating the job row with final status."""
    job_id = job["job_id"]
    portfolio_id = job["portfolio_id"]
    params = job["params"]
    kind = job["kind"]
    tickers_done = 0
    tickers_failed = 0
    tickers_total = 0

    try:
        if kind == "backfill_massive":
            api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
            lookback = int(params.get("lookback", 250))
            end = date.fromisoformat(params.get("end", date.today().isoformat()))
            provider = MassiveMarketDataProvider(api_key=api_key)
            tickers = api.workspace.store.list_tickers(portfolio_id, include_inactive=False)
            tickers_total = len(tickers)
            for ticker in tickers:
                try:
                    bars = provider.get_bars(ticker.ticker, end=end, lookback=lookback)
                    if bars:
                        api.workspace.store.save_bars(
                            ticker.ticker, bars,
                            source="massive-stocks-aggregates",
                            source_label="Massive Stocks Aggregates",
                        )
                    tickers_done += 1
                except Exception as exc:
                    api.workspace.store.record_market_data_failure(
                        ticker.ticker,
                        source="massive-stocks-aggregates",
                        source_label="Massive Stocks Aggregates",
                        error=str(exc),
                    )
                    tickers_failed += 1

        elif kind == "backfill_online":
            lookback = int(params.get("lookback", 250))
            end = date.fromisoformat(params.get("end", date.today().isoformat()))
            provider = YahooChartMarketDataProvider(proxy_url=_detect_proxy_url())
            tickers = api.workspace.store.list_tickers(portfolio_id, include_inactive=False)
            tickers_total = len(tickers)
            for ticker in tickers:
                try:
                    bars = provider.get_bars(ticker.ticker, end=end, lookback=lookback)
                    if bars:
                        api.workspace.store.save_bars(
                            ticker.ticker, bars,
                            source="online-yahoo-chart",
                            source_label="Online fallback (Yahoo chart)",
                        )
                    tickers_done += 1
                except Exception as exc:
                    api.workspace.store.record_market_data_failure(
                        ticker.ticker,
                        source="online-yahoo-chart",
                        source_label="Online fallback (Yahoo chart)",
                        error=str(exc),
                    )
                    tickers_failed += 1

        elif kind == "evaluate":
            asof = date.fromisoformat(params.get("asof", date.today().isoformat()))
            api.workspace.evaluate_portfolio(portfolio_id=portfolio_id, asof=asof)
            tickers = api.workspace.store.list_tickers(portfolio_id, include_inactive=False)
            tickers_total = len(tickers)
            tickers_done = tickers_total

        api.workspace.store.finish_job(
            job_id,
            status="done",
            tickers_total=tickers_total,
            tickers_done=tickers_done,
            tickers_failed=tickers_failed,
        )

    except Exception as exc:
        api.workspace.store.finish_job(
            job_id,
            status="failed",
            tickers_total=tickers_total,
            tickers_done=tickers_done,
            tickers_failed=tickers_failed,
            error=str(exc),
        )


def create_server(
    *,
    db_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    static_dir: Optional[str | Path] = None,
) -> ThreadingHTTPServer:
    import threading as _threading
    store = SQLiteStore(db_path)
    api = SentinelApi(PersistentSentinelWorkspace(store))
    handler = make_handler(api, Path(static_dir) if static_dir else None)
    server = SentinelHTTPServer((host, port), handler)
    # Start background job worker
    worker = _threading.Thread(
        target=_run_job_worker, args=(api,), daemon=True, name="sentinel-job-worker"
    )
    worker.start()
    return server
