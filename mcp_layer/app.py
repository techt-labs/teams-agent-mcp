"""Standalone MCP layer service.

Run:  uvicorn mcp_layer.app:app --host 0.0.0.0 --port 8100

Three surfaces, one process:

  * ``/mcp-server/mcp`` — the real MCP protocol (Streamable HTTP). A
    consumer connects, auto-discovers the tools, and calls them. Bearer
    auth via ``MCP_TOOLS_TOKEN``.
  * ``/tools/*``        — the same tools as plain authenticated REST,
    for consumers that cannot speak MCP.
  * ``/teams-inbound``  — where the connector delivers each human reply;
    routed to the owning session via the store.

The consumer that receives answers is chosen from configuration at
startup (a SaaS sessions API, an HTTP callback, or a mock) — see
``consumer.py``.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mcp_layer import store
from mcp_layer.consumer import client_from_settings, set_consumer
from mcp_layer.inbound import router as inbound_router
from mcp_layer.mcp_server import mcp_app
from mcp_layer.settings import settings
from mcp_layer.tools_api import router as tools_router

log = logging.getLogger("mcp_layer.app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await store.startup()

    # Choose the consumer adapter — the swap point. A SaaS platform, an
    # in-house callback, or the mock, decided purely by configuration.
    client = client_from_settings()
    set_consumer(client)
    log.info(f"consumer adapter: {type(client).__name__}")

    if not store.is_enabled():
        log.warning(
            "mcp store is not enabled — set MCP_DATABASE_URL (or "
            "DATABASE_URL). Replies cannot be routed to sessions until it is."
        )
    if not settings.inbound_token:
        log.warning(
            "MCP_INBOUND_TOKEN is unset — the inbound webhook accepts "
            "unauthenticated posts. Set it unless this runs in a trusted "
            "network."
        )
    if not settings.connector_base_url:
        log.warning("CONNECTOR_BASE_URL is unset — the tools cannot reach Teams.")

    # Run the mounted MCP server's own lifespan too — it starts the
    # Streamable HTTP session manager. A mounted sub-app does not get its
    # lifespan run automatically, and without this the /mcp-server
    # endpoint fails with "Task group is not initialized".
    async with mcp_app.router.lifespan_context(mcp_app):
        yield

    await store.shutdown()


app = FastAPI(
    title="EA Assist MCP Layer",
    summary="Session <-> Teams-thread correlation for an agent platform.",
    lifespan=lifespan,
)
app.include_router(inbound_router)
app.include_router(tools_router)


class _BearerGate:
    """Bearer auth for the mounted MCP app.

    The mount bypasses FastAPI dependencies, so the REST port's token
    gate does not cover it — without this wrapper the MCP protocol
    endpoint would be an unauthenticated door to ``ask_human`` (posting
    at real people) and channel membership. Same token as the REST
    tools, checked constant-time; unset token fails closed.
    """

    def __init__(self, inner):
        self._inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._inner(scope, receive, send)
            return

        import hmac

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        scheme, _, token = headers.get("authorization", "").partition(" ")
        authorized = (
            bool(settings.tools_token)
            and scheme.lower() == "bearer"
            and hmac.compare_digest(token, settings.tools_token)
        )
        if not authorized:
            from starlette.responses import JSONResponse

            status = 503 if not settings.tools_token else 401
            await JSONResponse(
                {"detail": "invalid or missing bearer token"}, status_code=status
            )(scope, receive, send)
            return
        await self._inner(scope, receive, send)


# The real MCP server, over the MCP protocol (Streamable HTTP) at
# /mcp-server/mcp. A client connects here and auto-discovers every tool —
# this is what makes the agent an MCP client, not a set of hardcoded calls.
app.mount("/mcp-server", _BearerGate(mcp_app))
