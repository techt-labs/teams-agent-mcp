"""The real MCP server — tools exposed over the MCP protocol.

This replaces the hand-wired REST tool port with an actual MCP server. A
client connects, calls ``tools/list``, and discovers every tool here
automatically — add one below and any connected client (the EA Assist
agent, or Devin) picks it up with no code change on its side. That
auto-discovery is the whole point of MCP, and the reason this exists.

Each tool is a thin wrapper over ``core.py`` — the same logic the tests
exercise — so there is one home for behaviour and this file only
declares the protocol surface.
"""
from __future__ import annotations

from mcp.server import MCPServer

from mcp_layer import core

mcp_server = MCPServer(
    name="ea-teams-bridge",
    description="Ask a human in Microsoft Teams and read channel context.",
)


@mcp_server.tool(
    name="list_channels",
    description="List the Microsoft Teams channels the bot is connected to "
    "and can post questions into. Returns each channel's name and id.",
)
async def list_channels() -> dict:
    return {"channels": await core.list_channels()}


@mcp_server.tool(
    name="list_channel_members",
    description="List the people in a connected Teams channel (name + email). "
    "Resolve the channel by display name or id.",
)
async def list_channel_members(channel: str) -> dict:
    return await core.list_channel_members(channel)


@mcp_server.tool(
    name="ask_human",
    description="Post a question into a Teams channel and @-mention the "
    "recipients — a real thread the person replies to. Pass the calling "
    "session's id so the reply can be routed back to it.",
)
async def ask_human(
    session_id: str, channel: str, recipients: list[str], question: str
) -> dict:
    return await core.ask_human(session_id, channel, recipients, question)


# ASGI app for the Streamable HTTP transport. app.py mounts it (behind
# a bearer gate) at /mcp-server, so the full client URL is
# /mcp-server/mcp.
mcp_app = mcp_server.streamable_http_app(streamable_http_path="/mcp")
