"""HTTP client for the connector's API — the MCP layer's only way to Teams.

This layer never touches Teams directly; it asks the connector to. Every
call carries the shared bearer token and returns parsed data or raises
:class:`ConnectorError`. Keeping this in one place means the tool logic
in ``core.py`` reads as intent, not plumbing.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from mcp_layer.settings import settings

log = logging.getLogger("mcp_layer.connector_client")

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class ConnectorError(RuntimeError):
    """A connector call failed. Carries no credential material."""


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.connector_api_token}"}


def _base() -> str:
    if not settings.connector_base_url:
        raise ConnectorError("CONNECTOR_BASE_URL is not set")
    return f"{settings.connector_base_url}/api/connector"


async def list_channels() -> list[dict]:
    """Channels the bot can reach: ``[{conversation_id, name}]``."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(f"{_base()}/channels", headers=_headers())
    if r.status_code != 200:
        raise ConnectorError(f"/channels returned {r.status_code}")
    return r.json().get("channels", [])


async def list_members(conversation_id: str) -> list[dict]:
    """Members of a channel: ``[{name, email, aad_object_id}]``."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(
            f"{_base()}/members",
            headers=_headers(),
            params={"conversation_id": conversation_id},
        )
    if r.status_code != 200:
        raise ConnectorError(f"/members returned {r.status_code}")
    return r.json().get("members", [])


async def create_thread(
    channel_conversation_id: str,
    text: str,
    mentions: Optional[list[dict]] = None,
) -> str:
    """Start a thread; return the new thread's conversation id."""
    body = {"channel_conversation_id": channel_conversation_id, "text": text}
    if mentions:
        body["mentions"] = mentions
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{_base()}/threads", headers=_headers(), json=body)
    if r.status_code != 200:
        raise ConnectorError(f"/threads returned {r.status_code}: {r.text[:200]}")
    return r.json()["conversation_id"]


async def say(
    conversation_id: str,
    text: str,
    mentions: Optional[list[dict]] = None,
) -> None:
    """Post a follow-up into an existing conversation (thread or chat)."""
    body = {"conversation_id": conversation_id, "text": text}
    if mentions:
        body["mentions"] = mentions
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(f"{_base()}/say", headers=_headers(), json=body)
    if r.status_code != 200:
        raise ConnectorError(f"/say returned {r.status_code}: {r.text[:200]}")
