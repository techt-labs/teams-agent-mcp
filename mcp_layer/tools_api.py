"""The MCP server's consumer-facing tool port.

WHAT THIS IS

The door a consumer knocks on. Whatever plays the agent — Devin in the
org, EA Assist here — calls these HTTP endpoints to discover channels and
ask a human. They are thin wrappers over ``core.py`` (the same functions
the tests exercise), so the logic has one home and this file only adds
the wire.

WHY THIS EXISTS ALONGSIDE THE REAL MCP SERVER

The MCP protocol surface lives in ``mcp_server.py`` (mounted at
``/mcp-server/mcp``) and is what MCP-speaking consumers use. This REST
port exposes the *same* ``core.py`` functions as plain authenticated
HTTP, for consumers and scripts that cannot speak MCP. Both are thin
shells over one implementation, so they cannot drift apart.

The consumer passes its own ``session_id`` on ``ask_human`` — that is
what lets a reply route back to it later, and it is the one thing that
must come from the caller, whether that caller is Devin or EA Assist.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from mcp_layer import core
from mcp_layer.settings import settings

log = logging.getLogger("mcp_layer.tools_api")

router = APIRouter(prefix="/tools", tags=["mcp-tools"])


async def require_token(authorization: str = Header(default="")) -> None:
    """Bearer gate for the tool port. The tools post to real people and
    reveal channel membership, so nothing here is anonymous."""
    if not settings.tools_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="tool port disabled — MCP_TOOLS_TOKEN is not set",
        )
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        presented, settings.tools_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
        )


class AskHumanRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    channel: str = Field(min_length=1, max_length=500)
    recipients: list[str] = Field(default_factory=list, max_length=20)
    question: str = Field(min_length=1, max_length=8000)


@router.get("/channels", dependencies=[Depends(require_token)])
async def list_channels() -> dict:
    """Channels the bot can reach, so a consumer can pick where to ask."""
    return {"channels": await core.list_channels()}


@router.get("/members", dependencies=[Depends(require_token)])
async def list_members(channel: str) -> dict:
    """People in a channel — who a question could be routed to."""
    return await core.list_channel_members(channel)


@router.post("/ask_human", dependencies=[Depends(require_token)])
async def ask_human(req: AskHumanRequest) -> dict:
    """Post a question into a channel on behalf of a session.

    The returned status is either ``asked`` (with the thread id bound to
    the session) or ``channel_not_installed`` (a message the consumer
    relays to a human). The human's reply arrives later on the consumer's
    own callback — this call does not block waiting for it.
    """
    return await core.ask_human(
        req.session_id, req.channel, req.recipients, req.question
    )
