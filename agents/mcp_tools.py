"""
agents/mcp_tools.py
-------------------
Shared async helper for calling FastMCP stdio servers from within ADK agents.

Each MCP server is a self-contained Python script that exposes tools via the
Model Context Protocol (MCP) over stdio.  This module spawns the server as a
subprocess, communicates with it using the official `mcp` Python SDK, and
returns the tool's text response.

Security note
--------------
MCP subprocesses receive only a safe allowlist of environment variables.
The full parent ``os.environ`` is NEVER forwarded to prevent accidental
leakage of secrets held by other tools (e.g. IDE tokens, cloud credentials).

Data contract for callers
--------------------------
  result: str  – JSON-encoded payload from the MCP server tool.
                 Always parse with json.loads() on the caller side.
"""

import sys
import os
import logging
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

# Absolute path to the project root (one level above this file)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def call_mcp_tool(server_script: str, tool_name: str, arguments: dict) -> str:
    """
    Spawn an MCP stdio server and invoke one of its tools.

    Parameters
    ----------
    server_script : str
        Path to the MCP server Python file, relative to PROJECT_ROOT.
        Example: ``"mcp_servers/pubmed.py"``
    tool_name : str
        The name of the tool registered on that server with ``@mcp.tool()``.
    arguments : dict
        Keyword arguments forwarded to the tool.

    Returns
    -------
    str
        The raw text response from the tool (usually JSON).

    Raises
    ------
    FileNotFoundError
        If the server script does not exist.
    RuntimeError
        If the MCP call fails for any reason.
    """
    server_path = os.path.join(PROJECT_ROOT, server_script)
    if not os.path.exists(server_path):
        raise FileNotFoundError(f"MCP server script not found: {server_path}")

    # Security: pass only an allowlist of env vars to the subprocess.
    # Never propagate the full parent environment — it may contain IDE tokens,
    # SSH keys, or other credentials irrelevant to the MCP server.
    _SAFE_ENV_KEYS = {
        # Python runtime
        "PATH", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
        # Vertex AI / Gemini auth
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_GENAI_USE_ENTERPRISE",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GEMINI_API_KEY",
        # Standard OS locale / encoding (required for some stdlib modules)
        "LANG", "LC_ALL", "LC_CTYPE", "USERPROFILE", "HOME", "TEMP", "TMP",
        # Proxy (needed for requests library on some networks)
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy",
    }
    safe_env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_path],
        env=safe_env,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool(tool_name, arguments)
                parts = [
                    block.text
                    for block in response.content
                    if hasattr(block, "text") and block.text
                ]
                return "".join(parts)
    except Exception as exc:
        logger.error(
            "MCP call failed – server=%s tool=%s args=%s error=%s",
            server_script, tool_name, arguments, exc,
        )
        raise RuntimeError(
            f"MCP tool '{tool_name}' on '{server_script}' failed: {exc}"
        ) from exc
