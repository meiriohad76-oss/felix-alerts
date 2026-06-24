"""Job queue polling handlers.

Extracted from http_api.py — no behaviour change.
"""
from __future__ import annotations

from http import HTTPStatus
from uuid import UUID


def handle_get_job(job_id_str: str, workspace) -> tuple:
    """GET /jobs/{job_id} — return current job status."""
    # Lazy import avoids circular-import at module load time
    from .http_api import ApiError, _parse_uuid

    job_id = _parse_uuid(job_id_str, "job_id")
    job = workspace.store.get_job(job_id)
    if job is None:
        raise ApiError(HTTPStatus.NOT_FOUND, "Job not found: %s" % job_id)
    return HTTPStatus.OK, {"job": job}
