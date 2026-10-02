# Copyright 2026 Grapevine

import unittest
import sys
import asyncio
from unittest import mock

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import analytics_mcp.coordinator as readonly_coordinator
import analytics_mcp.mutations.coordinator as mutation_coordinator


class MutationCoordinatorTest(unittest.TestCase):
    def test_separate_server_adds_auth_and_key_event_tools(self):
        readonly_names = set(readonly_coordinator.tool_map)
        mutation_names = set(mutation_coordinator.tool_map)

        self.assertEqual(
            readonly_names,
            {
                "get_account_summaries",
                "list_google_ads_links",
                "get_property_details",
                "list_property_annotations",
                "get_custom_dimensions_and_metrics",
                "run_report",
                "run_realtime_report",
                "run_funnel_report",
                "run_conversions_report",
            },
        )
        self.assertEqual(
            mutation_names - readonly_names,
            {
                "google_analytics_authorize",
                "google_analytics_auth_status",
                "google_analytics_disconnect",
                "list_key_events",
                "prepare_create_key_event",
                "prepare_delete_key_event",
                "apply_key_event_mutation",
            },
        )
        self.assertEqual(
            readonly_coordinator.app.name, "Google Analytics MCP Server"
        )
        self.assertEqual(
            mutation_coordinator.app.name,
            "Google Analytics Personal Mutations MCP Server",
        )

    def test_only_auth_lifecycle_tools_can_run_without_authorization(self):
        self.assertFalse(
            mutation_coordinator.requires_authorization(
                "google_analytics_authorize"
            )
        )
        self.assertFalse(
            mutation_coordinator.requires_authorization(
                "google_analytics_auth_status"
            )
        )
        self.assertFalse(
            mutation_coordinator.requires_authorization(
                "google_analytics_disconnect"
            )
        )
        self.assertTrue(
            mutation_coordinator.requires_authorization("run_report")
        )
        self.assertTrue(
            mutation_coordinator.requires_authorization(
                "prepare_create_key_event"
            )
        )


class MutationStdioTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_invocation_keeps_identity_lock_until_finished(
        self,
    ):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def fake_call(name, arguments):
            calls.append(name)
            if name == "run_report":
                entered.set()
                await release.wait()
            return []

        with (
            mock.patch.object(
                mutation_coordinator, "_invocation_lock", asyncio.Lock()
            ),
            mock.patch.object(mutation_coordinator, "_call_tool", fake_call),
        ):
            read = asyncio.create_task(
                mutation_coordinator.call_tool("run_report", {})
            )
            await entered.wait()
            read.cancel()
            disconnect = asyncio.create_task(
                mutation_coordinator.call_tool(
                    "google_analytics_disconnect", {}
                )
            )
            await asyncio.sleep(0)
            self.assertEqual(calls, ["run_report"])
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await read
            await disconnect
            self.assertEqual(
                calls, ["run_report", "google_analytics_disconnect"]
            )

    async def test_real_stdio_server_initializes_and_lists_tools(self):
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "analytics_mcp.mutations.server"],
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                self.assertEqual(
                    initialized.serverInfo.name,
                    "Google Analytics Personal Mutations MCP Server",
                )
                self.assertEqual(len(tools.tools), 16)


if __name__ == "__main__":
    unittest.main()
