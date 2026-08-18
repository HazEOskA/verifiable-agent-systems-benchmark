"""Standalone MCP client driver, executed under OSA's OWN venv interpreter.

This file is deliberately self-contained (stdlib + the ``mcp`` package only)
and imports nothing from the VASB benchmark. It is invoked as a subprocess
by ``adapters/osa/mcp_client.py`` using OSA's own venv python - the one
place the ``mcp`` client SDK needs to be importable - so that VASB's own
Python environment never needs the ``mcp`` package, or any other OSA
dependency, installed into it.

Protocol: a single JSON object on stdin, e.g.
    {"command": "list_tools"}
    {"command": "call_tool", "tool_name": "osa_run_mission", "arguments": {...}}
One line on stdout, prefixed with ``VASB_MCP_RESULT:``, containing a JSON
object: ``{"ok": true, "result": ...}`` or ``{"ok": false, "error": "..."}``.
Everything else on stdout/stderr (Alembic migration logs, etc.) is real OSA
output and is ignored by the parent except for diagnostics.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

RESULT_PREFIX = "VASB_MCP_RESULT:"


async def _run(request: dict, errlog) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # The MCP SDK's default (params.env=None) forwards only a filtered,
    # minimal environment to the spawned server - NOT the OSA_* variables
    # the parent adapter process set on THIS driver's own environment
    # (OSA_DATABASE_URL, OSA_REGISTRY_DIR, OSA_SOURCE_COMMIT_SHA). Forward
    # this process's real environment explicitly so those reach OSA.
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_start"],
        env=dict(os.environ),
    )
    # errlog defaults to this driver's own sys.stderr, which - when this
    # driver is itself a grandchild of runner.process's piped, non-tty
    # worker subprocess - can leave the spawned OSA server's stderr pointed
    # at an unread/backed-up pipe chain, observed to make the OSA server
    # process appear to close its stdio connection during the MCP
    # handshake. A dedicated real file sidesteps that pipe chain entirely;
    # its content is still read back below for real diagnostics.
    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            command = request["command"]
            if command == "list_tools":
                tools = await session.list_tools()
                return {"ok": True, "result": sorted(t.name for t in tools.tools)}
            if command == "call_tool":
                result = await session.call_tool(
                    request["tool_name"], request["arguments"]
                )
                texts = [getattr(c, "text", None) for c in result.content]
                texts = [t for t in texts if t is not None]
                if result.is_error:
                    return {"ok": False, "error": "; ".join(texts) or "<no detail>"}
                if not texts:
                    return {"ok": False, "error": "tool returned no text content"}
                try:
                    return {"ok": True, "result": json.loads(texts[0])}
                except json.JSONDecodeError:
                    return {"ok": False, "error": f"non-JSON content: {texts[0][:500]}"}
            return {"ok": False, "error": f"unknown driver command: {command!r}"}


def main() -> None:
    request = json.loads(sys.stdin.read())
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
        try:
            outcome = asyncio.run(_run(request, errlog))
        except Exception as exc:  # noqa: BLE001 - report to parent, never crash silently
            import traceback

            errlog.seek(0)
            osa_stderr_tail = errlog.read()[-4000:]
            outcome = {
                "ok": False,
                "error": (
                    f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    f"\n--- OSA server stderr ---\n{osa_stderr_tail}"
                ),
            }
    print(RESULT_PREFIX + json.dumps(outcome))


if __name__ == "__main__":
    main()
