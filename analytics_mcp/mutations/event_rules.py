"""Confirmed CRUD for derived-event and event-modification rules."""

import asyncio
import json

from google.analytics import admin_v1alpha as admin
from google.protobuf.field_mask_pb2 import FieldMask

from analytics_mcp.mutations.event_validation import (
    validate_resource,
    validate_rule,
)
from analytics_mcp.mutations.tools import KeyEventService, construct_property_rn
from analytics_mcp.tools.utils import proto_to_dict


def create_personal_alpha_client(credentials):
    return admin.AnalyticsAdminServiceClient(credentials=credentials)


class EventRuleService(KeyEventService):
    """Reuse the audited confirmation lifecycle with explicit alpha clients."""

    def __init__(self, client_factory=create_personal_alpha_client, **kwargs):
        super().__init__(client_factory=client_factory, **kwargs)

    async def list_data_streams(self, property_id: int | str) -> list[dict]:
        return await self._list(
            "list_data_streams",
            admin.ListDataStreamsRequest(
                parent=construct_property_rn(property_id)
            ),
        )

    async def list_rules(self, kind: str, parent: str) -> list[dict]:
        parent = validate_resource(parent)
        if kind not in {"create", "edit"}:
            raise ValueError("Unknown rule family")
        request_type = (
            admin.ListEventCreateRulesRequest
            if kind == "create"
            else admin.ListEventEditRulesRequest
        )
        return await self._list(
            f"list_event_{kind}_rules", request_type(parent=parent)
        )

    async def _list(self, method: str, request) -> list[dict]:
        credentials = await asyncio.to_thread(
            self.credential_manager.get_credentials
        )

        def call():
            return [
                proto_to_dict(rule)
                for rule in getattr(self.client_factory(credentials), method)(
                    request=request
                )
            ]

        return await asyncio.to_thread(call)

    async def prepare_create(self, kind: str, parent: str, rule: dict) -> dict:
        parent = validate_resource(parent)
        return self._prepare(
            f"create_event_{kind}_rule",
            {"parent": parent, "rule": validate_rule(kind, rule)},
        )

    async def prepare_update(self, kind: str, name: str, rule: dict) -> dict:
        name = validate_resource(name, kind)
        rule = validate_rule(kind, rule, partial=True)
        return self._prepare(
            f"update_event_{kind}_rule",
            {"name": name, "rule": rule, "update_mask": sorted(rule)},
        )

    async def prepare_delete(self, kind: str, name: str) -> dict:
        name = validate_resource(name, kind)
        return self._prepare(f"delete_event_{kind}_rule", {"name": name})

    def _prepare(self, operation: str, arguments: dict) -> dict:
        result = super()._prepare(operation, arguments)
        result["next_step"] = (
            "Call apply_event_rule_mutation; confirm the exact change in the native macOS dialog."
        )
        return result

    @staticmethod
    def _confirmation_message(operation: str, arguments: dict) -> str:
        return "Google Analytics event-rule change:\n" + json.dumps(
            {"operation": operation, **arguments}, indent=2, sort_keys=True
        )

    async def _execute(
        self, operation: str, arguments: dict, credentials
    ) -> dict:
        # Only operations created by the fixed preparation methods are allowed.
        allowed = {
            f"{action}_event_{kind}_rule"
            for action in ("create", "update", "delete")
            for kind in ("create", "edit")
        }
        if operation not in allowed:
            raise ValueError("Unsupported event-rule mutation")
        action, _, kind, _ = operation.split("_")
        resource_type = (
            admin.EventCreateRule if kind == "create" else admin.EventEditRule
        )
        request_types = {
            "create_event_create_rule": admin.CreateEventCreateRuleRequest,
            "update_event_create_rule": admin.UpdateEventCreateRuleRequest,
            "delete_event_create_rule": admin.DeleteEventCreateRuleRequest,
            "create_event_edit_rule": admin.CreateEventEditRuleRequest,
            "update_event_edit_rule": admin.UpdateEventEditRuleRequest,
            "delete_event_edit_rule": admin.DeleteEventEditRuleRequest,
        }
        if action == "delete":
            request = request_types[operation](name=arguments["name"])
        else:
            rule = resource_type(arguments["rule"])
            fields = {f"event_{kind}_rule": rule}
            if action == "create":
                fields["parent"] = arguments["parent"]
            else:
                rule.name = arguments["name"]
                fields["update_mask"] = FieldMask(
                    paths=arguments["update_mask"]
                )
            request = request_types[operation](**fields)
        response = await asyncio.to_thread(
            getattr(self.client_factory(credentials), operation),
            request=request,
            retry=None,
            timeout=30,
        )
        if action == "delete":
            return {"deleted": True, "name": arguments["name"]}
        return proto_to_dict(response)


event_rule_service = EventRuleService()


async def list_data_streams(property_id: int | str) -> list[dict]:
    """Discover streams for event-rule management; returns full resource names."""
    return await event_rule_service.list_data_streams(property_id)


async def list_event_create_rules(parent: str) -> list[dict]:
    """List derived-event rules under properties/{id}/dataStreams/{id}."""
    return await event_rule_service.list_rules("create", parent)


async def list_event_edit_rules(parent: str) -> list[dict]:
    """List rules that modify incoming events; includes their processing order."""
    return await event_rule_service.list_rules("edit", parent)


async def prepare_create_event_create_rule(parent: str, rule: dict) -> dict:
    """Preview a derived-event rule. rule requires destination_event and event_conditions.

    Optional: source_copy_parameters (boolean), parameter_mutations. Conditions
    use field, comparison_type (EQUALS, CONTAINS, etc.), value, optional negated.
    Parameter mutations use parameter and parameter_value. Apply the returned
    ID with apply_event_rule_mutation. Existing source events must be collected.
    """
    return await event_rule_service.prepare_create("create", parent, rule)


async def prepare_update_event_create_rule(name: str, rule: dict) -> dict:
    """Preview changes to a derived-event rule; supply only changed writable fields.

    destination_event, event_conditions, source_copy_parameters,
    parameter_mutations. Lists replace their entire previous value; omitted
    fields remain unchanged. Apply with apply_event_rule_mutation.
    """
    return await event_rule_service.prepare_update("create", name, rule)


async def prepare_delete_event_create_rule(name: str) -> dict:
    """Preview removing a derived-event rule, not historical collected events."""
    return await event_rule_service.prepare_delete("create", name)


async def prepare_create_event_edit_rule(parent: str, rule: dict) -> dict:
    """Preview modifying incoming events; requires display_name, event_conditions,
    and parameter_mutations. Set parameter='event_name' to rename matching
    incoming events. A new rule is appended to processing order. Cannot edit
    events generated by event-create rules. Apply with apply_event_rule_mutation.
    """
    return await event_rule_service.prepare_create("edit", parent, rule)


async def prepare_update_event_edit_rule(name: str, rule: dict) -> dict:
    """Preview partial changes to display_name, event_conditions, parameter_mutations.

    Lists replace their entire previous value. Omitted fields remain unchanged.
    Apply with apply_event_rule_mutation.
    """
    return await event_rule_service.prepare_update("edit", name, rule)


async def prepare_delete_event_edit_rule(name: str) -> dict:
    """Preview removing an event-modification rule, not historical events."""
    return await event_rule_service.prepare_delete("edit", name)


async def apply_event_rule_mutation(mutation_id: str) -> dict:
    """Apply an event-rule preview after exact native macOS user confirmation."""
    return await event_rule_service.apply_key_event_mutation(mutation_id)
