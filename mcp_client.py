"""
mcp_client.py — thin async wrapper around nexus-mcp-server.

Spawns the Node MCP server as a stdio subprocess (with the READ-ONLY
nexus_chat_ro credentials), lists its tools, filters them through the
ALLOWED_TOOLS allowlist, and exposes:

    tools_for_anthropic()  -> tool schemas in Anthropic API format
    call(name, args)       -> tool result text

This is the ONLY path between Claude and the Nexus database, per the
App Vision rule.
"""

import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config


class NexusMcp:
    """Use as:  async with NexusMcp() as nexus: ..."""

    def __init__(self):
        self._session = None
        self._stdio_ctx = None
        self._session_ctx = None
        self._tools = []  # allowlisted tools, MCP schema objects

    async def __aenter__(self):
        env = dict(os.environ)
        env.update(
            {
                "NEXUS_SERVER": config.NEXUS_SERVER,
                "NEXUS_DATABASE": config.NEXUS_DATABASE,
                # Read-only login — engine-level write denial.
                "NEXUS_USERNAME": config.RO_USERNAME,
                "NEXUS_PASSWORD": config.RO_PASSWORD,
            }
        )
        params = StdioServerParameters(
            command=config.NODE_COMMAND,
            args=[config.NEXUS_MCP_PATH],
            env=env,
        )
        self._stdio_ctx = stdio_client(params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()

        listing = await self._session.list_tools()
        self._tools = [
            t for t in listing.tools if t.name in config.ALLOWED_TOOLS
        ]
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Best-effort teardown: a failure while closing must not mask
        # the real error (anyio cancel-scope noise on abnormal exit).
        try:
            if self._session_ctx is not None:
                await self._session_ctx.__aexit__(exc_type, exc, tb)
        except Exception:
            pass
        try:
            if self._stdio_ctx is not None:
                await self._stdio_ctx.__aexit__(exc_type, exc, tb)
        except Exception:
            pass

    @staticmethod
    def _schema_of(tool):
        """MCP SDK versions differ: older exposes .inputSchema (camelCase),
        newer exposes .input_schema (snake_case). Handle both."""
        schema = getattr(tool, "inputSchema", None)
        if schema is None:
            schema = getattr(tool, "input_schema", None)
        return schema or {"type": "object", "properties": {}}

    def tools_for_anthropic(self):
        """MCP tool schemas -> Anthropic Messages API `tools` list."""
        out = []
        for t in self._tools:
            out.append(
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": self._schema_of(t),
                }
            )
        return out

    async def call(self, name, args):
        """Call a tool; returns its text content (str)."""
        if name not in {t.name for t in self._tools}:
            return json.dumps(
                {"error": f"Tool '{name}' is not available in Titan AI."}
            )
        result = await self._session.call_tool(name, args or {})
        parts = []
        for block in result.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "\n".join(parts) if parts else "(empty result)"
