"""block_key rows for one record, from ``backend.core.block`` (issue #10).

The FrontDesk gate and match runs look charts up with ``CORE.block_keys`` over the stored
``normalized_record`` row. Ingest writes its rows with the same function over the same row, so an
ingested chart always shares its blocks with an intake for the same person. This module only
reshapes core's ``BlockKey`` into the table's (key_type, key_value) form.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.core.block import KEY_TYPES
from backend.core.block import block_keys as core_block_keys
from backend.core.normalize import Normalized, coerce_normalized

__all__ = ["KEY_TYPES", "block_keys"]


def block_keys(record: Normalized | Mapping[str, Any]) -> list[tuple[str, str]]:
    """(key_type, key_value) rows, sorted and unique; placeholders contribute none (core's rule).

    Accepts a ``Normalized`` or a ``normalized_record`` row, the shape the gate reads back.
    """
    return sorted({(key.key_type, key.key_value) for key in core_block_keys(coerce_normalized(record))})
