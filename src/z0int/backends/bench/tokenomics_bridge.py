"""Emit canonical Tokenomics traces for decision-capability bench runs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tokenomics import (
    Experiment,
    JsonlSink,
    Latency,
    MemorySink,
    ModelRef,
    Outcome,
    Recorder,
    TokenUsage,
    TokenomicsEvent,
    new_trace_id,
)
from tokenomics.recorder import MultiSink

from .eligibility import option_count as fixture_option_count
from .fixtures import BenchExample


def _sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def dataset_hash(fixtures_path: Path) -> str:
    return _sha256_hex(fixtures_path.read_bytes())


def canonical_fixture_record(example: BenchExample) -> dict[str, Any]:
    if example.raw:
        return dict(example.raw)
    q = example.question
    qmap: dict[str, Any] = {"id": q.id, "type": q.type, "instructions": q.instructions}
    if q.type == "choice":
        qmap["options"] = [{"id": o.id, "description": o.description} for o in q.options]
    elif q.type == "boolean":
        qmap["criteria"] = {"false": q.false_criterion or "false", "true": q.true_criterion or "true"}
    else:
        qmap["criteria"] = list(q.levels)
    return {
        "id": example.id,
        "capability": example.capability,
        "provenance": example.provenance,
        "state": example.state,
        "question": qmap,
        "gold": example.gold,
        "allow_abstain": example.allow_abstain,
        "abstain_option_id": example.abstain_option_id,
    }


def task_snapshot_id(example: BenchExample) -> str:
    blob = json.dumps(canonical_fixture_record(example), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_hex(blob.encode("utf-8"))


def pair_id(fixture_id: str, *, seed: int) -> str:
    return f"{fixture_id}:seed={seed}"


def bench_treatment_hash(
    *,
    backend_id: str,
    model_revision: str | None,
    device: str | None,
    contract: str,
    dataset_sha: str,
    backend_impl: str | None,
) -> str:
    payload = {
        "backend_id": backend_id,
        "model_revision": model_revision,
        "device": device,
        "contract": contract,
        "dataset_hash": dataset_sha,
        "backend_impl": backend_impl,
        "prompt_version": "direct-options-v1",
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_hex(blob)[:16]


def _git_sha(cwd: Path) -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(cwd), text=True, stderr=subprocess.DEVNULL)
        return out.strip()[:40] or None
    except (subprocess.SubprocessError, OSError):
        return None


def tokenomics_git_sha() -> str | None:
    try:
        import tokenomics
        return _git_sha(Path(tokenomics.__file__).resolve().parents[2])
    except Exception:
        return None




def _bench_decision_attrs(
    *,
    contract: str,
    input_bytes: int,
    candidate_id: str,
    prediction: str,
    confidence: float | None,
    abstained: bool,
    startup_ms: float | None,
    ram_mb: float | None,
    vram_mb: float | None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "benchmark.contract": contract,
        "benchmark.status": "ok",
        "decision.prediction": prediction,
        "decision.confidence": float(confidence or 0.0),
        "decision.abstained": bool(abstained),
        "benchmark.input_bytes": input_bytes,
        "backend.candidate_id": candidate_id,
    }
    if startup_ms is not None:
        attrs["resource.startup_ms"] = float(startup_ms)
    if ram_mb is not None:
        attrs["resource.rss_peak_mb"] = float(ram_mb)
    if vram_mb is not None:
        attrs["resource.vram_peak_mb"] = float(vram_mb)
    return attrs


@dataclass
class BenchTokenomicsSession:
    run_id: str
    contract: str
    dataset_sha: str
    fixtures_path: Path
    seed: int
    candidates: list[str]
    recorder: Recorder
    memory: MemorySink
    events_path: Path
    z0int_git_sha: str | None = None
    tokenomics_git_sha: str | None = None

    @classmethod
    def open(
        cls,
        *,
        run_id: str,
        contract: str,
        fixtures_path: Path,
        seed: int,
        candidates: list[str],
        events_path: Path,
        repo_root: Path,
    ) -> "BenchTokenomicsSession":
        memory = MemorySink()
        recorder = Recorder(MultiSink(memory, JsonlSink(events_path)))
        return cls(
            run_id=run_id,
            contract=contract,
            dataset_sha=dataset_hash(fixtures_path),
            fixtures_path=fixtures_path,
            seed=seed,
            candidates=list(candidates),
            recorder=recorder,
            memory=memory,
            events_path=events_path,
            z0int_git_sha=_git_sha(repo_root),
            tokenomics_git_sha=tokenomics_git_sha(),
        )

    @property
    def experiment_id(self) -> str:
        return f"{self.contract}:{self.dataset_sha[:16]}:{self.run_id}"

    def _experiment(self, example: BenchExample, *, arm_id: str, **treatment_kw) -> Experiment:
        return Experiment(
            experiment_id=self.experiment_id,
            pair_id=pair_id(example.id, seed=self.seed),
            task_snapshot_id=task_snapshot_id(example),
            arm_id=arm_id,
            treatment_hash=bench_treatment_hash(
                backend_id=arm_id,
                model_revision=treatment_kw.get("model_revision"),
                device=treatment_kw.get("device"),
                contract=self.contract,
                dataset_sha=self.dataset_sha,
                backend_impl=treatment_kw.get("backend_impl"),
            ),
            selection_policy="benchmark",
            evaluation_cohort="offline_fixture",
            supervision_kind="deterministic",
        )

    def begin_trace(
        self,
        example: BenchExample,
        *,
        candidate_id: str,
        commercial_use: bool | None,
        platforms: tuple[str, ...],
        backend_impl: str | None,
        device: str | None,
        model_revision: str | None,
        input_bytes: int,
    ) -> tuple[str, str]:
        trace_id = new_trace_id()
        task = self.recorder.record(
            TokenomicsEvent(
                kind="task",
                name="z0int.decision_benchmark",
                trace_id=trace_id,
                task_id=example.id,
                capability_id=example.capability,
                harness="z0int",
                service="decision-bench",
                role="other",
                status="ok",
                experiment=self._experiment(
                    example,
                    arm_id=candidate_id,
                    model_revision=model_revision,
                    device=device,
                    backend_impl=backend_impl,
                ),
                attributes={
                    "benchmark.contract": self.contract,
                    "benchmark.seed": self.seed,
                    "benchmark.fixture_id": example.id,
                    "benchmark.provenance": example.provenance,
                    "benchmark.dataset_hash": self.dataset_sha,
                    "benchmark.option_count": fixture_option_count(example),
                    "benchmark.input_bytes": input_bytes,
                    "backend.candidate_id": candidate_id,
                },
                extra={
                    "backend.platforms": list(platforms),
                    "backend.backend_impl": backend_impl,
                    "backend.commercial_use": commercial_use,
                    "resource.device": device,
                },
            )
        )
        return trace_id, task.span_id

    def emit_unavailable(
        self,
        *,
        trace_id: str,
        task_span_id: str,
        example: BenchExample,
        candidate_id: str,
        reason: str,
        commercial_use: bool | None,
        platforms: tuple[str, ...],
        backend_impl: str | None,
    ) -> None:
        self.recorder.record(
            TokenomicsEvent(
                kind="decision",
                name="z0int.backend_decision",
                trace_id=trace_id,
                parent_span_id=task_span_id,
                task_id=example.id,
                capability_id=example.capability,
                harness="z0int",
                service="decision-bench",
                role="router",
                status="unknown",
                model=ModelRef(provider="local", name=candidate_id),
                experiment=self._experiment(example, arm_id=candidate_id, backend_impl=backend_impl),
                attributes={
                    "benchmark.contract": self.contract,
                    "benchmark.status": "unavailable",
                    "backend.candidate_id": candidate_id,
                },
                extra={
                    "benchmark.unavailable_reason": reason[:2000],
                    "backend.platforms": list(platforms),
                    "backend.backend_impl": backend_impl,
                    "backend.commercial_use": commercial_use,
                },
            )
        )

    def emit_error(
        self,
        *,
        trace_id: str,
        task_span_id: str,
        example: BenchExample,
        candidate_id: str,
        error_class: str,
        reason: str,
        commercial_use: bool | None,
        platforms: tuple[str, ...],
        backend_impl: str | None,
        device: str | None,
    ) -> None:
        self.recorder.record(
            TokenomicsEvent(
                kind="decision",
                name="z0int.backend_decision",
                trace_id=trace_id,
                parent_span_id=task_span_id,
                task_id=example.id,
                capability_id=example.capability,
                harness="z0int",
                service="decision-bench",
                role="router",
                status="error",
                model=ModelRef(provider="local", name=candidate_id),
                experiment=self._experiment(example, arm_id=candidate_id, device=device, backend_impl=backend_impl),
                attributes={
                    "benchmark.contract": self.contract,
                    "benchmark.status": "error",
                    "benchmark.error_class": error_class[:120],
                    "backend.candidate_id": candidate_id,
                },
                extra={
                    "benchmark.error_reason": reason[:2000],
                    "backend.platforms": list(platforms),
                    "backend.backend_impl": backend_impl,
                    "backend.commercial_use": commercial_use,
                    "resource.device": device,
                },
            )
        )

    def emit_success(
        self,
        *,
        trace_id: str,
        task_span_id: str,
        example: BenchExample,
        candidate_id: str,
        commercial_use: bool | None,
        platforms: tuple[str, ...],
        backend_impl: str | None,
        device: str | None,
        model_revision: str | None,
        input_bytes: int,
        latency_ms: float,
        startup_ms: float | None,
        ram_mb: float | None,
        vram_mb: float | None,
        prediction: str,
        confidence: float | None,
        abstained: bool,
        scored: dict[str, Any],
        result_dict: dict[str, Any],
        input_tokens: int | None,
    ) -> None:
        usage = None
        if input_tokens is not None:
            usage = TokenUsage(input_tokens=int(input_tokens), output_tokens=0, source="derived")
        decision = self.recorder.record(
            TokenomicsEvent(
                kind="decision",
                name="z0int.backend_decision",
                trace_id=trace_id,
                parent_span_id=task_span_id,
                task_id=example.id,
                capability_id=example.capability,
                harness="z0int",
                service="decision-bench",
                role="router",
                status="ok",
                model=ModelRef(provider="local", name=candidate_id, revision=model_revision),
                usage=usage,
                latency=Latency(duration_ms=float(latency_ms)),
                experiment=self._experiment(
                    example,
                    arm_id=candidate_id,
                    model_revision=model_revision,
                    device=device,
                    backend_impl=backend_impl,
                ),
                attributes=_bench_decision_attrs(
                    contract=self.contract,
                    input_bytes=input_bytes,
                    candidate_id=candidate_id,
                    prediction=prediction,
                    confidence=confidence,
                    abstained=abstained,
                    startup_ms=startup_ms,
                    ram_mb=ram_mb,
                    vram_mb=vram_mb,
                ),
                extra={
                    "backend.platforms": list(platforms),
                    "backend.backend_impl": backend_impl,
                    "backend.commercial_use": commercial_use,
                    "resource.device": device,
                    "result": result_dict,
                },
            )
        )
        self.recorder.record(
            TokenomicsEvent(
                kind="verification",
                name="decision_capability_gold",
                trace_id=trace_id,
                parent_span_id=decision.span_id,
                task_id=example.id,
                capability_id=example.capability,
                harness="z0int",
                service="decision-bench",
                role="verifier",
                status="ok",
                outcome=Outcome(
                    verified_success=bool(scored.get("verified_correct")),
                    verifier_ok=bool(scored.get("verified_correct")),
                    verification_source=self.contract,
                    source="z0int_benchmark",
                ),
                experiment=self._experiment(
                    example,
                    arm_id=candidate_id,
                    model_revision=model_revision,
                    device=device,
                    backend_impl=backend_impl,
                ),
                attributes={
                    "decision.gold": example.gold,
                    "decision.correct": bool(scored.get("verified_correct")),
                    "decision.dangerous_false": bool(scored.get("dangerous_false")),
                },
                extra={
                    "decision.brier": scored.get("brier"),
                    "decision.abstention_correct": scored.get("abstention_correct"),
                    "decision.prediction": prediction,
                },
            )
        )
