from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional, Sequence

from .models import Bar, Pivot


def quantize_price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def mean_decimal(values: Iterable[Decimal]) -> Optional[Decimal]:
    items = tuple(values)
    if not items:
        return None
    return sum(items, Decimal("0")) / Decimal(len(items))


def index_at_or_before(bars: Sequence[Bar], asof) -> Optional[int]:
    result = None
    for idx, bar in enumerate(bars):
        if bar.date <= asof:
            result = idx
        else:
            break
    return result


def sma_adj_close(bars: Sequence[Bar], idx: int, period: int) -> Optional[Decimal]:
    if idx < period - 1:
        return None
    window = bars[idx - period + 1 : idx + 1]
    return mean_decimal(bar.adj_close for bar in window)


def average_volume_previous(bars: Sequence[Bar], idx: int, period: int = 50) -> Optional[Decimal]:
    if idx < period:
        return None
    window = bars[idx - period : idx]
    return mean_decimal(Decimal(bar.volume) for bar in window)


def crossed_below(previous_value: Decimal, previous_reference: Decimal, value: Decimal, reference: Decimal) -> bool:
    return previous_value >= previous_reference and value < reference


def distance_pct(value: Decimal, reference: Decimal) -> Decimal:
    if reference == 0:
        return Decimal("0")
    return (value / reference) - Decimal("1")


def detect_swing_pivots(bars: Sequence[Bar], strength: int = 2) -> tuple[Pivot, ...]:
    pivots = []
    if len(bars) < (strength * 2) + 1:
        return ()
    for idx in range(strength, len(bars) - strength):
        before = bars[idx - strength : idx]
        after = bars[idx + 1 : idx + strength + 1]
        current = bars[idx]
        if all(current.low < bar.low for bar in before + after):
            pivots.append(Pivot(current.date, "low", current.low, strength))
        if all(current.high > bar.high for bar in before + after):
            pivots.append(Pivot(current.date, "high", current.high, strength))
    return tuple(pivots)


def latest_pivot_low(pivots: Sequence[Pivot], asof) -> Optional[Pivot]:
    lows = [pivot for pivot in pivots if pivot.kind == "low" and pivot.date <= asof]
    if not lows:
        return None
    return sorted(lows, key=lambda pivot: pivot.date)[-1]

