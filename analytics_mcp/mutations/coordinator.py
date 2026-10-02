"""Independent registry for personal OAuth reads and confirmed mutations."""

import asyncio
import copy
import json

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.conversion_utils import adk_to_mcp_tool_type
from mcp import types
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import McpError

from analytics_mcp import coordinator as readonly
from analytics_mcp.mutations.auth import (
    credential_manager,
    google_analytics_authorize,
    google_analytics_auth_status,
    google_analytics_disconnect,
)
from analytics_mcp.mutations.tools import (
    apply_key_event_mutation,
    list_key_events,
    prepare_create_key_event,
    prepare_delete_key_event,
)
from analytics_mcp.mutations.execution import finish_before_cancelling

_AUTH_TOOLS = {
    "google_analytics_authorize",
    "google_analytics_auth_status",
    "google_analytics_disconnect",
}
tools = list(readonly.tools) + [
    FunctionTool(function)
    for function in (
        google_analytics_authorize,
        google_analytics_auth_status,
        google_analytics_disconnect,
        list_key_events,
        prepare_create_key_event,
        prepare_delete_key_event,
        apply_key_event_mutation,
    )
]
tool_map = {tool.name: tool for tool in tools}
mcp_tools = copy.deepcopy(readonly.mcp_tools) + [
    adk_to_mcp_tool_type(tool) for tool in tools[len(readonly.tools) :]
]
for tool in mcp_tools:
    if not tool.inputSchema:
        tool.inputSchema = {"type": "object", "properties": {}}
    readonly.sanitize_mcp_schema_properties(tool.inputSchema)

app = Server(name="Google Analytics Personal Mutations MCP Server")
_invocation_lock = asyncio.Lock()


def requires_authorization(name: str) -> bool:
    return name not in _AUTH_TOOLS


@app.list_tools()
async def list_tools():
    return mcp_tools


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    # Shared upstream read helpers use a cached credential. Serialize calls so
    # auth lifecycle changes cannot replace it during a read invocation.
    async with _invocation_lock:
        return await finish_before_cancelling(_call_tool(name, arguments))


async def _call_tool(name: str, arguments: dict):
    try:
        if name not in tool_map:
            raise ValueError("Unknown tool")
        if requires_authorization(name):
            await asyncio.to_thread(credential_manager.get_credentials)
        result = await tool_map[name].run_async(
            args=arguments, tool_context=None
        )
        return [types.TextContent(type="text", text=json.dumps(result))]
    except Exception as error:
        # OAuth and upstream errors may contain credential material. Never
        # return their raw messages to the model or protocol logs.
        raise McpError(
            types.ErrorData(
                code=-32000,
                message=f"Tool failed ({type(error).__name__}); check authorization, inputs, and Google permissions.",
            )
        ) from None
