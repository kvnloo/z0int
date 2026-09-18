"""Autoresearch helper: consume Tokenomics measurement-gap ranking."""

from __future__ import annotations

from typing import Any

from ..tokenomics_emit import measurement_gaps as _gaps


def top_measurement_gaps(*, range_spec: str = "7d", limit: int = 12) -> list[dict[str, Any]]:
    return _gaps(range_spec=range_spec, limit=limit)
