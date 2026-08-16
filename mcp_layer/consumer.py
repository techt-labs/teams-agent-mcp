"""Delivering a human's answer back to whatever agent is attached.

The bridge does not care what the agent is — a SaaS platform, an
in-house tool, a test harness. It needs exactly one thing from it:
*deliver this text to this session*. That one method is the whole
consumer contract, and everything here is an implementation of it:

  * :class:`HttpAgent`            — any in-house tool with a callback URL
  * :class:`DevinSessionsAdapter` — an example adapter for one SaaS
                                    platform's sessions API; write your
                                    own the same way for another vendor
  * :class:`MockConsumer`         — records deliveries, for tests

Which one runs is decided purely by configuration at startup
(:func:`client_from_settings`) — nothing else in the pipeline knows or
cares which agent is on the other end.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol

import httpx

from mcp_layer.settings import settings

log = logging.getLogger("mcp_layer.consumer")


class ConsumerClient(Protocol):
    """The one thing this layer needs an agent platform to do."""

    async def deliver_message(self, session_id: str, text: str) -> None:
        """Deliver ``text`` to ``session_id``, waking it if asleep."""
        ...


class MockConsumer:
    """Records deliveries instead of sending them. For tests and local runs.

    The full round-trip is provable without the vendor: assert that a
    human's reply reached the right session id with the right text.
    """

    def __init__(self) -> None:
        self.delivered: list[tuple[str, str]] = []

    async def deliver_message(self, session_id: str, text: str) -> None:
        self.delivered.append((session_id, text))
        log.info(f"mock consumer: delivered to session={session_id} chars={len(text)}")


class DevinSessionsAdapter:
    """Example SaaS adapter — a thin wrapper over one vendor's sessions
    API (Devin-shaped). Kept small and unused-until-configured; treat it
    as the template for any platform that exposes "post a message into a
    session": implement ``deliver_message``, add a branch in
    :func:`client_from_settings`, done.
    """

    async def deliver_message(self, session_id: str, text: str) -> None:
        if not (settings.devin_base_url and settings.devin_org):
            raise RuntimeError("Devin is not configured (DEVIN_BASE_URL/DEVIN_ORG)")
        url = (
            f"{settings.devin_base_url}/v3/organizations/{settings.devin_org}"
            f"/sessions/{session_id}/messages"
        )
        headers = {"Authorization": f"Bearer {settings.devin_api_token}"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as c:
            r = await c.post(url, headers=headers, json={"message": text})
        if r.status_code >= 400:
            # Status only — never the body, which could echo the token.
            raise RuntimeError(f"Devin delivery failed: HTTP {r.status_code}")


class HttpAgent:
    """Delivers an answer to any consumer with a callback endpoint.

    The generic swap target: any in-house tool plugs in by pointing
    ``AGENT_CALLBACK_URL`` at its own reply endpoint. The MCP layer POSTs
    ``{session_id, text}``; the consumer resumes that session. A
    vendor-specific REST shape belongs in its own adapter (see
    :class:`DevinSessionsAdapter`) — either way the pipeline behind this
    call is identical.
    """

    async def deliver_message(self, session_id: str, text: str) -> None:
        if not settings.agent_callback_url:
            raise RuntimeError("AGENT_CALLBACK_URL is not set")
        headers = {}
        if settings.agent_callback_token:
            headers["Authorization"] = f"Bearer {settings.agent_callback_token}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as c:
            r = await c.post(
                settings.agent_callback_url,
                headers=headers,
                json={"session_id": session_id, "text": text},
            )
        if r.status_code >= 400:
            raise RuntimeError(f"agent callback failed: HTTP {r.status_code}")


def client_from_settings() -> ConsumerClient:
    """Pick the consumer adapter from configuration — the swap point.

    A SaaS sessions API, an HTTP callback, or the mock when neither is
    configured. This is the *only* place the choice is made.
    """
    if settings.devin_base_url and settings.devin_org:
        return DevinSessionsAdapter()
    if settings.agent_callback_url:
        return HttpAgent()
    return MockConsumer()


# Module-level client, swappable by tests and by configuration. Defaults
# to the mock so an unconfigured process fails safe (records, never
# silently drops) rather than erroring at import.
_client: ConsumerClient = MockConsumer()


def get_consumer() -> ConsumerClient:
    return _client


def set_consumer(client: ConsumerClient) -> None:
    global _client
    _client = client
