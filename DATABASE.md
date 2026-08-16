# Database — Teams Agent MCP Server

Everything this service persists, for whoever owns databases in your
organization. **One table, one index. No extensions.** Any
PostgreSQL 13+ works — including **Azure Database for PostgreSQL
(Flexible Server)** — and SQLite is supported for pilots.

## Do I have to run this DDL?

No. The service applies it at **startup, idempotently**
(`CREATE TABLE IF NOT EXISTS`), against whatever `MCP_DATABASE_URL`
points at. This document exists so a DBA can review, pre-provision, or
manage the schema with their own migration tooling — the startup apply
is a no-op on an already-provisioned database.

## The DDL

The authoritative copy is [`mcp_layer/schema.sql`](mcp_layer/schema.sql) —
the service loads and executes that exact file. It is annotated
column-by-column; the shape:

```sql
CREATE TABLE IF NOT EXISTS mcp_sessions (
    thread_id   TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    channel_id  TEXT,
    recipient   TEXT,
    question    TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS mcp_sessions_session_idx
    ON mcp_sessions (session_id);
```

## What this table is

The **single correlation the whole bridge depends on**: which agent
session a Teams thread belongs to.

- A row is **written** when `ask_human` posts a question (the new
  thread's id, bound to the calling session's id).
- It is **read** when a human's reply arrives — Teams stamps the same
  thread id on every reply inside a thread, so routing the answer back
  is one point query on the primary key.
- `status` flips `open → answered` on first delivery; informational
  only (follow-up replies still route).
- `channel_id` / `recipient` / `question` are operator context, not
  used for routing.

## Sizing and access patterns

- **One row per question asked.** Growth is linear in questions, not in
  messages. Thousands to hundreds of thousands of rows are trivial.
- Reads: point lookup by `thread_id` (every inbound reply); occasional
  `session_id` scans for operator queries — covered by the one index.
- Writes: one upsert per `ask_human`; one status `UPDATE` per delivery.
- No further indexes needed; both hot paths are covered.

## Retention

Rows are the audit trail of what was asked and to whom. Nothing in this
store contains the human's *answer* text (answers pass through to the
consumer and are not persisted here). Prune old `answered` rows on your
own policy if desired; the service never depends on historical rows for
new asks.

## SQLite note

Set `MCP_DATABASE_URL=sqlite:///./mcp.db` and the service substitutes
`TEXT` for `TIMESTAMPTZ` at apply time; nothing else changes. Use
PostgreSQL when more than one container instance runs.
