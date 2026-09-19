"""Thin bridge from z0int harness seams to neutral Tokenomics events.

Append-only projection to ``~/.z0int/tokenomics/events.jsonl``.
Does not replace z0int decision receipts or Hermes/OMP counters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import paths


def events_path(root: Path | None = None) -> Path:
    layout = paths.ensure_layout(root)
    return layout["tokenomics"] / "events.jsonl"


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
        fh.write("\n")


def emit_raw(row: dict[str, Any], *, root: Path | None = None) -> Path:
    """Append a pre-shaped provider/session row (OMP/Hermes adapters consume this)."""
    p = events_path(root)
    _append_jsonl(p, row)
    return p


def emit_provider_usage(
    *,
    harness: str,
    trace_id: str | None,
    session_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    usage: dict[str, Any],
    role: str = "root",
    attribution: str = "incremental",
    cost_usd: float | None = None,
    latency_ms: float | None = None,
    extra: dict[str, Any] | None = None,
    root: Path | None = None,
) -> Path | None:
    """Best-effort emit; returns path or None when tokenomics is unavailable."""
    schema = f"{harness}.provider_usage.v0" if attribution == "incremental" else f"{harness}.session_usage.v0"
    raw: dict[str, Any] = {
        "schema": schema,
        "harness": harness,
        "trace_id": trace_id,
        "session_id": session_id,
        "provider": provider,
        "model": model,
        "role": role,
        "attribution": attribution,
        "usage": usage,
    }
    if cost_usd is not None:
        raw["cost_usd"] = cost_usd
    if latency_ms is not None:
        raw["latency_ms"] = latency_ms
    if extra:
        raw.update(extra)
    try:
        from tokenomics.emit import append_raw

        return append_raw(raw, path=events_path(root))
    except Exception:
        return emit_raw(raw, root=root)


def measurement_gaps(*, range_spec: str = "7d", limit: int = 24) -> list[dict[str, Any]]:
    """Ranked measurement gaps for autoresearchd replay planning."""
    try:
        from tokenomics.coverage import coverage_report_from_sources

        report = coverage_report_from_sources(range_spec=range_spec)
        gaps = list(report.get("measurement_gaps") or [])
        return gaps[:limit]
    except Exception:
        return []
