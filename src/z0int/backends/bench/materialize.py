"""Materialize z0int.backends_bench.row.v1 rows from Tokenomics events.

Architecture invariant
----------------------
Benchmark persistence is **event-sourced**:

- ``tokenomics-events.jsonl`` is the ONLY canonical raw measurement source.
- ``raw.jsonl`` is a materialized compatibility view derived from those events.
- Do not construct analytics rows in parallel with event emission.

A future contributor should have difficulty accidentally reintroducing a
parallel analytics path — all persisted row fields must flow through
``materialize_row`` / ``materialize_trace``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from tokenomics import TokenomicsEvent
from tokenomics.jsonl import iter_jsonl

from .contract import BENCH_CONTRACT


def _attr(event: TokenomicsEvent, key: str, default: Any = None) -> Any:
    return (event.attributes or {}).get(key, default)


def _extra(event: TokenomicsEvent, key: str, default: Any = None) -> Any:
    return (event.extra or {}).get(key, default)


def _events_by_trace(events: Iterable[TokenomicsEvent]) -> dict[str, list[TokenomicsEvent]]:
    grouped: dict[str, list[TokenomicsEvent]] = {}
    for ev in events:
        grouped.setdefault(ev.trace_id, []).append(ev)
    return grouped


def _find(events: list[TokenomicsEvent], kind: str) -> TokenomicsEvent | None:
    for ev in events:
        if ev.kind == kind:
            return ev
    return None


def events_for_trace(events: Iterable[TokenomicsEvent], trace_id: str) -> list[TokenomicsEvent]:
    return [ev for ev in events if ev.trace_id == trace_id]


def materialize_row(events: list[TokenomicsEvent]) -> dict[str, Any]:
    task = _find(events, "task")
    decision = _find(events, "decision")
    verification = _find(events, "verification")
    if task is None or decision is None:
        raise ValueError("trace missing task or decision event")

    bench_status = _attr(decision, "benchmark.status") or _extra(decision, "benchmark.status")
    candidate_id = str(
        _attr(decision, "backend.candidate_id")
        or (decision.model.name if decision.model else "")
        or _attr(task, "backend.candidate_id")
        or ""
    )
    base = {
        "schema": "z0int.backends_bench.row.v1",
        "contract": str(_attr(task, "benchmark.contract") or BENCH_CONTRACT),
        "candidate_id": candidate_id,
        "capability": str(task.capability_id or ""),
        "fixture_id": str(task.task_id or _attr(task, "benchmark.fixture_id") or ""),
        "provenance": str(_attr(task, "benchmark.provenance") or "z0int.fixtures.v1"),
        "commercial_use": _extra(task, "backend.commercial_use"),
        "platforms": list(_extra(task, "backend.platforms") or []),
        "backend_impl": _extra(task, "backend.backend_impl"),
        "device": _extra(decision, "resource.device") or _extra(task, "resource.device"),
        "input_bytes": int(_attr(task, "benchmark.input_bytes") or 0),
    }

    if bench_status == "unavailable" or decision.status == "unknown":
        return {
            **base,
            "status": "unavailable",
            "reason": str(_extra(decision, "benchmark.unavailable_reason") or "unavailable"),
        }

    if decision.status == "error" or bench_status == "error":
        err_class = _attr(decision, "benchmark.error_class")
        err_reason = _extra(decision, "benchmark.error_reason")
        if err_class and err_reason:
            reason = f"{err_class}: {err_reason}"
        else:
            reason = str(err_reason or err_class or "error")
        return {
            **base,
            "status": "error",
            "reason": reason,
            "latency_ms": None,
        }

    gold = str(_attr(verification, "decision.gold") if verification else "")
    prediction = str(_extra(verification, "decision.prediction") or _attr(decision, "decision.prediction") or "")
    brier = _extra(verification, "decision.brier") if verification else None
    abstention_correct = _extra(verification, "decision.abstention_correct") if verification else None
    latency_ms = decision.latency.duration_ms if decision.latency else None
    startup_ms = _attr(decision, "resource.startup_ms")
    startup_ms = float(startup_ms) if startup_ms is not None else None
    ram_mb = _attr(decision, "resource.rss_peak_mb")
    vram_mb = _attr(decision, "resource.vram_peak_mb")

    row = {
        **base,
        "status": "ok",
        "prediction": prediction,
        "gold": gold,
        "latency_ms": latency_ms,
        "startup_ms": startup_ms,
        "ram_mb": float(ram_mb) if ram_mb is not None else None,
        "vram_mb": float(vram_mb) if vram_mb is not None else None,
        "energy": "unavailable",
        "energy_reason": "no platform energy counter wired",
        "verified_correct": bool(_attr(verification, "decision.correct")) if verification else None,
        "brier": float(brier) if brier is not None else None,
        "abstention_correct": abstention_correct,
        "dangerous_false": bool(_attr(verification, "decision.dangerous_false")) if verification else False,
        "result": _extra(decision, "result"),
    }
    return row


def materialize_trace(events: Iterable[TokenomicsEvent], trace_id: str) -> dict[str, Any]:
    """Materialize one compatibility row from an in-memory (or loaded) event stream."""
    return materialize_row(events_for_trace(events, trace_id))


def materialize_rows(events: Iterable[TokenomicsEvent]) -> list[dict[str, Any]]:
    rows = []
    for _trace_id, trace_events in sorted(_events_by_trace(events).items()):
        try:
            rows.append(materialize_row(trace_events))
        except ValueError:
            continue
    rows.sort(key=lambda r: (r.get("candidate_id", ""), r.get("fixture_id", "")))
    return rows


def load_materialized_rows(path: str | Path) -> list[dict[str, Any]]:
    return materialize_rows(iter_jsonl(path))


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    skip = {"result"}
    out: dict[str, Any] = {}
    for k, v in sorted(row.items()):
        if k in skip:
            continue
        if isinstance(v, float) and v is not None and not math.isfinite(v):
            out[k] = None
        else:
            out[k] = v
    return out


SEMANTIC_FIELDS = (
    "candidate_id",
    "fixture_id",
    "capability",
    "status",
    "prediction",
    "gold",
    "verified_correct",
    "dangerous_false",
    "brier",
    "abstention_correct",
    "reason",
)


def compare_rows(
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    *,
    float_tol: float = 1e-2,
    fields: tuple[str, ...] | None = None,
) -> list[str]:
    """Compare materialized compatibility rows.

    When ``fields`` is set, only those keys are compared (golden semantic parity).
    Timestamps / event IDs / trace IDs are never part of row payloads and are ignored.
    """
    errors: list[str] = []
    old_keyed = {(r["candidate_id"], r["fixture_id"]): r for r in old_rows}
    new_keyed = {(r["candidate_id"], r["fixture_id"]): r for r in new_rows}
    if set(old_keyed) != set(new_keyed):
        errors.append(f"key mismatch old={len(old_keyed)} new={len(new_keyed)}")
        errors.append(f"missing in new: {sorted(set(old_keyed) - set(new_keyed))[:5]}")
        errors.append(f"extra in new: {sorted(set(new_keyed) - set(old_keyed))[:5]}")
    for key in sorted(set(old_keyed) & set(new_keyed)):
        o = _normalize_row(old_keyed[key])
        n = _normalize_row(new_keyed[key])
        check_fields = fields if fields is not None else tuple(sorted(set(o) | set(n)))
        for field in check_fields:
            ov, nv = o.get(field), n.get(field)
            if ov == nv:
                continue
            if isinstance(ov, (int, float)) and isinstance(nv, (int, float)) and ov is not None and nv is not None:
                if abs(float(ov) - float(nv)) <= float_tol:
                    continue
            errors.append(f"{key} {field}: old={ov!r} new={nv!r}")
    return errors
