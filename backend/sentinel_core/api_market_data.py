"""Market data backfill handlers (enqueue async jobs).

Extracted from http_api.py — no behaviour change.
MASSIVE_API_KEY is never accepted from the request body; the worker reads it
from the server environment at execution time.
"""
from __future__ import annotations

from http import HTTPStatus
from uuid import UUID


def handle_backfill_massive(portfolio_id: UUID, body: dict, store) -> tuple:
    """POST /portfolios/{id}/backfill-massive — enqueue a Massive backfill job."""
    # Lazy imports avoid circular-import at module load time
    from .http_api import _parse_limited_int, _parse_iso_date

    end = _parse_iso_date(body.get("end"), "end")
    lookback = _parse_limited_int(body.get("lookback"), "lookback", default=250, minimum=1, maximum=1000)
    job = store.enqueue_job(
        portfolio_id,
        kind="backfill_massive",
        params={"lookback": lookback, "end": end.isoformat()},
    )
    return HTTPStatus.OK, {"job": job}


def handle_backfill_online(portfolio_id: UUID, body: dict, store) -> tuple:
    """POST /portfolios/{id}/backfill-online — enqueue an online (Yahoo) backfill job."""
    from .http_api import _parse_limited_int, _parse_iso_date

    end = _parse_iso_date(body.get("end"), "end")
    lookback = _parse_limited_int(body.get("lookback"), "lookback", default=250, minimum=1, maximum=1000)
    job = store.enqueue_job(
        portfolio_id,
        kind="backfill_online",
        params={"lookback": lookback, "end": end.isoformat()},
    )
    return HTTPStatus.OK, {"job": job}
