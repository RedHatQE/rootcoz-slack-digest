"""Shared helpers used across formatting modules."""

from __future__ import annotations


def version_sort_key(version: str) -> tuple[int, ...]:
    """Parse version string into comparable tuple. Handles v4.22.6.rhel9-9."""
    if not version:
        return (0,)
    cleaned = version.lstrip("v")
    parts: list[int] = []
    for part in cleaned.split("."):
        # Handle parts like "rhel9-9" by extracting leading digits
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        try:
            parts.append(int(digits) if digits else 0)
        except ValueError:
            parts.append(0)
    return tuple(parts)
