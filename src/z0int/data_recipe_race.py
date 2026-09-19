"""Ordinary vs contrastive data-recipe evaluation (probe/architecture fixed)."""

from __future__ import annotations

from typing import Any

from z0int.contrastive_evidence import (
    ContrastFamily,
    ProbeFn,
    aggregate_family_metrics,
    evaluate_family,
    evaluate_recipe_on_family,
    resolve_probe,
)


def ordinary_gate(eval_result: dict[str, Any]) -> bool:
    cond = (eval_result.get("conditions") or {}).get("original") or {}
    return bool(cond.get("ok"))


def contrastive_gate(eval_result: dict[str, Any]) -> bool:
    return bool(eval_result.get("full_pass"))


def race_data_recipes(
    families: list[ContrastFamily],
    *,
    probe: ProbeFn | None = None,
    recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ordinary_pass: list[dict[str, Any]] = []
    contrastive_pass: list[dict[str, Any]] = []
    all_results: list[dict[str, Any]] = []

    for fam in families:
        fn = probe or resolve_probe(fam)
        ev = evaluate_recipe_on_family(fam, recipe) if recipe else evaluate_family(fam, probe=fn)
        all_results.append(ev)
        if ordinary_gate(ev):
            ordinary_pass.append(ev)
        if contrastive_gate(ev):
            contrastive_pass.append(ev)

    n = max(len(families), 1)
    return {
        "schema": "z0int.data_recipe_race.v1",
        "n_families": len(families),
        "ordinary": {
            "acceptance_rate": len(ordinary_pass) / n,
            "accepted": len(ordinary_pass),
            "metrics": aggregate_family_metrics(ordinary_pass),
        },
        "contrastive": {
            "acceptance_rate": len(contrastive_pass) / n,
            "accepted": len(contrastive_pass),
            "metrics": aggregate_family_metrics(contrastive_pass),
        },
        "incremental_rejection": len(ordinary_pass) - len(contrastive_pass),
        "families": [r["family_id"] for r in all_results],
    }
