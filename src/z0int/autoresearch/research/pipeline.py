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
from .canonicalize import candidate_fingerprint, effective_candidate, fingerprints_equal
from .convert import proposal_to_fly_candidate
from .driver import ResearchDriverResult, get_driver
from .job import create_research_job
from .promotion import noop_result, paired_decide
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
    forced_proposal: ResearchProposalV1 | None = None,
    seed_league_if_missing: bool = False,
    paired_repeats: int = 2,
) -> dict[str, Any]:
    """One bounded research job with promotion-integrity gates (P0.1).

    Distinguishes:
      research_job: SUCCESS | ERROR | DEFERRED
      candidate:    NO_OP | REJECT | PROVISIONAL_KEEP | PROMOTED
    """
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
            "research_job": "DEFERRED",
            "candidate": None,
            "resource_class": "research_remote",
            "gate": research_gate,
        }

    import sys

    if str(el_root) not in sys.path:
        sys.path.insert(0, str(el_root))

    from evolution_lab.abab_meta import load_or_seed, world_path
    from evolution_lab.abab_state import Evidence, Experiment, apply_mutation, save
    from evolution_lab.autoresearch_propose import champion_from_genome, default_champion_candidate
    from evolution_lab.bench import run_fly_bench
    from evolution_lab.schema import genome_from_dict
    from evolution_lab.select import BenchResult, load_champion, load_config, save_champion
    from copy import deepcopy
    from dataclasses import replace as dc_replace

    cfg = load_config(el_root / "autoresearch" / "config.json")
    search_space = cfg.get("search_space") or {}
    league = el_root / "runs" / "autoresearch" / "league"
    league.mkdir(parents=True, exist_ok=True)
    eps = float((cfg.get("objective") or {}).get("improve_epsilon", 0.05))

    frozen_before = {
        "bench.py": _sha256(el_root / "evolution_lab" / "bench.py"),
        "select.py": _sha256(el_root / "evolution_lab" / "select.py"),
    }

    # --- Exactly one incumbent: league/champion.json ---
    champion_obj = load_champion(league)
    if champion_obj is None:
        if not seed_league_if_missing and os.environ.get("Z0INT_SEED_LEAGUE", "").strip() not in {"1", "true", "yes"}:
            return {
                "ok": False,
                "stage": "missing_league_champion",
                "research_job": "ERROR",
                "candidate": None,
                "error": (
                    "No runs/autoresearch/league/champion.json. "
                    "Pass seed_league_if_missing=True for first-ever init, "
                    "or set Z0INT_SEED_LEAGUE=1."
                ),
                "frozen_judge_before": frozen_before,
            }
        # First-ever league init from historical ABAB baseline knobs (hidden=96, dagger=3).
        base = default_champion_candidate()
        g = genome_from_dict(deepcopy(base.genome))
        g = dc_replace(
            g,
            architecture=dc_replace(g.architecture, hidden=96, history=8, k_winners=0),
            id="fly-league-seed-h96-d3",
        )
        seed_cand = champion_from_genome(
            g,
            dagger_rounds=3,
            plasticity_lr=base.plasticity_lr,
            plasticity_epochs=base.plasticity_epochs,
            k_winners=0,
            description="league-seed historical baseline hidden=96 dagger=3",
        )
        seed_bench = run_fly_bench(
            seed_cand,
            config=cfg,
            run_dir=league,
            experiment_id="league-seed-h96-d3",
            skip_unit_tests=skip_unit_tests,
        )
        seed_bench.status = "keep" if seed_bench.gates_pass else "discard"
        if not seed_bench.gates_pass:
            return {
                "ok": False,
                "stage": "league_seed_failed_gates",
                "research_job": "ERROR",
                "candidate": "REJECT",
                "gate_reasons": seed_bench.gate_reasons,
                "latency_score": seed_bench.latency_score,
                "frozen_judge_before": frozen_before,
            }
        save_champion(league, seed_bench)
        champion_obj = seed_bench

    assert champion_obj is not None
    champion_blob = champion_obj.to_dict()
    canon = effective_candidate(champion_obj.candidate)
    champion_knobs = canon.knobs_for_brief()
    incumbent_meta = {
        "incumbent_experiment_id": champion_obj.experiment_id,
        "incumbent_candidate_hash": candidate_fingerprint(champion_obj.candidate),
        "incumbent_latency_score": champion_obj.latency_score,
        "incumbent_canonical": canon.to_dict(),
        "league_champion_path": str(league / "champion.json"),
    }

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
        canonical_champion=champion_knobs,
        incumbent=incumbent_meta,
    )
    # Freeze incumbent snapshot for the job (immutable for this run).
    job.path("incumbent.json").write_text(
        json.dumps(incumbent_meta, indent=2, default=str) + "\n", encoding="utf-8"
    )

    if forced_proposal is not None:
        from .driver import ResearchDriverResult

        result = ResearchDriverResult(
            status="ok",
            proposal=forced_proposal,
            duration_ms=0.0,
            model=None,
            effort=None,
            command=["forced_proposal"],
            usage=None,
            error=None,
        )
        driver_name = "forced"
    else:
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
            "research_job": "ERROR",
            "candidate": None,
            "job_id": job.job_id,
            "job_dir": str(job.job_dir),
            "driver": driver_name,
            "status": result.status,
            "error": result.error,
            "agy_command": result.command,
            "incumbent": incumbent_meta,
            "frozen_judge_before": frozen_before,
            "resource_research": research_gate,
        }

    proposal: ResearchProposalV1 = result.proposal
    # Validate against *effective* champion knobs (catches k_winners=10 vs raw 0).
    from .proposal import validate_proposal

    try:
        proposal = validate_proposal(proposal, search_space=search_space, champion_knobs=champion_knobs)
    except Exception as exc:  # noqa: BLE001
        out = {
            "ok": True,
            "stage": "validate",
            "research_job": "SUCCESS",
            "candidate": "NO_OP" if "equals champion" in str(exc) else "REJECT",
            "verdict": "NO_OP" if "equals champion" in str(exc) else "REJECT",
            "job_id": job.job_id,
            "job_dir": str(job.job_dir),
            "proposal": proposal.to_dict(),
            "error": str(exc),
            "incumbent": incumbent_meta,
            "bench_avoided": True,
            "champion_changed": False,
            "frozen_judge_before": frozen_before,
            "frozen_judge_after": frozen_before,
            "frozen_judge_unchanged": True,
        }
        if out["candidate"] == "NO_OP":
            out["promotion"] = noop_result(reason="proposal_equals_effective_champion").__dict__
        job.path("result.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
        return out

    cand_dir = cand_root / job.job_id
    cand_dir.mkdir(parents=True, exist_ok=True)
    job.path("proposal.json").write_text(json.dumps(proposal.to_dict(), indent=2) + "\n", encoding="utf-8")
    shutil.copy2(job.path("proposal.json"), cand_dir / "proposal.json")

    fly = proposal_to_fly_candidate(
        proposal,
        champion=champion_blob.get("candidate") or champion_blob,
        evolution_lab_root=el_root,
    )
    (cand_dir / "candidate.json").write_text(json.dumps(fly.to_dict(), indent=2) + "\n", encoding="utf-8")

    # --- NO_OP short-circuit on effective fingerprint ---
    if fingerprints_equal(fly, champion_obj.candidate):
        promo = noop_result(reason="fingerprint_match")
        out = {
            "ok": True,
            "stage": "complete",
            "research_job": promo.research_job,
            "candidate": promo.candidate_verdict,
            "job_id": job.job_id,
            "job_dir": str(job.job_dir),
            "candidate_dir": str(cand_dir),
            "driver": driver_name,
            "agy_command": result.command,
            "proposal": proposal.to_dict(),
            "candidate_body": fly.to_dict(),
            "challenger_hash": candidate_fingerprint(fly),
            "incumbent": incumbent_meta,
            "promotion": promo.__dict__,
            "bench_avoided": True,
            "verdict": "NO_OP",
            "gates_pass": True,
            "latency_score": None,
            "research_duration_ms": result.duration_ms,
            "resource_research": research_gate,
            "frozen_judge_before": frozen_before,
            "frozen_judge_after": frozen_before,
            "frozen_judge_unchanged": True,
            "champion_changed": False,
            "note": max_experiments_note,
        }
        _emit_experiment_link(
            proposal_id=proposal.proposal_id,
            candidate_id=fly.genome_id,
            experiment_id=f"agy-{proposal.proposal_id}",
            verdict="NO_OP",
            metrics={},
            gates_pass=True,
        )
        job.path("result.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
        return out

    bench_gate = can_run(ResourceClass.GPU_BENCHMARK)
    if not force_resources and bench_gate.get("pause"):
        out = {
            "ok": False,
            "stage": "gpu_benchmark_paused",
            "research_job": "DEFERRED",
            "candidate": None,
            "job_id": job.job_id,
            "job_dir": str(job.job_dir),
            "proposal": proposal.to_dict(),
            "agy_command": result.command,
            "incumbent": incumbent_meta,
            "resource_research": research_gate,
            "resource_gpu_benchmark": bench_gate,
            "frozen_judge_before": frozen_before,
            "note": "research completed; GPU bench deferred under contention",
        }
        job.path("result.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
        return out

    # --- Paired A0/B0/A1/B1 under same machine conditions ---
    experiment_id = f"agy-{proposal.proposal_id}"
    tag_dir = league / "paired" / experiment_id
    tag_dir.mkdir(parents=True, exist_ok=True)
    repeats = max(1, int(paired_repeats))
    incumbent_scores: list[float] = []
    challenger_scores: list[float] = []
    challenger_benches: list[BenchResult] = []
    arm_rows: list[dict[str, Any]] = []
    t_bench = time.perf_counter()
    for i in range(repeats):
        # A: incumbent
        a = run_fly_bench(
            champion_obj.candidate,
            config=cfg,
            run_dir=tag_dir,
            experiment_id=f"{experiment_id}-A{i}",
            skip_unit_tests=skip_unit_tests,
        )
        incumbent_scores.append(float(a.latency_score))
        arm_rows.append({"arm": f"A{i}", "kind": "incumbent", "latency_score": a.latency_score, "gates_pass": a.gates_pass})
        # B: challenger
        b = run_fly_bench(
            fly,
            config=cfg,
            run_dir=tag_dir,
            experiment_id=f"{experiment_id}-B{i}",
            skip_unit_tests=skip_unit_tests,
        )
        challenger_scores.append(float(b.latency_score))
        challenger_benches.append(b)
        arm_rows.append({"arm": f"B{i}", "kind": "challenger", "latency_score": b.latency_score, "gates_pass": b.gates_pass})
    bench_ms = (time.perf_counter() - t_bench) * 1000.0

    gates_pass = all(b.gates_pass for b in challenger_benches)
    promo = paired_decide(
        incumbent_scores=incumbent_scores,
        challenger_scores=challenger_scores,
        gates_pass=gates_pass,
        improve_epsilon=eps,
        promote=True,
    )

    champion_before = load_champion(league)
    champion_changed = False
    if promo.candidate_verdict in {"PROVISIONAL_KEEP", "PROMOTED"} and challenger_benches:
        best = min(challenger_benches, key=lambda x: x.latency_score)
        best.latency_score = float(promo.challenger_mean or best.latency_score)
        best.status = "keep"
        best.experiment_id = experiment_id
        save_champion(league, best)
        promo.candidate_verdict = "PROMOTED"
        champion_changed = True

    champion_after = load_champion(league)

    # ABAB update — research evidence even on NO_OP/REJECT
    try:
        hyp_id = world.hypotheses[0].id if world.hypotheses else "H1"
        outcome = {
            "PROMOTED": "keep",
            "PROVISIONAL_KEEP": "keep",
            "REJECT": "revert",
            "NO_OP": "noop",
        }.get(promo.candidate_verdict, "revert")
        world = apply_mutation(
            world,
            "SPAWN_EXPERIMENT",
            {
                "experiment": Experiment(
                    id=experiment_id,
                    hypothesis_id=hyp_id,
                    intervention=json.dumps(proposal.target, sort_keys=True),
                    baseline="league_champion",
                    prediction=f"{proposal.expected_metric} {proposal.expected_direction}",
                    metric="latency_score",
                    outcome=outcome,
                    measured={
                        "incumbent_mean": promo.incumbent_mean,
                        "challenger_mean": promo.challenger_mean,
                        "gates_pass": gates_pass,
                        "candidate": promo.candidate_verdict,
                        "proposal_id": proposal.proposal_id,
                        "arm_scores": promo.arm_scores,
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
                    source="agy_research_p0_1",
                    source_class="measurement",
                    confidence=0.8 if promo.candidate_verdict == "PROMOTED" else 0.35,
                    counter=promo.candidate_verdict == "REJECT",
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
        verdict=promo.candidate_verdict,
        metrics=(challenger_benches[0].metrics.to_dict() if challenger_benches else {}),
        gates_pass=gates_pass,
    )

    frozen_after = {
        "bench.py": _sha256(el_root / "evolution_lab" / "bench.py"),
        "select.py": _sha256(el_root / "evolution_lab" / "select.py"),
    }
    out = {
        "ok": True,
        "stage": "complete",
        "research_job": promo.research_job,
        "candidate": promo.candidate_verdict,
        "job_id": job.job_id,
        "job_dir": str(job.job_dir),
        "candidate_dir": str(cand_dir),
        "driver": driver_name,
        "agy_command": result.command,
        "proposal": proposal.to_dict(),
        "candidate_body": fly.to_dict(),
        "challenger_hash": candidate_fingerprint(fly),
        "experiment_id": experiment_id,
        "verdict": promo.candidate_verdict,  # back-compat alias
        "gates_pass": gates_pass,
        "gate_reasons": list({r for b in challenger_benches for r in (b.gate_reasons or [])}),
        "latency_score": promo.challenger_mean,
        "incumbent_latency_score_paired": promo.incumbent_mean,
        "metrics": (challenger_benches[0].metrics.to_dict() if challenger_benches else {}),
        "paired_arms": arm_rows,
        "promotion": promo.__dict__,
        "bench_wall_ms": bench_ms,
        "bench_avoided": False,
        "research_duration_ms": result.duration_ms,
        "resource_research": research_gate,
        "resource_gpu_benchmark": bench_gate,
        "incumbent": incumbent_meta,
        "frozen_judge_before": frozen_before,
        "frozen_judge_after": frozen_after,
        "frozen_judge_unchanged": frozen_before == frozen_after,
        "champion_changed": champion_changed
        or (
            (champion_before.experiment_id if champion_before else None)
            != (champion_after.experiment_id if champion_after else None)
        ),
        "note": max_experiments_note,
    }
    job.path("result.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    return out
