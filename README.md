# MCP Layer

> **This repo is one of two, and it does not work alone.** The full
> bridge that lets an agent ask a human in Teams and get the answer back:
>
> ```
> ┌───────────────────┐   ┌─────────────────┐   ┌───────────────┐   ┌──────────────┐
> │ Microsoft 365      │◄─►│  connector      │◄─►│  MCP server   │◄─►│  your agent  │
> │ Teams + Azure Bot  │   │ teams-connector │   │  ★ THIS REPO  │   │ SaaS/in-house│
> └───────────────────┘   └─────────────────┘   └───────────────┘   └──────────────┘
> ```
>
> **Prerequisite:** a running
> **[teams-connector](https://github.com/techt-labs/teams-connector)** —
> that companion repo is the only thing that talks to Microsoft; this
> service is its client. Deploy it **first**, then this one, then point
> your agent here. Order and wiring: [`GETTING_STARTED.md`](GETTING_STARTED.md).

The agent-facing half of the Teams bridge. It holds one fact the
connector deliberately does not: **which agent session a Teams thread
belongs to.**

```
   Teams  <->  connector  <->  [ MCP layer ]  <->  your agent
                                this service
```

## What it does

- Exposes tools an agent calls: `list_channels`, `list_channel_members`,
  `ask_human`.
- Stores the `session_id ↔ thread_id` mapping — one table, `mcp_sessions`;
  the full annotated DDL, column meanings and sizing notes are in
  [`DATABASE.md`](DATABASE.md), and the executable copy the service
  applies at startup is [`mcp_layer/schema.sql`](mcp_layer/schema.sql).
- Receives each human reply from the connector and delivers it to the
  session that asked.

**Documentation map:** deploy step-by-step →
[`GETTING_STARTED.md`](GETTING_STARTED.md) · the database →
[`DATABASE.md`](DATABASE.md) · architecture & APIs → this file.

## Every API, at a glance

**This service EXPOSES 3 surfaces** (5 HTTP endpoints total):

| # | Endpoint | Who calls it | What it does |
|---|---|---|---|
| 1 | `/mcp-server/mcp` | **your agent** (MCP protocol, Streamable HTTP) | connect once, auto-discover and call the 3 tools |
| 2 | `GET /tools/channels` · `GET /tools/members` · `POST /tools/ask_human` | **your agent** (plain REST — same 3 tools, for anything that cannot speak MCP) | list channels · list people · post a question |
| 3 | `POST /teams-inbound` | **the connector** | every human reply arrives here and is routed to its session |

Surfaces 1–2 require `Authorization: Bearer <MCP_TOOLS_TOKEN>`;
surface 3 requires the connector's `CONNECTOR_INBOUND_TOKEN`.

**This service CALLS 2 things:**

| Direction | Where | Which endpoints | When |
|---|---|---|---|
| → the [teams-connector](https://github.com/techt-labs/teams-connector) | `CONNECTOR_BASE_URL` | `GET /api/connector/channels`, `GET /members`, `POST /threads`, `POST /say` | executing the tools |
| → your consumer | `AGENT_CALLBACK_URL` (one `POST` of `{session_id, text}`) **or** the SaaS sessions API | — | delivering each human answer to the session that asked |

That is the complete surface — nothing else listens, nothing else is
called.

## What it deliberately does not do

- **Talk to Teams.** It never imports the Teams SDK. It calls the
  connector's HTTP API instead — that is why it is a separate service and
  why swapping one agent platform for another touches only this layer.
- **See unrelated conversations.** The connector forwards every channel
  message; this layer routes only the ones whose thread matches a known
  session and drops the rest. An agent never sees channel traffic that
  was not a reply to its own question.

## The tools

| Tool | Purpose |
|---|---|
| `list_channels()` | channels the bot can reach (verify, not route) |
| `list_channel_members(channel)` | who is in a channel — resolves names to mentions |
| `ask_human(session_id, channel, recipients, question)` | post a question, bind the thread to the session |

Routing knowledge — which channel is for which program — lives in the
**agent's context file**, not here. These tools execute and verify; the
agent decides where to ask. If a channel is not installed, `ask_human`
returns a *"please install the bot"* message the agent relays to a human.

`session_id` is passed explicitly, so the layer works whether the
platform injects it or a playbook supplies it.

## Reply routing

The connector POSTs every inbound message to `/teams-inbound` with its
conversation id. This layer looks the thread up: a match is delivered to
the session; anything else returns `{"routed": false}` and is dropped.

## Files in this package

Deployment is configuration only; you do not edit these. A map for
readers and reviewers:

| File | What it does |
|---|---|
| `app.py` | **Entry point.** Starts the service, mounts the inbound webhook, opens the store. |
| `inbound.py` | The webhook the connector calls (`/teams-inbound`) — receives forwarded replies. |
| `core.py` | The tool logic: `list_channels`, `list_channel_members`, `ask_human`, and reply routing. |
| `connector_client.py` | HTTP client for the connector's API — this layer's only way to Teams. |
| `consumer.py` | Delivers an answer to the attached agent (`HttpAgent` callback, an example SaaS sessions-API adapter, or a recording mock). |
| `store.py` | The `session ↔ thread` table (Postgres or SQLite); DDL in `schema.sql`, explained in `DATABASE.md`. |
| `settings.py` | Reads all configuration from the environment. **Where config comes in.** |
| `.env.example` | **The config file you copy to `.env` and fill in.** |
| `Dockerfile` | Builds the container image. |

## Running

Deployment step-by-step (database options, config table, attaching your
agent platform, verification) lives in
[`GETTING_STARTED.md`](GETTING_STARTED.md). The short form:

```bash
cp .env.example .env      # fill in — see GETTING_STARTED.md
docker compose up --build # service + PostgreSQL, one command
```

or without Docker (Python 3.11+):

```bash
pip install -r requirements.txt
uvicorn mcp_layer.app:app --host 0.0.0.0 --port 8100
```

Point the connector's `CONNECTOR_INBOUND_URL` at
`https://<this-host>/teams-inbound`. See `.env.example` for all settings.

## Status

Complete and tested in the source monorepo's smoke suite (a mock
consumer and a faked connector prove the full ask → reply → session
loop; no Teams/LLM/network needed): the tool logic, the reply
round-trip, the REST tool port, and the **MCP-protocol surface**
(Streamable HTTP at `/mcp-server/mcp`, bearer-gated, tools
auto-discovered via `tools/list`). The bidirectional flow has also been
verified live against a real tenant. Per-repo CI is on the roadmap.

One piece is deliberately an example rather than a certainty: the SaaS
sessions-API adapter in `consumer.py` implements one vendor's endpoint
shape. Verify it against your platform's actual API (or add your own
adapter — one method) before relying on it in production.
