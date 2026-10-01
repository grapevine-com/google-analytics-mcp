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

"""Tests for the AgentCore streamable-HTTP entry point."""

import json
import unittest
from unittest import mock

from starlette.testclient import TestClient

import analytics_mcp.coordinator as coordinator
from grapevine.agentcore_server import create_app

# What a plain JSON-RPC client (like gvc-agent's MCPClient) sends.
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def rpc(method, params=None):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


class AgentCoreServerTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def post(self, body):
        return self.client.post("/mcp", json=body, headers=HEADERS)

    def test_tools_list_without_initialize(self):
        # Stateless: every request stands alone, so clients can skip the
        # initialize handshake, as gvc-agent's MCPClient does.
        response = self.post(rpc("tools/list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"].split(";")[0], "application/json"
        )
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        self.assertEqual(names, set(coordinator.tool_map))
        self.assertIn("run_report", names)

    def test_initialize(self):
        response = self.post(
            rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["result"]["serverInfo"]["name"],
            coordinator.app.name,
        )

    def test_tools_call_runs_upstream_tool(self):
        fake_tool = mock.Mock()
        fake_tool.run_async = mock.AsyncMock(
            return_value=[{"account": "accounts/1"}]
        )
        with mock.patch.dict(
            coordinator.tool_map, {"get_account_summaries": fake_tool}
        ):
            response = self.post(
                rpc(
                    "tools/call",
                    {"name": "get_account_summaries", "arguments": {}},
                )
            )

        self.assertEqual(response.status_code, 200)
        content = response.json()["result"]["content"]
        self.assertEqual(
            json.loads(content[0]["text"]), [{"account": "accounts/1"}]
        )
        fake_tool.run_async.assert_awaited_once_with(args={}, tool_context=None)

    def test_mcp_path_has_no_trailing_slash_redirect(self):
        response = self.client.post(
            "/mcp",
            json=rpc("tools/list"),
            headers=HEADERS,
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)

    def test_ping(self):
        response = self.client.get("/ping")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "Healthy"})


if __name__ == "__main__":
    unittest.main()
