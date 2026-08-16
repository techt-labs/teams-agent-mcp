"""The tool logic — what an agent actually invokes, and what a reply does.

Transport-independent on purpose: these are plain async functions, so
they are testable directly and the MCP-protocol binding on top of them
(the layer an agent platform speaks to) stays a thin wrapper. Three verbs the agent
uses — discover channels, discover people, ask — and one the inbound
webhook uses — deliver a reply back to the asking session.
"""
from __future__ import annotations

import logging
from typing import Optional

from mcp_layer import connector_client, store
from mcp_layer.consumer import get_consumer

log = logging.getLogger("mcp_layer.core")


async def list_channels() -> list[dict]:
    """Channels the bot can reach: ``[{id, name}]``.

    A discovery/verification surface. The agent's *routing* knowledge —
    which channel is for which program — comes from its context file;
    this only confirms what is actually reachable.
    """
    channels = await connector_client.list_channels()
    return [
        {"id": c["conversation_id"], "name": c.get("name")}
        for c in channels
    ]


async def list_channel_members(channel: str) -> dict:
    """People in a channel: ``{status, members:[{name, email}]}``.

    Names only to the agent — the Entra object id is resolved internally
    when a mention is built, and is not something the agent needs to
    handle. Returns a ``channel_not_installed`` status (rather than an
    error) when the channel is unknown, so the agent can relay the fix.
    """
    resolved = await _resolve_channel(channel)
    if resolved is None:
        return _not_installed(channel)
    members = await connector_client.list_members(resolved["id"])
    return {
        "status": "ok",
        "channel": resolved["name"],
        "members": [
            {"name": m.get("name"), "email": m.get("email")} for m in members
        ],
    }


async def ask_human(
    session_id: str,
    channel: str,
    recipients: list[str],
    question: str,
) -> dict:
    """Post ``question`` into ``channel``, @-mentioning ``recipients``.

    ``session_id`` is the calling agent session — passed explicitly so
    this works whether the platform injects it or the playbook supplies
    it. It is bound to the new thread here; the human's reply routes back
    to it later. ``channel`` and ``recipients`` are names (as they appear
    in the agent's context file); this resolves them to ids internally.

    Returns one of:
      * ``{status: "asked", thread_id, mentioned, unresolved}``
      * ``{status: "channel_not_installed", message}`` — agent relays it
    """
    resolved = await _resolve_channel(channel)
    if resolved is None:
        return _not_installed(channel)

    mentions, unresolved = await _resolve_recipients(resolved["id"], recipients)

    # The mentioned names must appear in the text for Teams to render and
    # notify them: the connector wraps a name it finds in the body, and
    # skips one it does not. Leading with the names is also the natural
    # way to address a question to specific people.
    prefix = ", ".join(m["name"] for m in mentions)
    text = f"{prefix}: {question}" if prefix else question

    thread_id = await connector_client.create_thread(
        resolved["id"], text, mentions or None
    )

    await store.bind(
        session_id=session_id,
        thread_id=thread_id,
        channel_id=resolved["id"],
        recipient=", ".join(recipients) if recipients else None,
        question=question,
    )

    log.info(
        f"ask_human: session={session_id} thread={thread_id[:24]}… "
        f"mentioned={len(mentions)} unresolved={len(unresolved)}"
    )
    return {
        "status": "asked",
        "thread_id": thread_id,
        "mentioned": [m["name"] for m in mentions],
        "unresolved": unresolved,
    }


async def handle_human_reply(
    thread_id: str, text: str, speaker: Optional[str]
) -> bool:
    """Route one human reply back to the session that asked. True if ours.

    Called by the inbound webhook for *every* forwarded message. Returns
    False for a thread this layer did not open — a reply in someone
    else's thread, or stray channel chatter — which is exactly how
    unrelated conversation is filtered out and never reaches an agent.
    """
    binding = await store.binding_for_thread(thread_id)
    if binding is None:
        return False

    who = speaker or "a stakeholder"
    await get_consumer().deliver_message(
        binding.session_id, f"Reply from {who}: {text}"
    )
    await store.mark_answered(thread_id)
    log.info(
        f"handle_human_reply: thread={thread_id[:24]}… → session="
        f"{binding.session_id}"
    )
    return True


# --- internals ---------------------------------------------------------

async def _resolve_channel(channel: str) -> Optional[dict]:
    """Match a name or id against installed channels. None if unreachable.

    Matching by name is case-insensitive because the agent quotes it from
    a context file, not from the API. An id is accepted too, so a caller
    that already holds one is not forced through a name lookup.
    """
    wanted = channel.strip().lower()
    for c in await connector_client.list_channels():
        if (c.get("conversation_id") or "").lower() == wanted:
            return {"id": c["conversation_id"], "name": c.get("name")}
        if (c.get("name") or "").strip().lower() == wanted:
            return {"id": c["conversation_id"], "name": c.get("name")}
    return None


async def _resolve_recipients(
    channel_id: str, recipients: list[str]
) -> tuple[list[dict], list[str]]:
    """Turn recipient names/emails into mention dicts via the roster.

    Returns ``(mentions, unresolved)``. An unresolved name is reported,
    not guessed at: the question still goes out, but the caller learns
    who was not pinged so it can fall back (ask by a different name, or
    tell a human).
    """
    if not recipients:
        return [], []

    members = await connector_client.list_members(channel_id)
    by_name = {(m.get("name") or "").strip().lower(): m for m in members}
    by_email = {(m.get("email") or "").strip().lower(): m for m in members}

    mentions: list[dict] = []
    unresolved: list[str] = []
    for r in recipients:
        key = r.strip().lower()
        member = by_name.get(key) or by_email.get(key)
        if member and member.get("aad_object_id"):
            mentions.append(
                {
                    "aad_object_id": member["aad_object_id"],
                    "name": member.get("name") or r,
                    "email": member.get("email"),
                }
            )
        else:
            unresolved.append(r)
    return mentions, unresolved


def _not_installed(channel: str) -> dict:
    return {
        "status": "channel_not_installed",
        "message": (
            f"The bot is not in a channel matching \"{channel}\". Ask a team "
            f"owner to install the app into that channel, then try again. "
            f"Use list_channels to see what is currently reachable."
        ),
    }
