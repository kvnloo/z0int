"""P0 research → candidate → frozen bench → Tokenomics → ABAB update."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..resources import ResourceClass, can_run
from .convert import proposal_to_fly_candidate
from .driver import ResearchDriverResult, get_driver
from .job import create_research_job
from .proposal import ResearchProposalV1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _emit_research_event(
    *,
    job_id: str,
    proposal_id: str | None,
    status: str,
    duration_ms: float,
    model: str | None,
    effort: str | None,
    driver: str,
    usage: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    from z0int.tokenomics_emit import emit_raw

    row: dict[str, Any] = {
        "schema": "z0int.research_task.v1",
        "kind": "decision",
        "name": "research.propose",
        "capability_id": "research.propose",
        "harness": "z0int",
        "service": "agy" if driver == "agy" else driver,
        "role": "router",
        "status": status,
        "trace_id": uuid.uuid4().hex,
        "job_id": job_id,
        "proposal_id": proposal_id,
        "duration_ms": duration_ms,
        "selection_policy": "research",
        # Pass through provider-reported usage only; never invent cost or token-savings credit.
        "usage": usage,
        "cost_usd": None,
        "estimated_tokens_avoided": None,
        "measured_tokens_avoided": None,
        "model": model,
        "effort": effort,
        "ts": time.time(),
    }
    if extra:
        row["extra"] = extra
    emit_raw(row)


def _emit_experiment_link(
    *,
    proposal_id: str,
    candidate_id: str,
    experiment_id: str,
    verdict: str,
    metrics: dict[str, Any],
    gates_pass: bool,
) -> None:
    from z0int.tokenomics_emit import emit_raw

    emit_raw(
        {
            "schema": "z0int.research_experiment.v1",
            "kind": "verification",
            "name": "research.candidate_bench",
            "capability_id": "research.propose",
            "harness": "evolution_lab",
            "service": "fly_bench",
            "status": "ok" if gates_pass else "error",
            "trace_id": uuid.uuid4().hex,
            "proposal_id": proposal_id,
            "candidate_id": candidate_id,
            "experiment_id": experiment_id,
            "verdict": verdict,
            "outcome": {
                "verified_success": gates_pass and verdict == "keep",
                "verification_source": "evolution_lab.bench",
            },
            "metrics": metrics,
            "ts": time.time(),
        }
    )


def _active_omp_worktree() -> Path | None:
    """Best-effort detect user's active OMP worktree; never mutate it."""
    markers = [
        os.environ.get("OMP_WORKTREE"),
        os.environ.get("CURSOR_WORKTREE"),
    ]
    for m in markers:
        if m:
            p = Path(m)
            if p.is_dir():
                return p
    # common oh-my-pi coding-agent path — treat as forbidden mutation target
    candidate = Path.home() / ".omp"  # not a worktree, but check env only
    return None


