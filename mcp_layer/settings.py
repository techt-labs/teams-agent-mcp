"""MCP layer configuration, read straight from the environment.

Like the connector, this reads plain ``os.environ`` with a small
mutable dataclass — no config framework — so tests set attributes
directly and a deployment sets environment variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


@dataclass
class McpSettings:
    """Everything the MCP layer needs, and nothing else."""

    # --- The connector (Teams-facing service) --------------------
    # Base URL of the connector's HTTP API, and the bearer token it
    # requires. This layer is a client of the connector.
    connector_base_url: str = ""
    connector_api_token: str = ""

    # --- The consumer (agent platform) ---------------------------
    # THE SWAP POINT. A human's answer is delivered to whichever of these
    # is configured, chosen at startup:
    #   * a SaaS platform → set devin_base_url/org (the example
    #     sessions-API adapter; add your own for another vendor)
    #   * any in-house tool → set agent_callback_url (HttpAgent, a plain
    #     POST of {session_id, text})
    #   * neither → the built-in mock (records, never sends)
    # The rest of the pipeline is identical regardless of which is used.
    devin_base_url: str = ""
    devin_api_token: str = ""
    devin_org: str = ""

    agent_callback_url: str = ""
    agent_callback_token: str = ""

    # --- The tool port -------------------------------------------
    # Shared secret a consumer presents to call /tools/*. Empty disables
    # the port (503), never leaves it open.
    tools_token: str = ""

    # --- Storage -------------------------------------------------
    # Holds the session <-> thread mapping. Postgres in production,
    # SQLite for a pilot or local test.
    database_url: str = ""

    # --- Inbound auth --------------------------------------------
    # Shared secret the connector presents when forwarding a reply to
    # this layer's /teams-inbound webhook. Empty disables the check
    # (acceptable only in a trusted network / local test).
    inbound_token: str = ""

    # --- Default channel -----------------------------------------
    # Optional. When set, ``ask_human`` may be called without a channel
    # and this one is used. The agent can always override via
    # ``list_channels`` + an explicit channel argument.
    default_channel_id: str = ""

    def load_from_env(self) -> "McpSettings":
        self.connector_base_url = _env("CONNECTOR_BASE_URL").rstrip("/")
        self.connector_api_token = _env("CONNECTOR_API_TOKEN")

        self.devin_base_url = _env("DEVIN_BASE_URL").rstrip("/")
        self.devin_api_token = _env("DEVIN_API_TOKEN")
        self.devin_org = _env("DEVIN_ORG")

        self.agent_callback_url = _env("AGENT_CALLBACK_URL").rstrip("/")
        self.agent_callback_token = _env("AGENT_CALLBACK_TOKEN")
        self.tools_token = _env("MCP_TOOLS_TOKEN")

        self.database_url = _env("MCP_DATABASE_URL", "DATABASE_URL")
        self.inbound_token = _env("MCP_INBOUND_TOKEN", "CONNECTOR_INBOUND_TOKEN")
        self.default_channel_id = _env("FACILITATION_CHANNEL_CONVERSATION_ID")
        return self

    @property
    def storage_is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def storage_enabled(self) -> bool:
        return bool(self.database_url)


settings = McpSettings().load_from_env()
