from __future__ import annotations

from datetime import date
from typing import Tuple

from sentinel_core.models import Bar
from tests.factories import flat_bars, make_bar


def p1_cross_below_sma150_bars() -> Tuple[Bar, ...]:
    bars = list(flat_bars(149, close=100))
    bars.append(make_bar(date(2025, 5, 30), 101))
    bars.append(make_bar(date(2025, 5, 31), 90))
    return tuple(bars)


def p7_distribution_day_bars() -> Tuple[Bar, ...]:
    bars = list(flat_bars(50, close=100))
    bars.append(make_bar(date(2025, 2, 20), close=95, open_price=100, volume=5200))
    return tuple(bars)
