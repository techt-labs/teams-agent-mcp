-- The MCP server's entire schema: one table, one index.
--
-- Authored as valid PostgreSQL so it can be handed to a DBA unchanged.
-- The service also applies this itself at startup (idempotent
-- CREATE IF NOT EXISTS), so running it manually is optional — it exists
-- so a database team can review, pre-provision, or manage the schema
-- with their own tooling. On SQLite the service substitutes TEXT for
-- TIMESTAMPTZ; no other change.
--
-- WHAT THIS TABLE IS
-- The single correlation the bridge depends on: which agent session a
-- Teams thread belongs to. A row is written when ask_human posts a
-- question; it is read when a human's reply arrives carrying the same
-- thread id.

CREATE TABLE IF NOT EXISTS mcp_sessions (
    -- The Teams thread's conversation id
    -- ("19:<channel>@thread.tacv2;messageid=<n>"). Primary key: one
    -- thread belongs to exactly one session, and the reply lookup is
    -- a point query on this value.
    thread_id   TEXT PRIMARY KEY,

    -- The consuming agent's own session identifier — opaque to the
    -- bridge; whatever the platform passed to ask_human.
    session_id  TEXT NOT NULL,

    -- Context for operators; not used for routing.
    channel_id  TEXT,
    recipient   TEXT,
    question    TEXT,

    -- 'open' until at least one reply has been delivered, then
    -- 'answered'. Informational — a thread stays routable for
    -- follow-up replies regardless.
    status      TEXT NOT NULL DEFAULT 'open',

    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Operator queries ("what has session X asked?") scan by session.
CREATE INDEX IF NOT EXISTS mcp_sessions_session_idx
    ON mcp_sessions (session_id);
