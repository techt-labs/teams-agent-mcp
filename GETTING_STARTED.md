# Getting Started — Teams Agent MCP Server

This guide takes you from zero to an MCP server your agent platform can
connect to. **No prior knowledge of this codebase is assumed.** It pairs
with the `teams-connector` service — deploy that one first
(its own `GETTING_STARTED.md` walks through it).

What this service is, in one line: *the tools an agent calls to ask a
human in Teams* (`list_channels`, `list_channel_members`, `ask_human`),
plus the one mapping that routes each human reply back to the agent
session that asked.

---

## Step 1 — Prerequisites

- A running
  **[teams-connector](https://github.com/techt-labs/teams-connector)**
  (the companion repo — the only component that talks to Microsoft; it
  has its own `GETTING_STARTED.md`). **If it is not deployed yet, stop
  and do that first.** From it you need two values: its base URL, and
  its `CONNECTOR_API_TOKEN`.
- A database (Step 2).
- Your agent platform's connection details (Step 5).

## Step 2 — Choose a database

One table (see [`DATABASE.md`](DATABASE.md) for the full annotated DDL —
hand it to your DBA if databases are provisioned centrally):

- **PostgreSQL** (production): any Postgres 13+, e.g. **Azure Database
  for PostgreSQL — Flexible Server**. Connection string:
  `postgresql://<user>:<password>@<server>.postgres.database.azure.com:5432/<db>`
- **SQLite** (pilot): `sqlite:///./mcp.db`

The service applies the schema itself at startup (idempotent); running
the DDL manually is optional.

## Step 3 — Configure

```bash
cp .env.example .env      # then edit .env
```

| Variable | Set it to |
|---|---|
| `CONNECTOR_BASE_URL` | the connector's base URL (e.g. `https://<connector-host>`) |
| `CONNECTOR_API_TOKEN` | the connector's token — must match what the connector expects |
| `MCP_DATABASE_URL` | the Step-2 connection string |
| `MCP_TOOLS_TOKEN` | generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` — your agent presents this to call the tools |
| `MCP_INBOUND_TOKEN` | must equal the connector's `CONNECTOR_INBOUND_TOKEN` (the connector presents it when forwarding replies here) |
| consumer settings | ONE of the Step-5 shapes below |

And on the **connector's** side, set its `CONNECTOR_INBOUND_URL` to
`https://<this-host>/teams-inbound` so replies flow here.

## Step 4 — Run

**Docker (recommended — includes Postgres):**

```bash
docker compose up --build
```

**Or directly:**

```bash
pip install -r requirements.txt
uvicorn mcp_layer.app:app --host 0.0.0.0 --port 8100
```

On Azure: App Service (Web App for Containers) or Container Apps. This
service does **not** need to face the public internet — only the
connector and your agent platform need to reach it.

## Step 5 — Attach your agent platform

Two halves: the agent **calls the tools**, and the agent **receives the
answers**.

### 5a. Calling the tools (all platforms, identical)

Register this server with your platform as a **custom MCP connection**:

- URL: `https://<this-host>/mcp-server/mcp` (MCP Streamable HTTP)
- Auth header: `Authorization: Bearer <MCP_TOOLS_TOKEN>`

The platform auto-discovers the tools via the MCP protocol. (A plain
REST mirror of the same tools exists at `/tools/*` for anything that
cannot speak MCP.)

The one integration detail to confirm with your platform: **how a
session supplies its own id** to the `ask_human(session_id, …)` call —
a tool argument filled from a prompt/playbook instruction, or injected
by the platform. An in-house tool simply passes its own id.

### 5b. Receiving the answers (pick ONE, by config)

| Your agent is… | Set | What happens on a reply |
|---|---|---|
| an **in-house tool** | `AGENT_CALLBACK_URL` (+ optional `AGENT_CALLBACK_TOKEN`) | this server POSTs `{session_id, text}` to your endpoint; your tool resumes that session |
| a **SaaS platform with a sessions API** | `DEVIN_BASE_URL`, `DEVIN_ORG`, `DEVIN_API_TOKEN` (the built-in example adapter; see `mcp_layer/consumer.py` to add another vendor — one method) | this server posts the answer into the platform session, waking it if asleep |
| nothing yet (testing) | leave both unset | the built-in mock records deliveries in the log |

## Step 6 — Verify the full loop

```bash
TOKEN=<your MCP_TOOLS_TOKEN>
BASE=https://<this-host>

# tools reachable + connector wired?
curl -H "Authorization: Bearer $TOKEN" $BASE/tools/channels
#  → the channel(s) the bot is installed in

# who could be asked?
curl -H "Authorization: Bearer $TOKEN" "$BASE/tools/members?channel=<name>"

# the outbound half — a real thread appears in Teams:
curl -X POST $BASE/tools/ask_human \
  -H "Authorization: Bearer $TOKEN" -H "content-type: application/json" \
  -d '{"session_id":"smoke-1","channel":"<name>","recipients":["<a member>"],
       "question":"Deployment smoke test — please reply in this thread."}'

# the inbound half — reply in that Teams thread, then check this
# service's logs for "handle_human_reply" and your consumer for the
# delivered {session_id, text}.
```

Both halves good → the bidirectional loop is live.

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `/tools/channels` → `502`/error | `CONNECTOR_BASE_URL`/`CONNECTOR_API_TOKEN` wrong, or connector down |
| `ask_human` → `channel_not_installed` | channel name mismatch → use the exact name from `/tools/channels`; or the bot isn't installed there |
| Reply never arrives here | connector's `CONNECTOR_INBOUND_URL` not pointing at this host, or `MCP_INBOUND_TOKEN` ≠ `CONNECTOR_INBOUND_TOKEN` |
| Reply arrives but goes nowhere | consumer not configured (mock is recording it — check the logs) |
| MCP connection rejected | missing/incorrect `Authorization: Bearer <MCP_TOOLS_TOKEN>` — the endpoint fails closed |
