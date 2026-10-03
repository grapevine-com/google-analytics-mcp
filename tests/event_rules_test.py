"""Journey event rules: real SDK requests against a fake Google boundary."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from google.analytics import admin_v1alpha as admin

from analytics_mcp.mutations.event_rules import EventRuleService
from tests.mutation_tools_test import FakeConfirmer, FakeCredentialManager
from analytics_mcp.mutations.tools import AuditLogger

STREAM = "properties/123/dataStreams/456"
CONDITIONS = [
    {"field": "event_name", "comparison_type": "EQUALS", "value": "page_view"}
]
CREATE = {
    "destination_event": "booking_completed",
    "event_conditions": CONDITIONS,
    "source_copy_parameters": True,
}
EDIT = {
    "display_name": "Rename form submission",
    "event_conditions": CONDITIONS,
    "parameter_mutations": [
        {"parameter": "event_name", "parameter_value": "form_submitted"}
    ],
}


class FakeRuleClient:
    def __init__(self):
        self.requests = []

    def __getattr__(self, method):
        if method not in {
            f"{action}_event_{kind}_rule"
            for action in ("create", "update", "delete")
            for kind in ("create", "edit")
        }:
            raise AttributeError(method)

        def call(*, request, retry=None, timeout=None):
            self.requests.append((method, request))
            if method.startswith("delete"):
                return None
            kind = "create" if method.endswith("create_rule") else "edit"
            rule = getattr(request, f"event_{kind}_rule")
            rule.name = rule.name or f"{STREAM}/event{kind.title()}Rules/789"
            return rule

        return call


class EventRuleTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.audit = Path(self.directory.name) / "audit.jsonl"
        self.client = FakeRuleClient()
        self.confirmer = FakeConfirmer()
        self.service = EventRuleService(
            credential_manager=FakeCredentialManager(),
            client_factory=lambda credentials: self.client,
            confirmer=self.confirmer,
            auditor=AuditLogger(self.audit),
        )

    async def test_both_rule_families_support_create_partial_update_delete(
        self,
    ):
        for kind, rule in (("create", CREATE), ("edit", EDIT)):
            with self.subTest(kind=kind):
                prepared = await self.service.prepare_create(kind, STREAM, rule)
                self.assertEqual(
                    len(self.client.requests), 0 if kind == "create" else 3
                )
                result = await self.service.apply_key_event_mutation(
                    prepared["mutation_id"]
                )
                name = result["name"]
                field = (
                    "destination_event" if kind == "create" else "display_name"
                )
                prepared = await self.service.prepare_update(
                    kind, name, {field: "updated_name"}
                )
                await self.service.apply_key_event_mutation(
                    prepared["mutation_id"]
                )
                method, request = self.client.requests[-1]
                self.assertEqual(method, f"update_event_{kind}_rule")
                self.assertEqual(list(request.update_mask.paths), [field])
                self.assertEqual(
                    getattr(request, f"event_{kind}_rule").name, name
                )
                prepared = await self.service.prepare_delete(kind, name)
                deleted = await self.service.apply_key_event_mutation(
                    prepared["mutation_id"]
                )
                self.assertEqual(deleted, {"deleted": True, "name": name})
                self.assertEqual(self.client.requests[-1][1].name, name)

    async def test_confirmation_uses_immutable_deep_snapshot(self):
        rule = copy.deepcopy(CREATE)
        prepared = await self.service.prepare_create("create", STREAM, rule)
        rule["event_conditions"][0]["value"] = "tampered"
        prepared["preview"]["rule"]["event_conditions"][0][
            "value"
        ] = "tampered_again"
        await self.service.apply_key_event_mutation(prepared["mutation_id"])
        request = self.client.requests[0][1]
        self.assertEqual(
            request.event_create_rule.event_conditions[0].value, "page_view"
        )
        self.assertIn('"value": "page_view"', self.confirmer.messages[0])
        self.assertNotIn("tampered", self.confirmer.messages[0])

    async def test_rejects_unknown_fields_invalid_limits_and_cross_family_names(
        self,
    ):
        invalid_rules = [
            {**CREATE, "name": "injected"},
            {**CREATE, "destination_event": "a" * 40},
            {**CREATE, "event_conditions": []},
            {**CREATE, "event_conditions": CONDITIONS * 11},
            {**CREATE, "source_copy_parameters": "true"},
            {
                **CREATE,
                "event_conditions": [
                    {
                        "field": "event_name",
                        "comparison_type": "BAD",
                        "value": "x",
                    }
                ],
            },
            {
                **CREATE,
                "parameter_mutations": [
                    {"parameter": "x", "parameter_value": "a" * 100}
                ],
            },
        ]
        for rule in invalid_rules:
            with self.subTest(rule=rule):
                with self.assertRaises(ValueError):
                    await self.service.prepare_create("create", STREAM, rule)
        with self.assertRaises(ValueError):
            await self.service.prepare_delete(
                "edit", f"{STREAM}/eventCreateRules/789"
            )
        with self.assertRaises(ValueError):
            await self.service.prepare_update(
                "create", f"{STREAM}/eventCreateRules/789", {}
            )
        self.assertEqual(self.client.requests, [])

    async def test_cancelled_confirmation_and_audit_redaction(self):
        self.confirmer.error = RuntimeError("cancelled")
        prepared = await self.service.prepare_create("create", STREAM, CREATE)
        with self.assertRaises(RuntimeError):
            await self.service.apply_key_event_mutation(prepared["mutation_id"])
        self.assertEqual(self.client.requests, [])
        record = json.loads(self.audit.read_text())
        self.assertEqual(record["property_id"], "properties/123")
        self.assertNotIn("event_conditions", record)
        self.assertNotIn("page_view", self.audit.read_text())


if __name__ == "__main__":
    unittest.main()
