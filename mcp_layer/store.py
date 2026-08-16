"""The session <-> thread mapping — the MCP layer's only state.

One table. When ``ask_human`` starts a thread, it binds the thread id to
the calling session. When a reply arrives on that thread, the inbound
webhook looks the session up and delivers the answer to it.

Supports PostgreSQL (production) and SQLite (pilot / local test) behind
the same small interface, chosen by the ``database_url`` scheme. SQLite
work runs in a thread so it never blocks the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mcp_layer.settings import settings

log = logging.getLogger("mcp_layer.store")

# The DDL lives in schema.sql (annotated, valid PostgreSQL) so a
# database team can review or pre-provision it without reading Python.
# Loaded here so the code and the handed-to-a-DBA copy cannot drift.
_SCHEMA = (Path(__file__).with_name("schema.sql")).read_text()


@dataclass(frozen=True)
class Binding:
    """One session/thread link, as read back for routing a reply."""

    session_id: str
    thread_id: str
    channel_id: Optional[str]
    recipient: Optional[str]
    status: str


# --- engine handles ----------------------------------------------------
_sqlite_path: Optional[str] = None
_pg_pool = None  # psycopg_pool.AsyncConnectionPool when Postgres is used


def is_enabled() -> bool:
    return _sqlite_path is not None or _pg_pool is not None


def _sqlite_file() -> str:
    """Path from a ``sqlite:///…`` URL.

    Strips exactly three slashes, following the SQLAlchemy convention:
    ``sqlite:///foo.db`` is relative (``foo.db``), ``sqlite:////abs.db``
    is absolute (``/abs.db``), ``sqlite:///:memory:`` is in-memory. The
    remainder is used as-is, so both relative and absolute paths work.
    """
    prefix = "sqlite:///"
    return settings.database_url[len(prefix):] or ":memory:"


async def startup() -> None:
    """Open storage and apply the (idempotent) schema."""
    global _sqlite_path, _pg_pool
    if is_enabled() or not settings.storage_enabled:
        return

    if settings.storage_is_sqlite:
        _sqlite_path = _sqlite_file()
        if _sqlite_path and _sqlite_path != ":memory:":
            Path(_sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_sqlite_init)
        log.info("mcp store ready (engine=sqlite)")
    else:
        from psycopg_pool import AsyncConnectionPool

        _pg_pool = AsyncConnectionPool(settings.database_url, open=False)
        await _pg_pool.open()
        async with _pg_pool.connection() as conn:
            # Postgres accepts the DDL as authored (TIMESTAMPTZ is native).
            # Comment lines are stripped before splitting on ';' — the
            # annotated schema.sql contains semicolons inside comments
            # (an example thread id), which would otherwise cut a
            # statement in half.
            ddl = "\n".join(
                line for line in _SCHEMA.splitlines()
                if not line.strip().startswith("--")
            )
            for stmt in filter(str.strip, ddl.split(";")):
                await conn.execute(stmt)
        log.info("mcp store ready (engine=postgres)")


def _sqlite_init() -> None:
    with sqlite3.connect(_sqlite_path) as conn:
        # SQLite has no TIMESTAMPTZ; it stores the value as text, which
        # round-trips fine since these are only ever displayed.
        conn.executescript(_SCHEMA.replace("TIMESTAMPTZ", "TEXT"))


async def shutdown() -> None:
    global _sqlite_path, _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None
    _sqlite_path = None


async def bind(
    *,
    session_id: str,
    thread_id: str,
    channel_id: Optional[str],
    recipient: Optional[str],
    question: Optional[str],
) -> None:
    """Record that ``thread_id`` belongs to ``session_id``.

    Upsert on the thread id: a retried ``ask_human`` for the same thread
    must not create a second row that a later lookup could pick between.
    """
    if not is_enabled():
        raise RuntimeError("mcp store is not enabled — set MCP_DATABASE_URL")

    if _sqlite_path is not None:
        await asyncio.to_thread(
            _sqlite_bind, session_id, thread_id, channel_id, recipient, question
        )
        return

    async with _pg_pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO mcp_sessions
                (thread_id, session_id, channel_id, recipient, question)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (thread_id) DO UPDATE SET
                session_id = EXCLUDED.session_id,
                channel_id = EXCLUDED.channel_id,
                recipient  = EXCLUDED.recipient,
                question   = EXCLUDED.question,
                status     = 'open',
                updated_at = CURRENT_TIMESTAMP
            """,
            (thread_id, session_id, channel_id, recipient, question),
        )


def _sqlite_bind(session_id, thread_id, channel_id, recipient, question) -> None:
    with sqlite3.connect(_sqlite_path) as conn:
        conn.execute(
            """
            INSERT INTO mcp_sessions
                (thread_id, session_id, channel_id, recipient, question)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (thread_id) DO UPDATE SET
                session_id = excluded.session_id,
                channel_id = excluded.channel_id,
                recipient  = excluded.recipient,
                question   = excluded.question,
                status     = 'open',
                updated_at = CURRENT_TIMESTAMP
            """,
            (thread_id, session_id, channel_id, recipient, question),
        )


async def binding_for_thread(thread_id: str) -> Optional[Binding]:
    """The session a thread belongs to, or None if this thread is
    unknown — which is normal: it means the reply is in a thread this
    layer did not open (someone else's, or a stray channel post)."""
    if not is_enabled():
        return None

    if _sqlite_path is not None:
        row = await asyncio.to_thread(_sqlite_get, thread_id)
    else:
        async with _pg_pool.connection() as conn:
            cur = await conn.execute(
                "SELECT session_id, thread_id, channel_id, recipient, status "
                "FROM mcp_sessions WHERE thread_id = %s",
                (thread_id,),
            )
            row = await cur.fetchone()
    if row is None:
        return None
    return Binding(row[0], row[1], row[2], row[3], row[4])


def _sqlite_get(thread_id: str):
    with sqlite3.connect(_sqlite_path) as conn:
        cur = conn.execute(
            "SELECT session_id, thread_id, channel_id, recipient, status "
            "FROM mcp_sessions WHERE thread_id = ?",
            (thread_id,),
        )
        return cur.fetchone()


async def mark_answered(thread_id: str) -> None:
    """Best-effort: note that a reply has been delivered for this thread.

    Not load-bearing for routing — a thread stays usable for follow-ups —
    but it records that the loop closed at least once, which operators
    ask for.
    """
    if not is_enabled():
        return
    if _sqlite_path is not None:
        await asyncio.to_thread(_sqlite_mark, thread_id)
    else:
        async with _pg_pool.connection() as conn:
            await conn.execute(
                "UPDATE mcp_sessions SET status='answered', "
                "updated_at=CURRENT_TIMESTAMP WHERE thread_id = %s",
                (thread_id,),
            )


def _sqlite_mark(thread_id: str) -> None:
    with sqlite3.connect(_sqlite_path) as conn:
        conn.execute(
            "UPDATE mcp_sessions SET status='answered', "
            "updated_at=CURRENT_TIMESTAMP WHERE thread_id = ?",
            (thread_id,),
        )
