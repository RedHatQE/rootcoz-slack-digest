"""Resolve JSON dot-paths and templates against API response dicts."""

from __future__ import annotations

import string
from typing import Any


def resolve_path(data: dict[str, Any], path: str) -> Any:
    """Resolve a dot-separated path against a nested dict.

    Examples:
        resolve_path({"a": {"b": 1}}, "a.b") → 1
        resolve_path({"x": 5}, "x") → 5
        resolve_path({"a": None}, "a.b") → None
    """
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def resolve_template(template: str, fields: dict[str, str], config_vars: dict[str, str]) -> str:
    """Resolve a template string like '{url}/results/{job_id}'.

    Looks up placeholders in fields first, then config_vars.
    Unknown placeholders are left empty.
    """
    combined = {**config_vars, **fields}
    try:
        return template.format_map(combined)
    except KeyError:
        formatter = string.Formatter()
        result: list[str] = []
        for literal, field_name, _, _ in formatter.parse(template):
            result.append(literal)
            if field_name is not None:
                result.append(combined.get(field_name, ""))
        return "".join(result)


def extract_tier(value: Any, tier_labels: dict[str, str]) -> str:
    """Extract display tier from a field value.

    If value is a list, find the first item matching a tier_labels key.
    If value is a string, look it up directly.
    Unmatched → 'other'.
    """
    if isinstance(value, list):
        for item in value:
            item_str = str(item)
            if item_str in tier_labels:
                return tier_labels[item_str]
        return "other"
    if isinstance(value, str):
        return tier_labels.get(value, value or "other")
    return "other"
