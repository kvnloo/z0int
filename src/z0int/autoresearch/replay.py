"""Replay arms for context-policy ABAB.

V0 does not re-execute the full agent turn. It evaluates whether a challenger
context policy is non-inferior on a frozen task snapshot + verifier identity.
"""

from __future__ import annotations

import time
from typing import Any

from .mutations import champion_policy, challenger_policies, treatment_hash
from .queue import record_arm
from .schema import ReplayResult
from . import store

def _unwrap_payload(job: dict[str, Any]) -> dict[str, Any]:
    """Jobs store enqueue body as payload; snapshot/kind may be nested one level."""
    body = job.get("payload") or {}
    if not isinstance(body, dict):
        return {}
    inner = body.get("payload")
    if isinstance(inner, dict) and (
        "snapshot" in inner
        or "kind" in inner
        or "family" in inner
        or "recipe_champion" in inner
        or "recipe_challenger" in inner
    ):
        merged = dict(body)
        merged.update(inner)
        return merged
    return body



def _simulate_context_cost(policy: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Deterministic cost model from policy ops (no network)."""
    ops = list(policy.get("ops") or [])
    base_ms = int(snapshot.get("baseline_wall_ms") or 1000)
    per = {
        "exact_path": 20,
        "lexical_local": 80,
        "qmd_lexical": 120,
        "qmd_semantic": 400,
        "cached_packet": 5,
    }
    ctx_ms = sum(per.get(o, 50) for o in ops)
    # ablation of successful items may fail verification if required evidence missing
    required = set(snapshot.get("required_ops") or ["exact_path"])
    have = set(ops)
    ablate = set(policy.get("ablate") or [])
    # if we ablated a required op and don't have cached_packet covering it → fail
    verified = True
    if required - have and "cached_packet" not in have:
        verified = False
    if snapshot.get("force_fail_ops"):
        if set(snapshot["force_fail_ops"]) & ablate:
            verified = False
    wall = base_ms + ctx_ms
    tokens = int(snapshot.get("frontier_tokens") or 0)
    if policy.get("role") == "challenger" and verified:
        # savings: reduced context tokens
        tokens = max(0, tokens - 50 * len(ablate))
    return {
        "verified_success": verified,
        "execution_completed": True,
        "wall_ms": wall,
        "frontier_tokens": tokens,
        "cpu_ms": ctx_ms,
        "gpu_ms": 0,
    }


def run_abab_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = _unwrap_payload(job)
    snapshot = payload.get("snapshot") or {}
    verifier_id = payload.get("verifier_id") or "unknown"
    task_id = snapshot.get("task_snapshot_id") or job.get("trace_id") or "task"
    champ = champion_policy(snapshot)
    champ["treatment_hash"] = treatment_hash(champ)
    # freeze champion file
    champ_path = store.champions_dir() / f"{job['trace_id']}.json"
    if not champ_path.is_file():
        import json

        champ_path.write_text(json.dumps({"policy": champ, "frozen": True, "trace_id": job["trace_id"]}, indent=2) + "\n")
    else:
        # champion immutable — reload frozen
        import json

        frozen = json.loads(champ_path.read_text(encoding="utf-8"))
        champ = frozen.get("policy") or champ

    arms_spec = [
        ("A0", champ),
        ("B0", None),  # filled with first challenger
        ("A1", champ),
        ("B1", None),
    ]
    challengers = challenger_policies(champ)
    primary = challengers[0] if challengers else champ
    results: list[dict[str, Any]] = []

    def run_arm(name: str, policy: dict[str, Any]) -> ReplayResult:
        t0 = time.perf_counter()
        sim = _simulate_context_cost(policy, snapshot)
        wall = int((time.perf_counter() - t0) * 1000) + int(sim["wall_ms"])
        rr = ReplayResult(
            experiment_id=job["id"],
            task_snapshot_id=str(task_id),
            arm=name,  # type: ignore[arg-type]
            treatment_hash=str(policy.get("treatment_hash") or treatment_hash(policy)),
            execution_completed=bool(sim["execution_completed"]),
            verified_success=sim["verified_success"],
            verifier_id=verifier_id,
            wall_ms=wall,
            frontier_tokens=int(sim["frontier_tokens"]),
            gpu_ms=int(sim["gpu_ms"]),
            cpu_ms=int(sim["cpu_ms"]),
        )
        rec = record_arm(job["id"], name, rr.treatment_hash, status="done", result=rr.to_dict())
        row = rr.to_dict()
        row["arm_record"] = rec
        row["trace_id"] = job.get("trace_id")
        store.append_result(row)
        results.append(row)
        return rr

    a0 = run_arm("A0", champ)
    b0 = run_arm("B0", primary)
    a1 = run_arm("A1", champ)
    b1 = run_arm("B1", primary)

    # KEEP if challenger non-inferior quality and better primary metric
    decision = "NO_UPDATE"
    if (
        a0.verified_success is True
        and a1.verified_success is True
        and b0.verified_success is True
        and b1.verified_success is True
    ):
        champ_ms = (a0.wall_ms + a1.wall_ms) / 2
        chal_ms = (b0.wall_ms + b1.wall_ms) / 2
        if chal_ms + 1e-6 < champ_ms:
            decision = "KEEP_CHALLENGER_CANDIDATE"  # still not auto-promote
        else:
            decision = "REJECT_CHALLENGER"
    elif b0.verified_success is False or b1.verified_success is False:
        decision = "REJECT_CHALLENGER"
        # retain negative evidence already in results.jsonl
    else:
        decision = "NO_UPDATE"

    return {
        "ok": True,
        "job_id": job["id"],
        "trace_id": job["trace_id"],
        "decision": decision,
        "champion_hash": champ.get("treatment_hash"),
        "challenger_hash": primary.get("treatment_hash"),
        "arms": results,
        "verifier_id": verifier_id,
    }


def run_contrastive_job(job: dict[str, Any]) -> dict[str, Any]:
    """Contrastive evidence-sufficiency arm (one mutation axis: evidence filter).

    Payload:
      family: ContrastFamily dict OR omit to use built-in fixture
      recipe_champion / recipe_challenger: keep/drop evidence recipes
    Does not claim verified_success for production — records pair_pass only.
    """
    import json

    from z0int.contrastive_evidence import (
        ContrastFamily,
        evaluate_recipe_on_family,
        example_project_status_family,
        store_dependency,
    )
    from z0int.autoresearch.mutations import treatment_hash

    payload = _unwrap_payload(job)
    if payload.get("family"):
        family = ContrastFamily.from_dict(payload["family"])
    else:
        family = example_project_status_family()

    champ_recipe = dict(payload.get("recipe_champion") or {"keep_necessary_only": False})
    chal_recipe = dict(
        payload.get("recipe_challenger")
        or {
            # cheaper: drop stale summary + unrelated chat
            "drop_evidence_ids": ["old_summary", "unrelated_chat"],
        }
    )
    champ_recipe.setdefault("role", "champion")
    chal_recipe.setdefault("role", "challenger")
    champ_recipe["treatment_hash"] = treatment_hash(champ_recipe)
    chal_recipe["treatment_hash"] = treatment_hash(chal_recipe)

    champ = evaluate_recipe_on_family(family, champ_recipe)
    chal = evaluate_recipe_on_family(family, chal_recipe)

    # store dependency from champion full_pass path
    dep_path = store_dependency(champ["dependency"])

    # decision: challenger must full_pass and use fewer evidence ids
    champ_n = len(champ.get("recipe_keep_ids") or [])
    chal_n = len(chal.get("recipe_keep_ids") or [])
    if chal["full_pass"] and champ["full_pass"] and chal_n <= champ_n:
        decision = "KEEP_CHEAPER_SENSITIVE_RECIPE"
    elif not chal["full_pass"]:
        decision = "REJECT_INSENSITIVE_OR_BRITTLE"
    else:
        decision = "NO_UPDATE"

    out = {
        "ok": True,
        "job_id": job.get("id"),
        "trace_id": job.get("trace_id"),
        "kind": "contrastive_evidence",
        "decision": decision,
        "family_id": family.family_id,
        "champion": {
            "treatment_hash": champ_recipe["treatment_hash"],
            "pair_pass": champ["pair_pass"],
            "full_pass": champ["full_pass"],
            "keep_ids": champ.get("recipe_keep_ids"),
            "conditions": champ["conditions"],
        },
        "challenger": {
            "treatment_hash": chal_recipe["treatment_hash"],
            "pair_pass": chal["pair_pass"],
            "full_pass": chal["full_pass"],
            "keep_ids": chal.get("recipe_keep_ids"),
            "conditions": chal["conditions"],
        },
        "dependency_path": str(dep_path),
        # explicit: not production gold
        "production_credit_eligible": False,
        "curation_accepted": bool(chal["full_pass"] and champ["full_pass"]),
    }
    store.append_result(
        {
            "schema": "z0int.replay_result.v1",
            "experiment_id": job.get("id"),
            "task_snapshot_id": family.family_id,
            "arm": "contrastive",
            "treatment_hash": chal_recipe["treatment_hash"],
            "execution_completed": True,
            "verified_success": None,  # never promote curation → verified
            "verifier_id": payload.get("verifier_id") or "contrastive_deterministic",
            "wall_ms": 0,
            "trace_id": job.get("trace_id"),
            "extra": out,
        }
    )
    return out

