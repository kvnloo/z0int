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

from ..base import DecisionBackend, result_to_dict
from .analytics import (
    build_coverage_section,
    build_decision_analytics,
    build_paired_comparisons,
    render_analytics_md,
)
from tokenomics.coverage import format_coverage_text

from .contract import BENCH_CONTRACT, BENCH_SCHEMA, CAPABILITIES, ROSTER_CANDIDATES
from .fixtures import BenchExample, default_fixtures_path, load_fixtures
from .eligibility import ELIGIBILITY_SCHEMA, enrich_backend_summaries
from .materialize import compare_rows, materialize_rows
from .metrics import aggregate_rows, score_example
from .pareto import build_pareto_report, render_pareto_md
from .roster import create_backend_for_candidate, probe_candidate, roster_adapter_table
from .run_manifest import build_run_manifest, write_run_manifest
from .tokenomics_bridge import BenchTokenomicsSession


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]




def _release_gpu_between_candidates() -> None:
    """Best-effort VRAM cleanup between roster candidates in one bench process."""
    try:
        import gc

        gc.collect()
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

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


def run_candidate(
    candidate_id: str,
    examples: list[BenchExample],
    *,
    tm_session: BenchTokenomicsSession,
    backend_factory: Callable[[str], DecisionBackend] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status = probe_candidate(candidate_id)
    rows: list[dict[str, Any]] = []
    if status.status != "available":
        for ex in examples:
            trace_id, task_span = tm_session.begin_trace(
                ex,
                candidate_id=candidate_id,
                commercial_use=status.commercial_use,
                platforms=status.platforms,
                backend_impl=status.backend_impl,
                device=None,
                model_revision=None,
                input_bytes=_input_size(ex),
            )
            tm_session.emit_unavailable(
                trace_id=trace_id,
                task_span_id=task_span,
                example=ex,
                candidate_id=candidate_id,
                reason=status.reason or "unavailable",
                commercial_use=status.commercial_use,
                platforms=status.platforms,
                backend_impl=status.backend_impl,
            )
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
    device = getattr(backend, "device", None)
    model_revision = getattr(backend, "revision", None)
    for ex in examples:
        input_bytes = _input_size(ex)
        trace_id, task_span = tm_session.begin_trace(
            ex,
            candidate_id=candidate_id,
            commercial_use=status.commercial_use,
            platforms=status.platforms,
            backend_impl=status.backend_impl,
            device=str(device) if device is not None else None,
            model_revision=str(model_revision) if model_revision else None,
            input_bytes=input_bytes,
        )
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
            "device": device,
            "input_bytes": input_bytes,
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
            abstain_id = ex.abstain_option_id or "abstain"
            abstained = pred == abstain_id
            ram_mb = _ram_mb()
            vram_mb = _vram_mb()
            result_dict = result_to_dict(result)
            tm_session.emit_success(
                trace_id=trace_id,
                task_span_id=task_span,
                example=ex,
                candidate_id=candidate_id,
                commercial_use=status.commercial_use,
                platforms=status.platforms,
                backend_impl=status.backend_impl,
                device=str(device) if device is not None else None,
                model_revision=str(model_revision) if model_revision else None,
                input_bytes=input_bytes,
                latency_ms=latency_ms,
                startup_ms=startup_ms if first else None,
                ram_mb=ram_mb,
                vram_mb=vram_mb,
                prediction=pred,
                confidence=ans.get("confidence"),
                abstained=abstained,
                scored=scored,
                result_dict=result_dict,
                input_tokens=(result.diagnostics or {}).get("input_tokens"),
            )
            row = {
                **base,
                "status": "ok",
                "prediction": pred,
                "gold": ex.gold,
                "latency_ms": latency_ms,
                "startup_ms": startup_ms if first else None,
                "ram_mb": ram_mb,
                "vram_mb": vram_mb,
                "energy": "unavailable",
                "energy_reason": "no platform energy counter wired",
                **scored,
                "result": result_dict,
            }
            first = False
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            tm_session.emit_error(
                trace_id=trace_id,
                task_span_id=task_span,
                example=ex,
                candidate_id=candidate_id,
                error_class=type(exc).__name__,
                reason=str(exc),
                commercial_use=status.commercial_use,
                platforms=status.platforms,
                backend_impl=status.backend_impl,
                device=str(device) if device is not None else None,
            )
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
    seed: int = 0,
) -> dict[str, Any]:
    if contract != BENCH_CONTRACT:
        raise ValueError(f"unsupported contract {contract!r}; only {BENCH_CONTRACT}")

    started_at = datetime.now(timezone.utc)
    examples = load_fixtures(fixtures_path)
    if capability_filter:
        examples = [e for e in examples if e.capability == capability_filter]

    candidates = list(ROSTER_CANDIDATES)
    if backend_filter:
        aliases = {
            "nanojev": "nanojev_06b",
            "openjev_06b": "openjev_06b",
            "openjev_4b": "openjev_4b",
            "laya": "laya_421m",
            "decider": "decider_2b",
        }
        requested = [x.strip() for x in str(backend_filter).split(",") if x.strip()]
        candidates = []
        for raw in requested:
            bid = aliases.get(raw, raw)
            if bid not in ROSTER_CANDIDATES:
                raise ValueError(f"unknown backend candidate {raw!r}")
            if bid not in candidates:
                candidates.append(bid)

    ts = started_at.strftime("%Y%m%dT%H%M%SZ")
    out_dir = output_dir or (_results_root() / ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    fixtures_file = fixtures_path or default_fixtures_path()
    events_path = out_dir / "tokenomics-events.jsonl"
    tm_session = BenchTokenomicsSession.open(
        run_id=ts,
        contract=contract,
        fixtures_path=fixtures_file,
        seed=seed,
        candidates=candidates,
        events_path=events_path,
        repo_root=_repo_root(),
    )

    import os

    device_env = {
        k: v
        for k, v in os.environ.items()
        if k.startswith("Z0INT_") and k.endswith(("_DEVICE", "_USE_GRAPHS"))
    }

    inline_rows: list[dict[str, Any]] = []
    backend_summaries: list[dict[str, Any]] = []
    for cid in candidates:
        rows, summary = run_candidate(
            cid,
            examples,
            tm_session=tm_session,
            backend_factory=backend_factory,
        )
        inline_rows.extend(rows)
        backend_summaries.append(summary)
        _release_gpu_between_candidates()

    finished_at = datetime.now(timezone.utc)
    materialized_rows = materialize_rows(tm_session.memory.events)
    parity_errors = compare_rows(inline_rows, materialized_rows)
    all_rows = materialized_rows

    raw_path = out_dir / "raw.jsonl"
    with raw_path.open("w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    cap_list = [c for c in CAPABILITIES if not capability_filter or c == capability_filter]
    enriched_summaries = enrich_backend_summaries(
        backend_summaries,
        examples,
        cap_list,
    )
    pareto = build_pareto_report(
        contract=contract,
        capabilities=cap_list,
        backend_summaries=enriched_summaries,
        examples=examples,
    )

    analytics = build_decision_analytics(tm_session.memory.events)
    paired = build_paired_comparisons(tm_session.memory.events)
    coverage = build_coverage_section(tm_session.memory.events)
    coverage_text = format_coverage_text(coverage)

    manifest = build_run_manifest(
        repo_root=_repo_root(),
        contract=contract,
        fixtures_path=fixtures_file,
        candidates=candidates,
        run_id=ts,
        started_at=started_at,
        finished_at=finished_at,
        device_env=device_env,
    )
    write_run_manifest(out_dir / "run-manifest.json", manifest)

    summary = {
        "schema": BENCH_SCHEMA,
        "contract": contract,
        "timestamp": ts,
        "seed": seed,
        "fixtures_path": str(fixtures_file),
        "capabilities": list(CAPABILITIES),
        "candidates": candidates,
        "adapter_table": roster_adapter_table(),
        "measurement": {
            "canonical": "tokenomics-events.jsonl",
            "materialized": "raw.jsonl",
            "parity_ok": not parity_errors,
            "parity_errors": parity_errors[:20],
        },
        "eligibility": {
            "schema": ELIGIBILITY_SCHEMA,
            "competence_margin": 0.05,
            "validated_min_examples": 50,
        },
        "backends": enriched_summaries,
        "pareto": pareto,
        "aggregate": aggregate_rows(all_rows),
        "analytics": analytics,
        "paired_comparisons": paired,
        "coverage": coverage,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pareto_path = out_dir / "pareto.md"
    pareto_path.write_text(render_pareto_md(pareto) + "\n", encoding="utf-8")
    analytics_path = out_dir / "analytics.json"
    analytics_path.write_text(json.dumps(analytics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "analytics.md").write_text(
        render_analytics_md(analytics, coverage_text=coverage_text),
        encoding="utf-8",
    )
    (out_dir / "coverage.json").write_text(json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "coverage.md").write_text(coverage_text + "\n", encoding="utf-8")

    return {
        "ok": True,
        "output_dir": str(out_dir),
        "tokenomics_events": str(events_path),
        "run_manifest": str(out_dir / "run-manifest.json"),
        "raw_jsonl": str(raw_path),
        "summary_json": str(summary_path),
        "pareto_md": str(pareto_path),
        "analytics_json": str(analytics_path),
        "parity_ok": not parity_errors,
        "parity_errors": parity_errors,
        "summary": summary,
    }
