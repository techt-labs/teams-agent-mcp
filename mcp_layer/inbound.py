"""Inbound webhook — where the connector delivers a human's reply.

The connector forwards *every* Teams message it sees to this endpoint,
with the conversation id attached. This layer decides which ones matter:
:func:`handle_human_reply` returns quietly for a thread it did not open,
so unrelated channel traffic is dropped here and never reaches an agent.

Point the connector's ``CONNECTOR_INBOUND_URL`` at ``/teams-inbound``.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from mcp_layer import core
from mcp_layer.settings import settings

log = logging.getLogger("mcp_layer.inbound")

router = APIRouter(tags=["mcp-inbound"])


class InboundReply(BaseModel):
    """One forwarded Teams message. Matches the connector's payload."""

    conversation_id: str = Field(min_length=1, max_length=500)
    text: str = Field(default="", max_length=16_000)
    speaker: str | None = Field(default=None, max_length=200)
    speaker_email: str | None = Field(default=None, max_length=320)
    source: str | None = Field(default=None, max_length=50)


def _authorized(authorization: str) -> bool:
    """Constant-time bearer check. An unset token disables the check —
    acceptable only inside a trusted network, and logged as a warning at
    startup so it is never a silent state."""
    if not settings.inbound_token:
        return True
    scheme, _, presented = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(
        presented, settings.inbound_token
    )


@router.post("/teams-inbound")
async def teams_inbound(
    reply: InboundReply, authorization: str = Header(default="")
) -> dict:
    """Receive one forwarded reply and route it to the asking session.

    Always 200 on an authorized, well-formed request — whether or not the
    message matched a session. "Not ours" is a normal outcome (someone
    else's thread), not an error, and answering 200 keeps the connector
    from retrying a message that was correctly ignored.
    """
    if not _authorized(authorization):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
        )

    routed = await core.handle_human_reply(
        thread_id=reply.conversation_id,
        text=reply.text,
        speaker=reply.speaker or reply.speaker_email,
    )
    return {"routed": routed}
