# Copyright 2026 Grapevine
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Streamable-HTTP entry point for Bedrock AgentCore Runtime.

AgentCore's MCP protocol contract: listen on 0.0.0.0:8000 and serve stateless
streamable HTTP at /mcp. This reuses upstream's server (all tools registered in
``analytics_mcp.coordinator.app``) and only swaps the stdio transport for HTTP.
Responses are plain JSON rather than SSE so simple JSON-RPC clients work.
"""

import contextlib
import os
import sys

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

import analytics_mcp.coordinator as coordinator
from grapevine.credentials import install_credentials

MCP_PATH = "/mcp"


class _McpEndpoint:
    """ASGI app that hands /mcp requests to the session manager.

    A class instance (not a function) so Starlette's Route passes the raw ASGI
    scope through instead of wrapping it as a request handler, and so /mcp
    needs no trailing-slash redirect as a Mount would.
    """

    def __init__(self, session_manager):
        self._session_manager = session_manager

    async def __call__(self, scope, receive, send):
        await self._session_manager.handle_request(scope, receive, send)


async def _ping(request):
    return JSONResponse({"status": "Healthy"})


def create_app():
    """Returns the Starlette app serving MCP at /mcp."""
    session_manager = StreamableHTTPSessionManager(
        app=coordinator.app, stateless=True, json_response=True
    )

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    return Starlette(
        routes=[
            Route(
                MCP_PATH,
                endpoint=_McpEndpoint(session_manager),
                methods=["GET", "POST", "DELETE"],
            ),
            Route("/ping", endpoint=_ping, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


def run_server():
    mode = install_credentials()
    print(f"Google credentials mode: {mode}", file=sys.stderr)
    uvicorn.run(
        create_app(),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    run_server()
