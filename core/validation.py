"""Shared validation helpers for user-supplied text (names, labels)."""

from __future__ import annotations

import unicodedata


def validate_name(name: str, *, max_length: int, label: str = "Name") -> str:
    """Validate and return a cleaned user-supplied name.

    Strips surrounding whitespace, enforces a max length, and rejects control
    and bidirectional/format characters (Unicode categories ``Cc``/``Cf``, which
    includes RTL overrides and zero-width characters that can spoof how a name
    renders in Discord embeds). Raises ``ValueError`` on failure.
    """
    cleaned = name.strip()
    if not cleaned:
        raise ValueError(f"{label} cannot be empty.")
    if len(cleaned) > max_length:
        raise ValueError(f"{label} must be {max_length} characters or fewer.")
    for ch in cleaned:
        if ch != "\t" and unicodedata.category(ch) in ("Cc", "Cf"):
            raise ValueError(f"{label} contains disallowed control characters.")
    return cleaned
