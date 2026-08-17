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
- Stores the `session_id ↔ thread_id` mapping (one table).
- Receives each human reply from the connector and delivers it to the
  session that asked.

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
| `store.py` | The `session ↔ thread` table (Postgres or SQLite). |
| `settings.py` | Reads all configuration from the environment. **Where config comes in.** |
| `.env.example` | **The config file you copy to `.env` and fill in.** |
| `Dockerfile` | Builds the container image. |

## Running

```bash
pip install -r requirements.txt
uvicorn mcp_layer.app:app --host 0.0.0.0 --port 8100    # from server/
```

or as a container:

```bash
docker build -f mcp_layer/Dockerfile -t ea-mcp-layer server/
docker run -p 8100:8100 --env-file mcp_layer/.env ea-mcp-layer
```

Point the connector's `CONNECTOR_INBOUND_URL` at
`https://<this-host>/teams-inbound`. See `.env.example` for all settings.

## Status

Complete and tested (`tests/test_phase19_mcp_layer_smoke.py`, no
Teams/LLM/network — a mock consumer and a faked connector prove the full
loop): the tool logic, the reply round-trip, the REST tool port, and the
**MCP-protocol surface** (Streamable HTTP at `/mcp-server/mcp`,
bearer-gated, tools auto-discovered via `tools/list`).

One piece is deliberately an example rather than a certainty: the SaaS
sessions-API adapter in `consumer.py` implements one vendor's endpoint
shape. Verify it against your platform's actual API (or add your own
adapter — one method) before relying on it in production.
