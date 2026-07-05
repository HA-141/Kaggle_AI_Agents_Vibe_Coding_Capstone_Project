import sys
import os
import logging
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("mcp_client")

async def call_mcp_tool(server_filename: str, tool_name: str, arguments: dict) -> str:
    """
    Spawns an MCP server subprocess and invokes a tool.
    
    :param server_filename: The path to the Python script (e.g., 'mcp_servers/pubmed.py')
    :param tool_name: The name of the tool to call
    :param arguments: Dictionary of arguments to pass to the tool
    :return: The string content returned by the tool
    """
    server_path = os.path.abspath(server_filename)
    if not os.path.exists(server_path):
        raise FileNotFoundError(f"MCP Server script not found at {server_path}")
        
    # Security: pass only an allowlist of env vars to the subprocess.
    # Never propagate the full parent environment — it may contain IDE tokens,
    # SSH keys, or other credentials irrelevant to the MCP server.
    _SAFE_ENV_KEYS = {
        "PATH", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
        "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE",
        "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_APPLICATION_CREDENTIALS", "GEMINI_API_KEY",
        "LANG", "LC_ALL", "LC_CTYPE", "USERPROFILE", "HOME", "TEMP", "TMP",
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
                # Initialize session
                await session.initialize()
                
                # Invoke tool
                response = await session.call_tool(tool_name, arguments)
                
                # Aggregate text contents
                text_parts = []
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        text_parts.append(block.text)
                return "".join(text_parts)
    except Exception as e:
        logger.error(f"Error calling MCP tool {tool_name} on {server_filename}: {e}")
        raise e
