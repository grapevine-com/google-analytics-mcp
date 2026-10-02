# Copyright 2026 Grapevine

import json
import asyncio
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from google.analytics import admin_v1beta

from analytics_mcp.mutations.confirmation import PendingMutationStore
from analytics_mcp.mutations.tools import AuditLogger, KeyEventService


class FakeCredentialManager:
    def __init__(self):
        self.calls = 0

    def get_credentials(self):
        self.calls += 1
        return object()


class FakeConfirmer:
    def __init__(self, error=None):
        self.messages = []
        self.error = error

    def confirm(self, message):
        self.messages.append(message)
        if self.error:
            raise self.error


class FakeAdminClient:
    def __init__(self):
        self.created = []
        self.deleted = []
        self.key_events = [
            admin_v1beta.KeyEvent(
                name="properties/123/keyEvents/456",
                event_name="purchase",
                deletable=True,
                custom=True,
            )
        ]

    def list_key_events(self, request):
        self.list_request = request
        return self.key_events

    def create_key_event(self, request):
        self.created.append(request)
        return admin_v1beta.KeyEvent(
            name="properties/123/keyEvents/789",
            event_name=request.key_event.event_name,
            deletable=True,
            custom=True,
        )

    def delete_key_event(self, request):
        self.deleted.append(request)

    def update_key_event(self, request):
        self.update_request = request
        return request.key_event


class KeyEventServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.audit_path = Path(self.tempdir.name) / "audit.jsonl"
        self.client = FakeAdminClient()
        self.credentials = FakeCredentialManager()
        self.confirmer = FakeConfirmer()
        self.service = KeyEventService(
            credential_manager=self.credentials,
            client_factory=lambda credentials: self.client,
            pending_store=PendingMutationStore(clock=lambda: 100),
            confirmer=self.confirmer,
            auditor=AuditLogger(self.audit_path),
        )

    async def test_lists_key_events_for_validated_property(self):
        result = await self.service.list_key_events(" 123 ")

        self.assertEqual(self.client.list_request.parent, "properties/123")
        self.assertEqual(result[0]["event_name"], "purchase")
        self.assertEqual(self.credentials.calls, 1)

    async def test_updates_conversion_counting_with_exact_field_mask(self):
        prepared = await self.service.prepare_update_key_event(
            "properties/123/keyEvents/456", "ONCE_PER_SESSION"
        )
        result = await self.service.apply_key_event_mutation(
            prepared["mutation_id"]
        )
        self.assertEqual(result["counting_method"], "ONCE_PER_SESSION")
        self.assertEqual(
            list(self.client.update_request.update_mask.paths),
            ["counting_method"],
        )
        self.assertIn("ONCE_PER_SESSION", self.confirmer.messages[0])
        with self.assertRaises(ValueError):
            await self.service.prepare_update_key_event(
                "properties/123/keyEvents/456", "UNSPECIFIED"
            )

    async def test_create_requires_preview_then_native_confirmation(self):
        prepared = await self.service.prepare_create_key_event(
            "properties/123", "generate_lead"
        )

        self.assertEqual(
            prepared["preview"],
            {
                "operation": "create_key_event",
                "property_id": "properties/123",
                "event_name": "generate_lead",
                "counting_method": "ONCE_PER_EVENT",
            },
        )
        result = await self.service.apply_key_event_mutation(
            prepared["mutation_id"]
        )

        request = self.client.created[0]
        self.assertEqual(request.parent, "properties/123")
        self.assertEqual(request.key_event.event_name, "generate_lead")
        self.assertEqual(
            request.key_event.counting_method,
            admin_v1beta.KeyEvent.CountingMethod.ONCE_PER_EVENT,
        )
        self.assertEqual(result["event_name"], "generate_lead")
        self.assertIn("properties/123", self.confirmer.messages[0])
        self.assertIn("generate_lead", self.confirmer.messages[0])
        with self.assertRaisesRegex(RuntimeError, "already used"):
            await self.service.apply_key_event_mutation(prepared["mutation_id"])

    async def test_delete_uses_exact_previewed_resource_name(self):
        prepared = await self.service.prepare_delete_key_event(
            "properties/123/keyEvents/456"
        )

        result = await self.service.apply_key_event_mutation(
            prepared["mutation_id"]
        )

        self.assertEqual(
            self.client.deleted[0].name, "properties/123/keyEvents/456"
        )
        self.assertEqual(
            result,
            {
                "deleted": True,
                "name": "properties/123/keyEvents/456",
            },
        )

    async def test_rejects_invalid_event_and_key_event_names(self):
        for event_name in ("", "1purchase", "has-hyphen", "a" * 41):
            with self.subTest(event_name=event_name):
                with self.assertRaises(ValueError):
                    await self.service.prepare_create_key_event(
                        "properties/123", event_name
                    )
        with self.assertRaises(ValueError):
            await self.service.prepare_delete_key_event(
                "properties/123/keyEvents/not-a-number"
            )

    async def test_audit_contains_no_confirmation_or_credentials(self):
        prepared = await self.service.prepare_create_key_event(123, "purchase")
        await self.service.apply_key_event_mutation(prepared["mutation_id"])

        record = json.loads(self.audit_path.read_text().splitlines()[-1])
        self.assertEqual(record["operation"], "create_key_event")
        self.assertEqual(record["outcome"], "succeeded")
        self.assertEqual(record["property_id"], "properties/123")
        self.assertEqual(record["event_name"], "purchase")
        serialized = json.dumps(record)
        self.assertNotIn(prepared["mutation_id"], serialized)
        self.assertNotIn("token", serialized.lower())

    async def test_cancelled_confirmation_never_calls_google(self):
        self.confirmer.error = RuntimeError("cancelled")
        prepared = await self.service.prepare_create_key_event(123, "purchase")
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            await self.service.apply_key_event_mutation(prepared["mutation_id"])
        self.assertEqual(self.client.created, [])
        record = json.loads(self.audit_path.read_text().strip())
        self.assertEqual(record["outcome"], "failed")

    async def test_audit_failure_before_write_blocks_google(self):
        self.service.auditor = mock.Mock()
        self.service.auditor.write.side_effect = OSError("disk full")
        prepared = await self.service.prepare_create_key_event(123, "purchase")
        with self.assertRaises(OSError):
            await self.service.apply_key_event_mutation(prepared["mutation_id"])
        self.assertEqual(self.client.created, [])

    async def test_completion_audit_failure_reports_success_without_retry(self):
        self.service.auditor = mock.Mock()
        self.service.auditor.write.side_effect = [None, OSError("disk full")]
        prepared = await self.service.prepare_create_key_event(123, "purchase")
        result = await self.service.apply_key_event_mutation(
            prepared["mutation_id"]
        )
        self.assertTrue(result["mutation_succeeded"])
        self.assertIn("do not retry", result["audit_warning"])
        self.assertEqual(len(self.client.created), 1)

    async def test_task_cancellation_waits_for_google_and_completion_audit(
        self,
    ):
        started = threading.Event()
        release = threading.Event()
        original_create = self.client.create_key_event

        def blocked_create(request):
            started.set()
            release.wait(timeout=5)
            return original_create(request)

        self.client.create_key_event = blocked_create
        prepared = await self.service.prepare_create_key_event(123, "purchase")
        task = asyncio.create_task(
            self.service.apply_key_event_mutation(prepared["mutation_id"])
        )
        self.assertTrue(await asyncio.to_thread(started.wait, 5))
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.client.created), 1)
        records = [
            json.loads(line)
            for line in self.audit_path.read_text().splitlines()
        ]
        self.assertEqual(
            [r["outcome"] for r in records], ["attempted", "succeeded"]
        )

    async def test_invalid_property_paths_are_rejected(self):
        for value in (True, -1, "properties/x/123", "0"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await self.service.prepare_create_key_event(
                        value, "purchase"
                    )


if __name__ == "__main__":
    unittest.main()
