"""Run decision-capability-v1 benchmark across roster candidates."""

from __future__ import annotations

import json
import resource
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from z0int.tokenomics_emit import emit_provider_usage

from ..base import DecisionBackend, result_to_dict
from .contract import BENCH_CONTRACT, BENCH_SCHEMA, CAPABILITIES, ROSTER_CANDIDATES
from .fixtures import BenchExample, default_fixtures_path, load_fixtures
from .metrics import aggregate_rows, score_example
from .pareto import build_pareto_report, render_pareto_md
from .roster import create_backend_for_candidate, probe_candidate, roster_adapter_table


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _results_root() -> Path:
    return _repo_root() / "results" / "decision-backends"


def _ram_mb() -> float | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = usage.ru_maxrss
        if rss > 10_000_000:
            return rss / (1024 * 1024)
        return rss / 1024
    except Exception:
        return None


def _vram_mb() -> float | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
        vals = [float(x.strip()) for x in out.strip().splitlines() if x.strip()]
        return max(vals) if vals else None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _input_size(example: BenchExample) -> int:
    return len(json.dumps(example.state, ensure_ascii=False))


def _answer_dict(result, qid: str) -> dict[str, Any]:
    for a in result.answers:
        if a.question_id == qid:
            return {
                "value": a.value,
                "probabilities": dict(a.probabilities),
                "confidence": a.confidence,
            }
    return {}


def _emit_tokenomics_row(*, candidate_id: str, latency_ms: float, diagnostics: dict[str, Any]) -> None:
    usage = {
        "input_tokens": diagnostics.get("input_tokens"),
        "output_tokens": 0,
        "total_tokens": diagnostics.get("input_tokens"),
    }
    emit_provider_usage(
        harness="z0int",
        trace_id=f"bench:{candidate_id}:{int(time.time())}",
        provider="z0int",
        model=candidate_id,
        usage={k: v for k, v in usage.items() if v is not None},
        role="decision_backend",
        latency_ms=latency_ms,
        extra={"bench_contract": BENCH_CONTRACT},
    )


def run_candidate(
    candidate_id: str,
    examples: list[BenchExample],
    *,
    backend_factory: Callable[[str], DecisionBackend] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status = probe_candidate(candidate_id)
    rows: list[dict[str, Any]] = []
    if status.status != "available":
        for ex in examples:
            rows.append(
                {
                    "schema": "z0int.backends_bench.row.v1",
                    "contract": BENCH_CONTRACT,
                    "candidate_id": candidate_id,
                    "capability": ex.capability,
                    "fixture_id": ex.id,
                    "provenance": ex.provenance,
                    "status": "unavailable",
                    "reason": status.reason,
                    "commercial_use": status.commercial_use,
                    "platforms": list(status.platforms),
                    "backend_impl": status.backend_impl,
                }
            )
        summary = {
            "candidate_id": candidate_id,
            "status": status.status,
            "reason": status.reason,
            "commercial_use": status.commercial_use,
            "platforms": list(status.platforms),
            "backend_impl": status.backend_impl,
            **aggregate_rows(rows),
        }
        return rows, summary

    factory = backend_factory or create_backend_for_candidate
    backend = factory(candidate_id)
    cold_start = time.perf_counter()
    try:
        backend.health(load=True)
    except Exception:
        pass
    startup_ms = (time.perf_counter() - cold_start) * 1000.0
    first = True
    for ex in examples:
        base = {
            "schema": "z0int.backends_bench.row.v1",
            "contract": BENCH_CONTRACT,
            "candidate_id": candidate_id,
            "capability": ex.capability,
            "fixture_id": ex.id,
            "provenance": ex.provenance,
            "commercial_use": status.commercial_use,
            "platforms": list(status.platforms),
            "backend_impl": status.backend_impl,
            "device": getattr(backend, "device", None),
            "input_bytes": _input_size(ex),
        }
        try:
            t0 = time.perf_counter()
            result = backend.evaluate(ex.to_request())
            latency_ms = (time.perf_counter() - t0) * 1000.0
            ans = _answer_dict(result, ex.question.id)
            pred = str(ans.get("value"))
            if ex.question.type == "boolean":
                pred = "true" if ans.get("value") is True else "false"
            scored = score_example(ex, probabilities=ans.get("probabilities"), pred=pred)
            row = {
                **base,
                "status": "ok",
                "prediction": pred,
                "gold": ex.gold,
                "latency_ms": latency_ms,
                "startup_ms": startup_ms if first else None,
                "ram_mb": _ram_mb(),
                "vram_mb": _vram_mb(),
                "energy": "unavailable",
                "energy_reason": "no platform energy counter wired",
                **scored,
                "result": result_to_dict(result),
            }
            first = False
            try:
                _emit_tokenomics_row(
                    candidate_id=candidate_id,
                    latency_ms=latency_ms,
                    diagnostics=result.diagnostics,
                )
            except Exception:
                pass
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    **base,
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "latency_ms": None,
                }
            )
    summary = {
        "candidate_id": candidate_id,
        "status": "available",
        "commercial_use": status.commercial_use,
        "platforms": list(status.platforms),
        "backend_impl": status.backend_impl,
        **aggregate_rows(rows),
    }
    return rows, summary


def run_bench(
    *,
    contract: str = BENCH_CONTRACT,
    fixtures_path: Path | None = None,
    backend_filter: str | None = None,
    capability_filter: str | None = None,
    output_dir: Path | None = None,
    backend_factory: Callable[[str], DecisionBackend] | None = None,
) -> dict[str, Any]:
    if contract != BENCH_CONTRACT:
        raise ValueError(f"unsupported contract {contract!r}; only {BENCH_CONTRACT}")

    examples = load_fixtures(fixtures_path)
    if capability_filter:
        examples = [e for e in examples if e.capability == capability_filter]

    candidates = list(ROSTER_CANDIDATES)
    if backend_filter:
        aliases = {
            "nanojev": "nanojev_06b",
            "openjev_06b": "openjev_06b",
            "openjev_4b": "openjev_4b",
        }
        bid = aliases.get(backend_filter, backend_filter)
        candidates = [bid] if bid in ROSTER_CANDIDATES else [backend_filter]

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = output_dir or (_results_root() / ts)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    backend_summaries: list[dict[str, Any]] = []
    for cid in candidates:
        rows, summary = run_candidate(cid, examples, backend_factory=backend_factory)
        all_rows.extend(rows)
        backend_summaries.append(summary)

    raw_path = out_dir / "raw.jsonl"
    with raw_path.open("w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    pareto = build_pareto_report(
        contract=contract,
        capabilities=[c for c in CAPABILITIES if not capability_filter or c == capability_filter],
        backend_summaries=backend_summaries,
    )
    summary = {
        "schema": BENCH_SCHEMA,
        "contract": contract,
        "timestamp": ts,
        "fixtures_path": str(fixtures_path or default_fixtures_path()),
        "capabilities": list(CAPABILITIES),
        "candidates": candidates,
        "adapter_table": roster_adapter_table(),
        "backends": backend_summaries,
        "pareto": pareto,
        "aggregate": aggregate_rows(all_rows),
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pareto_path = out_dir / "pareto.md"
    pareto_path.write_text(render_pareto_md(pareto) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "output_dir": str(out_dir),
        "raw_jsonl": str(raw_path),
        "summary_json": str(summary_path),
        "pareto_md": str(pareto_path),
        "summary": summary,
    }
