from __future__ import annotations

from dataclasses import dataclass
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Iterable, Protocol, Sequence, Tuple
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from .models import Bar


SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")


class MarketDataPort(Protocol):
    def validate_symbol(self, ticker: str) -> bool:
        ...

    def get_bars(self, ticker: str, *, end: date, lookback: int = 250) -> Tuple[Bar, ...]:
        ...


@dataclass
class InMemoryMarketDataProvider:
    bars_by_ticker: Dict[str, Tuple[Bar, ...]]

    def validate_symbol(self, ticker: str) -> bool:
        return ticker.upper() in self.bars_by_ticker

    def get_bars(self, ticker: str, *, end: date, lookback: int = 250) -> Tuple[Bar, ...]:
        bars = tuple(bar for bar in self.bars_by_ticker.get(ticker.upper(), ()) if bar.date <= end)
        return bars[-lookback:]

    @classmethod
    def from_items(cls, items: Iterable[tuple[str, Sequence[Bar]]]) -> "InMemoryMarketDataProvider":
        return cls({ticker.upper(): tuple(bars) for ticker, bars in items})


@dataclass
class YahooChartMarketDataProvider:
    range_value: str = "2y"
    interval: str = "1d"
    timeout_seconds: int = 10
    proxy_url: str | None = None

    def validate_symbol(self, ticker: str) -> bool:
        return bool(SYMBOL_RE.match(ticker.upper()))

    def get_bars(self, ticker: str, *, end: date, lookback: int = 250) -> Tuple[Bar, ...]:
        symbol = ticker.upper().replace(".", "-")
        query = urlencode({"range": self.range_value, "interval": self.interval})
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?%s" % (symbol, query)
        with _open_url(Request(url), timeout_seconds=self.timeout_seconds, proxy_url=self.proxy_url) as response:
            payload = json.loads(response.read().decode("utf-8"))
        bars = _bars_from_yahoo_chart_payload(payload)
        return tuple(bar for bar in bars if bar.date <= end)[-lookback:]


@dataclass
class MassiveMarketDataProvider:
    api_key: str
    base_url: str = "https://api.massive.com"
    timeout_seconds: int = 15
    adjusted: bool = True
    proxy_url: str | None = None

    def validate_symbol(self, ticker: str) -> bool:
        return bool(SYMBOL_RE.match(ticker.upper()))

    def get_bars(self, ticker: str, *, end: date, lookback: int = 250) -> Tuple[Bar, ...]:
        if not self.api_key:
            raise ValueError("MASSIVE_API_KEY is required")

        symbol = ticker.upper().replace(".", "-")
        calendar_days = max(lookback * 3, lookback + 10)
        start = end - timedelta(days=calendar_days)
        query = urlencode(
            {
                "adjusted": str(self.adjusted).lower(),
                "sort": "asc",
                "limit": "50000",
                "apiKey": self.api_key,
            }
        )
        url = (
            "%s/v2/aggs/ticker/%s/range/1/day/%s/%s?%s"
            % (
                self.base_url.rstrip("/"),
                quote(symbol, safe=""),
                start.isoformat(),
                end.isoformat(),
                query,
            )
        )
        payload = _load_massive_json(
            url,
            self.api_key,
            self.timeout_seconds,
            proxy_url=self.proxy_url,
        )
        bars = _bars_from_massive_aggs_payload(payload)
        return tuple(bar for bar in bars if bar.date <= end)[-lookback:]


def _decimal_from_float(value) -> Decimal:
    return Decimal(str(value))


def _bars_from_yahoo_chart_payload(payload: dict) -> Tuple[Bar, ...]:
    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise ValueError(error.get("description") or "Yahoo chart error")
    result = chart.get("result") or []
    if not result:
        return ()

    item = result[0]
    timestamps = item.get("timestamp") or []
    indicators = item.get("indicators", {})
    quote = (indicators.get("quote") or [{}])[0]
    adjclose = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
    bars = []
    for idx, timestamp in enumerate(timestamps):
        open_value = _value_at(quote.get("open"), idx)
        high_value = _value_at(quote.get("high"), idx)
        low_value = _value_at(quote.get("low"), idx)
        close_value = _value_at(quote.get("close"), idx)
        volume_value = _value_at(quote.get("volume"), idx)
        adj_close_value = _value_at(adjclose, idx) if adjclose else close_value
        if None in {open_value, high_value, low_value, close_value, volume_value, adj_close_value}:
            continue
        bars.append(
            Bar(
                date=datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date(),
                open=_decimal_from_float(open_value),
                high=_decimal_from_float(high_value),
                low=_decimal_from_float(low_value),
                close=_decimal_from_float(close_value),
                adj_close=_decimal_from_float(adj_close_value),
                volume=int(volume_value),
            )
        )
    return tuple(bars)


def _open_url(request: Request, *, timeout_seconds: int, proxy_url: str | None = None):
    if proxy_url:
        opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
        return opener.open(request, timeout=timeout_seconds)
    return urlopen(request, timeout=timeout_seconds)


def _load_massive_json(
    url: str,
    api_key: str,
    timeout_seconds: int,
    *,
    proxy_url: str | None = None,
) -> dict:
    request = Request(url, headers={"Authorization": "Bearer %s" % api_key})
    try:
        with _open_url(request, timeout_seconds=timeout_seconds, proxy_url=proxy_url) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.reason or "Massive API request failed"
        try:
            body = json.loads(exc.read().decode("utf-8"))
            message = body.get("error") or body.get("message") or body.get("status") or message
        except Exception:
            pass
        raise ValueError("Massive API error: %s" % message) from exc


def _bars_from_massive_aggs_payload(payload: dict) -> Tuple[Bar, ...]:
    status = str(payload.get("status", "")).upper()
    if status in {"ERROR", "NOT_AUTHORIZED"}:
        raise ValueError(payload.get("error") or payload.get("message") or "Massive API error")

    bars = []
    for item in payload.get("results") or ():
        open_value = item.get("o", item.get("open"))
        high_value = item.get("h", item.get("high"))
        low_value = item.get("l", item.get("low"))
        close_value = item.get("c", item.get("close"))
        volume_value = item.get("v", item.get("volume"))
        timestamp = item.get("t", item.get("timestamp", item.get("window_start")))
        trading_date = item.get("date") or item.get("session_end_date")
        if None in {open_value, high_value, low_value, close_value, volume_value}:
            continue
        if trading_date:
            bar_date = date.fromisoformat(str(trading_date))
        elif timestamp is not None:
            bar_date = datetime.fromtimestamp(int(timestamp) / 1000, tz=timezone.utc).date()
        else:
            continue
        bars.append(
            Bar(
                date=bar_date,
                open=_decimal_from_float(open_value),
                high=_decimal_from_float(high_value),
                low=_decimal_from_float(low_value),
                close=_decimal_from_float(close_value),
                adj_close=_decimal_from_float(close_value),
                volume=int(volume_value),
            )
        )
    return tuple(bars)


def _value_at(values, idx: int):
    if values is None or idx >= len(values):
        return None
    return values[idx]
