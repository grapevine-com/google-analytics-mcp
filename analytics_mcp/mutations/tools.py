"""Confirmation-gated Google Analytics key-event tools."""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from google.analytics import admin_v1beta

from analytics_mcp.mutations.auth import credential_manager
from analytics_mcp.mutations.execution import finish_before_cancelling
from analytics_mcp.mutations.confirmation import (
    MacOSConfirmer,
    PendingMutationStore,
)
from analytics_mcp.tools.utils import proto_to_dict

_EVENT_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_KEY_EVENT_NAME_PATTERN = re.compile(
    r"^properties/(?P<property_id>[0-9]+)/keyEvents/[0-9]+$"
)
_DEFAULT_AUDIT_PATH = Path(
    "~/Library/Logs/analytics-mutations-mcp/audit.jsonl"
).expanduser()


def construct_property_rn(value: int | str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Invalid property ID")
    match = re.fullmatch(r"(?:properties/)?([0-9]+)", str(value).strip())
    if match is None or int(match[1]) <= 0:
        raise ValueError("Property ID must be a positive numeric ID")
    return f"properties/{int(match[1])}"


def create_personal_admin_client(credentials):
    return admin_v1beta.AnalyticsAdminServiceClient(credentials=credentials)


class AuditLogger:
    """Writes minimal mutation outcomes without credentials or report data."""

    def __init__(self, path: str | Path | None = None):
        configured_path = path or os.environ.get(
            "ANALYTICS_MUTATIONS_AUDIT_LOG", _DEFAULT_AUDIT_PATH
        )
        self.path = Path(configured_path).expanduser()

    def write(
        self,
        operation: str,
        arguments: dict,
        outcome: str,
        error_type: str | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "outcome": outcome,
            **self._safe_arguments(operation, arguments),
        }
        if error_type:
            record["error_type"] = error_type
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        with os.fdopen(descriptor, "a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(record, separators=(",", ":")) + "\n")

    @staticmethod
    def _safe_arguments(operation: str, arguments: dict) -> dict:
        if operation == "create_key_event":
            return {
                "property_id": arguments["property_id"],
                "event_name": arguments["event_name"],
            }
        name = arguments["name"]
        return {
            "property_id": "/".join(name.split("/")[:2]),
            "key_event_name": name,
        }


class KeyEventService:
    """Lists and safely mutates GA4 key-event configuration."""

    def __init__(
        self,
        credential_manager=credential_manager,
        client_factory=create_personal_admin_client,
        pending_store=None,
        confirmer=None,
        auditor=None,
    ):
        self.credential_manager = credential_manager
        self.client_factory = client_factory
        self.pending_store = pending_store or PendingMutationStore()
        self.confirmer = confirmer or MacOSConfirmer()
        self.auditor = auditor or AuditLogger()

    async def list_key_events(self, property_id: int | str) -> list[dict]:
        """List the key events configured for a GA4 property."""
        parent = construct_property_rn(property_id)
        credentials = await asyncio.to_thread(
            self.credential_manager.get_credentials
        )
        request = admin_v1beta.ListKeyEventsRequest(parent=parent)

        def _list():
            return list(
                self.client_factory(credentials).list_key_events(
                    request=request
                )
            )

        response = await asyncio.to_thread(_list)
        return [proto_to_dict(key_event) for key_event in response]

    async def prepare_create_key_event(
        self, property_id: int | str, event_name: str
    ) -> dict:
        """Preview creation of a GA4 key event without changing Analytics."""
        parent = construct_property_rn(property_id)
        event_name = self._validate_event_name(event_name)
        arguments = {
            "property_id": parent,
            "event_name": event_name,
            "counting_method": "ONCE_PER_EVENT",
        }
        return self._prepare("create_key_event", arguments)

    async def prepare_delete_key_event(self, name: str) -> dict:
        """Preview deletion of a GA4 key event without changing Analytics."""
        name = self._validate_key_event_name(name)
        return self._prepare("delete_key_event", {"name": name})

    async def apply_key_event_mutation(self, mutation_id: str) -> dict:
        """Apply a prepared mutation after a native human confirmation dialog.

        The mutation ID is short-lived and single-use. Calling this tool opens a
        macOS dialog containing the exact operation; no Google Analytics change
        occurs unless the operator clicks Confirm.
        """
        return await finish_before_cancelling(
            self._apply_key_event_mutation(mutation_id)
        )

    async def _apply_key_event_mutation(self, mutation_id: str) -> dict:
        mutation = self.pending_store.consume(mutation_id)
        message = self._confirmation_message(
            mutation.operation, mutation.arguments
        )
        try:
            await asyncio.to_thread(self.confirmer.confirm, message)
            credentials = await asyncio.to_thread(
                self.credential_manager.get_credentials
            )
            # A durable attempt must exist before the irreversible API call.
            self.auditor.write(
                mutation.operation, mutation.arguments, "attempted"
            )
            result = await self._execute(
                mutation.operation, mutation.arguments, credentials
            )
        except Exception as error:
            self.auditor.write(
                mutation.operation,
                mutation.arguments,
                "failed",
                type(error).__name__,
            )
            raise
        try:
            self.auditor.write(
                mutation.operation, mutation.arguments, "succeeded"
            )
        except OSError:
            return {
                "mutation_succeeded": True,
                "result": result,
                "audit_warning": "Completion audit failed; do not retry this mutation.",
            }
        return result

    def _prepare(self, operation: str, arguments: dict) -> dict:
        mutation_id = self.pending_store.prepare(operation, arguments)
        return {
            "mutation_id": mutation_id,
            "expires_in_seconds": self.pending_store.ttl_seconds,
            "preview": {"operation": operation, **arguments},
            "next_step": (
                "Call apply_key_event_mutation with mutation_id. A native "
                "macOS dialog will require the operator to confirm."
            ),
        }

    async def _execute(
        self, operation: str, arguments: dict, credentials
    ) -> dict:
        client = self.client_factory(credentials)
        if operation == "create_key_event":
            request = admin_v1beta.CreateKeyEventRequest(
                parent=arguments["property_id"],
                key_event=admin_v1beta.KeyEvent(
                    event_name=arguments["event_name"],
                    counting_method=arguments["counting_method"],
                ),
            )
            response = await asyncio.to_thread(
                client.create_key_event, request=request
            )
            return proto_to_dict(response)
        if operation == "delete_key_event":
            request = admin_v1beta.DeleteKeyEventRequest(name=arguments["name"])
            await asyncio.to_thread(client.delete_key_event, request=request)
            return {"deleted": True, "name": arguments["name"]}
        raise ValueError(f"Unsupported mutation operation: {operation}")

    @staticmethod
    def _validate_event_name(event_name: str) -> str:
        if not isinstance(event_name, str):
            raise ValueError("event_name must be a string")
        event_name = event_name.strip()
        if not _EVENT_NAME_PATTERN.fullmatch(event_name):
            raise ValueError(
                "event_name must start with a letter, contain only letters, "
                "numbers, or underscores, and be at most 40 characters"
            )
        return event_name

    @staticmethod
    def _validate_key_event_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("name must be a key-event resource name")
        name = name.strip()
        if not _KEY_EVENT_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                "name must match properties/{property_id}/keyEvents/{id}"
            )
        return name

    @staticmethod
    def _confirmation_message(operation: str, arguments: dict) -> str:
        if operation == "create_key_event":
            return (
                f"Create key event '{arguments['event_name']}' in "
                f"{arguments['property_id']}? Counting method: {arguments['counting_method']}"
            )
        return f"Delete key event {arguments['name']}?"


key_event_service = KeyEventService()


async def list_key_events(property_id: int | str) -> list[dict]:
    """List the key events configured for a GA4 property."""
    return await key_event_service.list_key_events(property_id)


async def prepare_create_key_event(
    property_id: int | str, event_name: str
) -> dict:
    """Preview creating a key event; this does not mutate Analytics."""
    return await key_event_service.prepare_create_key_event(
        property_id, event_name
    )


async def prepare_delete_key_event(name: str) -> dict:
    """Preview deleting a key event; this does not mutate Analytics."""
    return await key_event_service.prepare_delete_key_event(name)


async def apply_key_event_mutation(mutation_id: str) -> dict:
    """Apply a previewed key-event change after native user confirmation."""
    return await key_event_service.apply_key_event_mutation(mutation_id)
