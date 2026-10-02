"""Validate only the writable GA4 event-rule fields before previewing."""

import copy
import json
import re

from google.analytics import admin_v1alpha as admin

_STREAM = r"properties/[1-9][0-9]*/dataStreams/[1-9][0-9]*"
_FIELDS = {
    "create": {
        "destination_event",
        "event_conditions",
        "source_copy_parameters",
        "parameter_mutations",
    },
    "edit": {"display_name", "event_conditions", "parameter_mutations"},
}
_COMPARISONS = {
    value.name
    for value in admin.MatchingCondition.ComparisonType
    if value.value
}


def validate_resource(name: str, kind: str | None = None) -> str:
    if not isinstance(name, str):
        raise ValueError("Resource name must be a string")
    suffix = "" if kind is None else f"/event{kind.title()}Rules/[A-Za-z0-9_-]+"
    if kind is not None and kind not in _FIELDS:
        raise ValueError("Unknown event-rule family")
    if not re.fullmatch(_STREAM + suffix, name):
        raise ValueError("Invalid data-stream or event-rule resource name")
    return name


def _text(value, field: str, limit: int, empty: bool = False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value)
    ):
        raise ValueError(
            f"{field} must be a string of at most {limit} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} must not contain control characters")


def validate_rule(kind: str, rule: dict, partial: bool = False) -> dict:
    if kind not in _FIELDS or not isinstance(rule, dict) or not rule:
        raise ValueError(
            "A nonempty rule object and valid rule family are required"
        )
    if set(rule) - _FIELDS[kind]:
        raise ValueError("Unknown, immutable, or output-only rule fields")
    required = (
        {"destination_event", "event_conditions"}
        if kind == "create"
        else {"display_name", "event_conditions", "parameter_mutations"}
    )
    if not partial and not required <= set(rule):
        raise ValueError("Required rule fields are missing")
    if "destination_event" in rule:
        value = rule["destination_event"]
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{0,38}", value
        ):
            raise ValueError(
                "destination_event must start with a letter and be less than 40 characters"
            )
    if "display_name" in rule:
        _text(rule["display_name"], "display_name", 255)
    if (
        "source_copy_parameters" in rule
        and type(rule["source_copy_parameters"]) is not bool
    ):
        raise ValueError("source_copy_parameters must be boolean")
    if "event_conditions" in rule:
        conditions = rule["event_conditions"]
        if not isinstance(conditions, list) or not 1 <= len(conditions) <= 10:
            raise ValueError("event_conditions must contain 1 to 10 conditions")
        for condition in conditions:
            if not isinstance(condition, dict) or set(condition) - {
                "field",
                "comparison_type",
                "value",
                "negated",
            }:
                raise ValueError("Invalid condition fields")
            _text(condition.get("field"), "condition field", 40)
            if any(c.isspace() for c in condition["field"]):
                raise ValueError("Condition field must not contain spaces")
            comparison = condition.get("comparison_type")
            if (
                not isinstance(comparison, str)
                or comparison not in _COMPARISONS
            ):
                raise ValueError(
                    "Invalid comparison_type; use an SDK enum name such as EQUALS or CONTAINS"
                )
            _text(condition.get("value"), "condition value", 1024, empty=True)
            if (
                "negated" in condition
                and type(condition["negated"]) is not bool
            ):
                raise ValueError("negated must be boolean")
    if "parameter_mutations" in rule:
        mutations = rule["parameter_mutations"]
        if (
            not isinstance(mutations, list)
            or len(mutations) > 20
            or (kind == "edit" and not mutations)
        ):
            raise ValueError(
                "parameter_mutations permits up to 20 items; edit rules require at least one"
            )
        parameters = set()
        for mutation in mutations:
            if not isinstance(mutation, dict) or set(mutation) != {
                "parameter",
                "parameter_value",
            }:
                raise ValueError(
                    "Parameter mutations require parameter and parameter_value"
                )
            parameter = mutation["parameter"]
            if not isinstance(parameter, str) or not re.fullmatch(
                r"[A-Za-z0-9_]{1,39}", parameter
            ):
                raise ValueError("Invalid parameter name")
            if parameter in parameters or (
                kind == "create" and parameter == "event_name"
            ):
                raise ValueError(
                    "Duplicate parameter or invalid event_name mutation"
                )
            parameters.add(parameter)
            _text(
                mutation["parameter_value"], "parameter_value", 99, empty=True
            )
            if parameter == "event_name" and not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]{0,38}", mutation["parameter_value"]
            ):
                raise ValueError(
                    "event_name mutation must be a valid event name"
                )
    if len(json.dumps(rule)) > 8192:
        raise ValueError("Rule preview exceeds the 8192-character local limit")
    return copy.deepcopy(rule)
