"""Local stdio entry point for the personal Analytics server."""

import asyncio

from mcp.server.stdio import stdio_server

from analytics_mcp.mutations.coordinator import app


async def run_server_async():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream, app.create_initialization_options()
        )


def run_server():
    asyncio.run(run_server_async())


if __name__ == "__main__":
    run_server()
