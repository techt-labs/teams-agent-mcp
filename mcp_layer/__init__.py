"""The MCP layer — the agent-facing half of the bridge.

WHERE THIS SITS

    Teams  <->  connector  <->  [ MCP layer ]  <->  your agent
                                 this package

The connector knows how to reach Teams and nothing about sessions. This
layer holds the one fact the connector must never hold: which agent
*session* a given Teams thread belongs to. It exposes tools an agent
calls (``list_channels``, ``ask_human``), and it receives the human's
reply back from the connector and delivers it to the right session.

THE ONE MAPPING

    session_id  <->  thread_id

is this package's whole reason to exist. ``ask_human`` writes it when a
question goes out; the inbound webhook reads it when an answer comes
back. Everything else is plumbing around that single correlation.

WHY IT IS SEPARATE FROM THE CONNECTOR

Swapping one agent platform for another must change only this layer.
The connector, the Teams app, and the channel install all stay put. So
this package may call the connector's HTTP API, but the connector holds
no reference back — the dependency points one way only.
"""