def run_research_once(
    *,
    driver_name: str = "agy",
    evolution_lab_root: Path | None = None,
    jobs_root: Path | None = None,
    candidate_worktree_root: Path | None = None,
    force_resources: bool = False,
    skip_unit_tests: bool = True,
    max_experiments_note: str = "p0_single",
) -> dict[str, Any]:
    """One bounded: gaps → job → propose → validate → train/bench → KEEP/REJECT → ABAB."""
    el_root = Path(
        evolution_lab_root
        or os.environ.get("EVOLUTION_LAB_ROOT")
        or "/home/kvn/tmp/evolution-lab-agy"
    )
    jobs_root = Path(jobs_root or el_root)
    cand_root = Path(
        candidate_worktree_root
        or os.environ.get("AR_CANDIDATES_ROOT")
        or "/home/kvn/tmp/ar-candidates"
    )

    omp_wt = _active_omp_worktree()
    if omp_wt is not None and el_root.resolve() == omp_wt.resolve():
        raise RuntimeError(f"refusing to run autoresearch inside active OMP worktree: {omp_wt}")

    research_gate = can_run(ResourceClass.RESEARCH_REMOTE)
    if not force_resources and research_gate.get("pause"):
        return {
            "ok": False,
            "stage": "resource_gate",
            "resource_class": "research_remote",
            "gate": research_gate,
        }

    import sys

    if str(el_root) not in sys.path:
        sys.path.insert(0, str(el_root))

    from evolution_lab.abab_meta import load_or_seed, world_path
    from evolution_lab.abab_state import Evidence, Experiment, apply_mutation, save
    from evolution_lab.autoresearch_propose import default_champion_candidate
    from evolution_lab.bench import run_fly_bench
    from evolution_lab.select import decide_status, load_champion, load_config, save_champion

    cfg = load_config(el_root / "autoresearch" / "config.json")
    search_space = cfg.get("search_space") or {}
    league = el_root / "runs" / "autoresearch" / "league"
    league.mkdir(parents=True, exist_ok=True)

    frozen_before = {
        "bench.py": _sha256(el_root / "evolution_lab" / "bench.py"),
        "select.py": _sha256(el_root / "evolution_lab" / "select.py"),
    }

    tag_dir = el_root / "runs" / "autoresearch" / "agy-p0"
    tag_dir.mkdir(parents=True, exist_ok=True)
    champion_result = load_champion(tag_dir)
    if champion_result is None:
        cand = default_champion_candidate()
        champion_blob = {"candidate": cand.to_dict(), "latency_score": None, "status": "seed"}
        champion_knobs = {
            "hidden": cand.genome["architecture"]["hidden"],
            "dagger_rounds": cand.dagger_rounds,
            "plasticity_lr": cand.plasticity_lr,
            "plasticity_epochs": cand.plasticity_epochs,
            "k_winners": cand.k_winners,
            "seed": cand.genome["training"]["seed"],
        }
        champion_obj = None
    else:
        champion_blob = champion_result.to_dict()
        c = champion_result.candidate
        champion_knobs = {
            "hidden": c.genome["architecture"]["hidden"],
            "dagger_rounds": c.dagger_rounds,
            "plasticity_lr": c.plasticity_lr,
            "plasticity_epochs": c.plasticity_epochs,
            "k_winners": c.k_winners,
            "seed": c.genome["training"]["seed"],
        }
        champion_obj = champion_result

    from z0int.autoresearch.measurement_gaps import top_measurement_gaps

    gaps = top_measurement_gaps(limit=12)
    world = load_or_seed(league)
    world_dict = asdict(world)

    hyps = [asdict(h) for h in (world.hypotheses or [])]

    job = create_research_job(
        root=jobs_root,
        objective=str(world.objective or "Evolve local_plasticity under PRODUCT_TARGET gates."),
        champion=champion_blob,
        measurement_gaps=gaps,
        world=world_dict,
        search_space=search_space,
        product_target=cfg.get("product_target") or {},
        objective_weights=cfg.get("objective") or {},
        abab_hypotheses=hyps,
    )

    driver = get_driver(driver_name, evolution_lab_root=el_root)
    result: ResearchDriverResult = driver.propose(
        job,
        search_space=search_space,
        champion_knobs=champion_knobs,
        timeout_s=float(os.environ.get("AGY_PRINT_TIMEOUT_S") or 900),
    )
    _emit_research_event(
        job_id=job.job_id,
        proposal_id=result.proposal.proposal_id if result.proposal else None,
        status=result.status,
        duration_ms=result.duration_ms,
        model=result.model,
        effort=result.effort,
        driver=driver_name,
        usage=result.usage,
        extra={"command": result.command, "error": result.error},
    )
    if result.status != "ok" or result.proposal is None:
        return {
            "ok": False,
            "stage": "propose",
            "job_id": job.job_id,
            "job_dir": str(job.job_dir),
            "driver": driver_name,
            "status": result.status,
            "error": result.error,
            "agy_command": result.command,
            "frozen_judge_before": frozen_before,
            "resource_research": research_gate,
        }

    proposal: ResearchProposalV1 = result.proposal
    cand_dir = cand_root / job.job_id
    cand_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(job.path("proposal.json"), cand_dir / "proposal.json")

    bench_gate = can_run(ResourceClass.GPU_BENCHMARK)
    if not force_resources and bench_gate.get("pause"):
        # Opportunistic: record pause but still allow forced P0 serial run via force_resources.
        # Without force, defer GPU bench.
        out = {
            "ok": False,
            "stage": "gpu_benchmark_paused",
            "job_id": job.job_id,
            "job_dir": str(job.job_dir),
            "proposal": proposal.to_dict(),
            "agy_command": result.command,
            "resource_research": research_gate,
            "resource_gpu_benchmark": bench_gate,
            "frozen_judge_before": frozen_before,
            "note": "research completed; GPU bench deferred under contention",
        }
        job.path("result.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
        return out

    fly = proposal_to_fly_candidate(
        proposal,
        champion=champion_blob.get("candidate") or champion_blob,
        evolution_lab_root=el_root,
    )
    (cand_dir / "candidate.json").write_text(json.dumps(fly.to_dict(), indent=2) + "\n", encoding="utf-8")

    experiment_id = f"agy-{proposal.proposal_id}"
    t_bench = time.perf_counter()
    bench = run_fly_bench(
        fly,
        config=cfg,
        run_dir=tag_dir,
        experiment_id=experiment_id,
        skip_unit_tests=skip_unit_tests,
    )
    bench_ms = (time.perf_counter() - t_bench) * 1000.0
    if champion_obj is not None:
        bench.status = decide_status(bench, champion_obj, cfg)
    else:
        # First champion: keep only if gates pass (establish baseline).
        bench.status = "keep" if bench.gates_pass else "discard"

    champion_before = load_champion(tag_dir)
    if bench.status == "keep":
        save_champion(tag_dir, bench)
    champion_after = load_champion(tag_dir)

    # ABAB update for both keep and discard (measurement evidence).
    try:
        hyp_id = world.hypotheses[0].id if world.hypotheses else "H1"
        outcome = "keep" if bench.status == "keep" else "revert"
        world = apply_mutation(
            world,
            "SPAWN_EXPERIMENT",
            {
                "experiment": Experiment(
                    id=experiment_id,
                    hypothesis_id=hyp_id,
                    intervention=json.dumps(proposal.target, sort_keys=True),
                    baseline="champion",
                    prediction=f"{proposal.expected_metric} {proposal.expected_direction}",
                    metric="latency_score",
                    outcome=outcome,
                    measured={
                        "latency_score": bench.latency_score,
                        "gates_pass": bench.gates_pass,
                        "status": bench.status,
                        "proposal_id": proposal.proposal_id,
                    },
                )
            },
        )
        world = apply_mutation(
            world,
            "ADD",
            {
                "evidence": Evidence(
                    id=f"E-{proposal.proposal_id}",
                    claim=proposal.hypothesis[:240],
                    source="agy_research_p0",
                    source_class="measurement",
                    confidence=0.8 if bench.status == "keep" else 0.35,
                    counter=bench.status != "keep",
                )
            },
        )
        save(world, world_path(league))
    except Exception as exc:  # noqa: BLE001
        job.path("abab_update_error.txt").write_text(str(exc), encoding="utf-8")

    _emit_experiment_link(
        proposal_id=proposal.proposal_id,
        candidate_id=fly.genome_id,
        experiment_id=experiment_id,
        verdict=bench.status,
        metrics=bench.metrics.to_dict(),
        gates_pass=bench.gates_pass,
    )

    frozen_after = {
        "bench.py": _sha256(el_root / "evolution_lab" / "bench.py"),
        "select.py": _sha256(el_root / "evolution_lab" / "select.py"),
    }
    out = {
        "ok": True,
        "stage": "complete",
        "job_id": job.job_id,
        "job_dir": str(job.job_dir),
        "candidate_dir": str(cand_dir),
        "driver": driver_name,
        "agy_command": result.command,
        "proposal": proposal.to_dict(),
        "candidate": fly.to_dict(),
        "experiment_id": experiment_id,
        "verdict": bench.status,
        "gates_pass": bench.gates_pass,
        "gate_reasons": bench.gate_reasons,
        "latency_score": bench.latency_score,
        "metrics": bench.metrics.to_dict(),
        "bench_wall_ms": bench_ms,
        "research_duration_ms": result.duration_ms,
        "resource_research": research_gate,
        "resource_gpu_benchmark": bench_gate,
        "frozen_judge_before": frozen_before,
        "frozen_judge_after": frozen_after,
        "frozen_judge_unchanged": frozen_before == frozen_after,
        "champion_changed": (
            (champion_before.experiment_id if champion_before else None)
            != (champion_after.experiment_id if champion_after else None)
        ),
        "note": max_experiments_note,
    }
    job.path("result.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    return out
