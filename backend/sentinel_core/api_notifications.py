"""Notification settings and delivery handlers.

Extracted from http_api.py — no behaviour change.
"""
from __future__ import annotations

from http import HTTPStatus
from uuid import UUID


def handle_get_notification_settings(portfolio_id: UUID, workspace) -> tuple:
    """GET /portfolios/{id}/notification-settings"""
    return HTTPStatus.OK, {
        "settings": workspace.store.get_notification_settings(portfolio_id),
        "delivery_status": {
            "email_configured": workspace.email_provider is not None,
            "telegram_configured": workspace.telegram_provider is not None,
        },
    }


def handle_save_notification_settings(portfolio_id: UUID, body: dict, workspace) -> tuple:
    """POST /portfolios/{id}/notification-settings"""
    settings = workspace.store.save_notification_settings(
        portfolio_id,
        email_enabled=bool(body.get("email_enabled")),
        email_recipients=body.get("email_recipients") or (),
        telegram_enabled=bool(body.get("telegram_enabled")),
        telegram_chat_id=str(body.get("telegram_chat_id") or "").strip(),
    )
    return HTTPStatus.OK, {
        "settings": settings,
        "delivery_status": {
            "email_configured": workspace.email_provider is not None,
            "telegram_configured": workspace.telegram_provider is not None,
        },
    }


def handle_list_notifications(portfolio_id: UUID, workspace) -> tuple:
    """GET /portfolios/{id}/notifications"""
    return HTTPStatus.OK, {
        "notifications": workspace.list_notifications(portfolio_id=portfolio_id)
    }
