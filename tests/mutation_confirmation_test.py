# Copyright 2026 Grapevine

import unittest
from unittest import mock

from analytics_mcp.mutations.confirmation import (
    ConfirmationError,
    MacOSConfirmer,
    PendingMutationStore,
)


class PendingMutationStoreTest(unittest.TestCase):
    def test_pending_mutation_is_single_use(self):
        now = 100.0
        store = PendingMutationStore(clock=lambda: now)

        mutation_id = store.prepare(
            "create_key_event",
            {"property_id": "properties/123", "event_name": "purchase"},
        )

        mutation = store.consume(mutation_id)
        self.assertEqual(mutation.operation, "create_key_event")
        self.assertEqual(mutation.arguments["event_name"], "purchase")
        with self.assertRaisesRegex(ConfirmationError, "not found"):
            store.consume(mutation_id)

    def test_expired_mutation_is_rejected_and_removed(self):
        current_time = [100.0]
        store = PendingMutationStore(
            ttl_seconds=30, clock=lambda: current_time[0]
        )
        mutation_id = store.prepare("delete_key_event", {"name": "keyEvents/1"})
        current_time[0] = 131.0

        with self.assertRaisesRegex(ConfirmationError, "expired"):
            store.consume(mutation_id)
        with self.assertRaisesRegex(ConfirmationError, "not found"):
            store.consume(mutation_id)


class MacOSConfirmerTest(unittest.TestCase):
    @mock.patch("analytics_mcp.mutations.confirmation.subprocess.run")
    def test_confirmation_uses_argument_safe_macos_dialog(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="OK\n")
        confirmer = MacOSConfirmer(platform_name="Darwin")

        confirmer.confirm('Create key event "purchase"?')

        command = run.call_args.args[0]
        self.assertEqual(command[0:2], ["osascript", "-e"])
        self.assertEqual(command[-1], 'Create key event "purchase"?')
        self.assertNotIn('Create key event "purchase"?', command[2])

    def test_confirmation_fails_closed_off_macos(self):
        confirmer = MacOSConfirmer(platform_name="Linux")

        with self.assertRaisesRegex(ConfirmationError, "macOS"):
            confirmer.confirm("Create key event?")

    @mock.patch("analytics_mcp.mutations.confirmation.subprocess.run")
    def test_cancelled_dialog_rejects_mutation(self, run):
        run.return_value = mock.Mock(returncode=1, stdout="")
        confirmer = MacOSConfirmer(platform_name="Darwin")

        with self.assertRaisesRegex(ConfirmationError, "cancelled"):
            confirmer.confirm("Delete key event?")


if __name__ == "__main__":
    unittest.main()
