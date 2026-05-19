from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Tuple, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .models import (
    CsvImportIssue,
    CsvImportReport,
    CsvImportRowResult,
    PortfolioTickerView,
    TickerType,
)

VALID_TYPES = {"investor", "trader", "index", "unknown"}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")


def normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_").replace("-", "_")


def normalize_ticker(raw: str) -> str:
    return raw.strip().upper()


def parse_optional_decimal(raw: Optional[str]) -> Optional[Decimal]:
    if raw is None or raw.strip() == "":
        return None
    try:
        value = Decimal(raw.strip().replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("expected decimal number") from exc
    if not value.is_finite():
        raise ValueError("expected finite decimal number")
    return value


def parse_optional_date(raw: Optional[str]) -> Optional[date]:
    if raw is None or raw.strip() == "":
        return None
    value = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("expected date as YYYY-MM-DD, MM/DD/YYYY, or DD/MM/YYYY")


def has_value(row: Dict[str, str], key: str) -> bool:
    value = row.get(key)
    return value is not None and value.strip() != ""


def normalize_type(raw: Optional[str], *, default_type: TickerType = "investor") -> Tuple[TickerType, Optional[str]]:
    if raw is None or raw.strip() == "":
        return default_type, None
    value = raw.strip().lower()
    if value in VALID_TYPES:
        return cast(TickerType, value), None
    return "unknown", "invalid_type"


def stable_ticker_id(portfolio_id: UUID, ticker: str) -> UUID:
    return uuid5(NAMESPACE_URL, "sentinel:portfolio-ticker:%s:%s" % (portfolio_id, ticker))


def _existing_by_ticker(
    existing: Optional[Iterable[PortfolioTickerView]],
) -> Dict[str, PortfolioTickerView]:
    return {item.ticker: item for item in existing or ()}


def import_portfolio_csv(
    csv_text: str,
    *,
    user_id: UUID,
    portfolio_id: UUID,
    existing: Optional[Iterable[PortfolioTickerView]] = None,
    mode: str = "merge",
    import_id: Optional[UUID] = None,
    default_type: TickerType = "investor",
) -> CsvImportReport:
    """Parse and apply a portfolio CSV into in-memory ticker records.

    The persistence layer will later wrap this function. Keeping it pure-ish
    lets us prove the import semantics before adding API/database concerns.
    """

    if mode not in {"merge", "replace"}:
        raise ValueError("mode must be 'merge' or 'replace'")

    import_uuid = import_id or uuid4()
    existing_map = _existing_by_ticker(existing)
    existing_remaining = set(existing_map)
    accepted_tickers: List[PortfolioTickerView] = []
    row_results: List[CsvImportRowResult] = []
    seen_in_file = set()

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV must include a header row")

    field_map = {name: normalize_header(name) for name in reader.fieldnames}
    normalized_fields = set(field_map.values())
    if "ticker" not in normalized_fields:
        raise ValueError("CSV must include a ticker column")

    created_count = 0
    updated_count = 0
    unchanged_count = 0
    rejected_count = 0

    for row_number, raw_row in enumerate(reader, start=2):
        row = {field_map[key]: value for key, value in raw_row.items() if key is not None}
        issues: List[CsvImportIssue] = []
        ticker = normalize_ticker(row.get("ticker", ""))

        if not ticker:
            issues.append(CsvImportIssue(row_number, "missing_ticker", "Ticker is required."))
        elif not TICKER_RE.match(ticker):
            issues.append(CsvImportIssue(row_number, "invalid_ticker", "Ticker format is invalid."))
        elif ticker in seen_in_file:
            issues.append(CsvImportIssue(row_number, "duplicate_ticker", "Ticker appears more than once in this CSV."))

        existing_ticker = existing_map.get(ticker)
        ticker_type, type_issue = normalize_type(row.get("type"), default_type=default_type)
        if existing_ticker and not has_value(row, "type"):
            ticker_type = existing_ticker.type
        if type_issue:
            issues.append(CsvImportIssue(row_number, type_issue, "Type must be investor, trader, index, or unknown."))

        try:
            shares = parse_optional_decimal(row.get("shares"))
        except ValueError as exc:
            shares = None
            issues.append(CsvImportIssue(row_number, "invalid_shares", str(exc)))
        if shares is not None and shares <= 0:
            issues.append(CsvImportIssue(row_number, "invalid_shares", "shares must be greater than zero."))

        try:
            entry_price = parse_optional_decimal(row.get("entry_price"))
        except ValueError as exc:
            entry_price = None
            issues.append(CsvImportIssue(row_number, "invalid_entry_price", str(exc)))
        if entry_price is not None and entry_price <= 0:
            issues.append(CsvImportIssue(row_number, "invalid_entry_price", "entry_price must be greater than zero."))

        try:
            current_profit_lock = parse_optional_decimal(row.get("current_profit_lock"))
        except ValueError as exc:
            current_profit_lock = None
            issues.append(CsvImportIssue(row_number, "invalid_current_profit_lock", str(exc)))
        if current_profit_lock is not None and current_profit_lock <= 0:
            issues.append(
                CsvImportIssue(
                    row_number,
                    "invalid_current_profit_lock",
                    "current_profit_lock must be greater than zero.",
                )
            )

        try:
            entry_date = parse_optional_date(row.get("entry_date"))
        except ValueError as exc:
            entry_date = None
            issues.append(CsvImportIssue(row_number, "invalid_entry_date", str(exc)))

        if issues:
            rejected_count += 1
            row_results.append(
                CsvImportRowResult(row_number, ticker or None, "rejected", tuple(issues))
            )
            continue

        seen_in_file.add(ticker)
        existing_remaining.discard(ticker)

        if existing_ticker:
            merged_entry_date = entry_date if has_value(row, "entry_date") else existing_ticker.entry_date
            merged_entry_price = entry_price if has_value(row, "entry_price") else existing_ticker.entry_price
            merged_shares = shares if has_value(row, "shares") else existing_ticker.shares
            merged_profit_lock = (
                current_profit_lock
                if has_value(row, "current_profit_lock")
                else existing_ticker.current_profit_lock
            )
            merged_user_exit_price = (
                current_profit_lock
                if has_value(row, "current_profit_lock")
                else existing_ticker.user_exit_price
            )
            merged_notes = (row.get("notes") or "").strip() if has_value(row, "notes") else existing_ticker.notes
            merged = PortfolioTickerView(
                portfolio_id=portfolio_id,
                portfolio_ticker_id=existing_ticker.portfolio_ticker_id,
                user_id=user_id,
                ticker=ticker,
                type=ticker_type,
                status="active",
                position_id=existing_ticker.position_id,
                account_ids=existing_ticker.account_ids,
                entry_date=merged_entry_date,
                entry_price=merged_entry_price,
                shares=merged_shares,
                current_profit_lock=merged_profit_lock,
                user_exit_price=merged_user_exit_price,
                margin_used=existing_ticker.margin_used,
                notes=merged_notes,
                bars=existing_ticker.bars,
                swing_pivots=existing_ticker.swing_pivots,
            )
            if merged == existing_ticker:
                unchanged_count += 1
                row_status = "unchanged"
            else:
                updated_count += 1
                row_status = "updated"
        else:
            notes = (row.get("notes") or "").strip()
            merged = PortfolioTickerView(
                portfolio_id=portfolio_id,
                portfolio_ticker_id=stable_ticker_id(portfolio_id, ticker),
                user_id=user_id,
                ticker=ticker,
                type=ticker_type,
                entry_date=entry_date,
                entry_price=entry_price,
                shares=shares,
                current_profit_lock=current_profit_lock,
                user_exit_price=current_profit_lock,
                notes=notes,
            )
            created_count += 1
            row_status = "accepted"

        accepted_tickers.append(merged)
        row_results.append(CsvImportRowResult(row_number, ticker, row_status, ()))

    deactivated_count = 0
    if mode == "merge":
        accepted_tickers.extend(existing_map[ticker] for ticker in sorted(existing_remaining))
    else:
        for ticker in sorted(existing_remaining):
            existing_ticker = existing_map[ticker]
            deactivated = PortfolioTickerView(
                portfolio_id=existing_ticker.portfolio_id,
                portfolio_ticker_id=existing_ticker.portfolio_ticker_id,
                user_id=existing_ticker.user_id,
                ticker=existing_ticker.ticker,
                type=existing_ticker.type,
                status="inactive",
                position_id=existing_ticker.position_id,
                account_ids=existing_ticker.account_ids,
                entry_date=existing_ticker.entry_date,
                entry_price=existing_ticker.entry_price,
                shares=existing_ticker.shares,
                current_profit_lock=existing_ticker.current_profit_lock,
                user_exit_price=existing_ticker.user_exit_price,
                margin_used=existing_ticker.margin_used,
                notes=existing_ticker.notes,
                bars=existing_ticker.bars,
                swing_pivots=existing_ticker.swing_pivots,
            )
            deactivated_count += 1
            accepted_tickers.append(deactivated)
            row_results.append(CsvImportRowResult(0, ticker, "deactivated", ()))

    return CsvImportReport(
        portfolio_id=portfolio_id,
        import_id=import_uuid,
        imported_at=datetime.utcnow(),
        tickers=tuple(sorted(accepted_tickers, key=lambda item: item.ticker)),
        row_results=tuple(row_results),
        created_count=created_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        rejected_count=rejected_count,
        deactivated_count=deactivated_count,
    )
