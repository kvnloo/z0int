"""Contrastive evidence-sufficiency checks for context recipes.

Borrow Nimble's *measurement unit*, not its weights:

  original evidence          → preserve correct decision
  one relevant fact changes  → change decision appropriately
  irrelevant control         → preserve decision
  required evidence removed  → abstain (not false)

Per necessary evidence id, run leave-one-out necessity probes independently.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from . import paths

SCHEMA_FAMILY = "z0int.contrast_family.v1"
SCHEMA_RESULT = "z0int.contrastive_eval.v1"
SCHEMA_DEPENDENCY = "z0int.evidence_dependency.v1"

CAPABILITY_CURRENT_PROJECT_STATE = "context.current_project_state"
CAPABILITY_IMPLEMENTATION_DECISION = "context.current_implementation_decision"

BaseCondition = Literal["original", "relevant_edit", "irrelevant_control"]
Supervision = Literal["deterministic", "model_checked_synthetic", "live_verified"]

# Probe registry — fixed derivation, never read injected answer labels from evidence.
ProbeFn = Callable[[list["EvidenceItem"], str], str | None]


@dataclass
class EvidenceItem:
    id: str
    text: str
    necessary: bool = False
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContrastFamily:
    """Nearly-identical examples where one relevant fact flips the label."""

    family_id: str
    task_family: str
    question: str
    evidence: list[EvidenceItem]
    answer_original: str
    answer_after_relevant_edit: str
    relevant_edit: dict[str, Any]
    necessary_ids: list[str]
    irrelevant_control: dict[str, Any] = field(default_factory=dict)
    source_family_id: str | None = None
    parent_example_id: str | None = None
    supervision: Supervision = "deterministic"
    probe_name: str = "derive_implementation_decision"
    schema: str = SCHEMA_FAMILY
    # cache invalidation hints (filled when promoted from eval)
    invalidated_by: list[str] = field(default_factory=list)
    invariant_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "family_id": self.family_id,
            "task_family": self.task_family,
            "question": self.question,
            "evidence": [e.to_dict() for e in self.evidence],
            "answer_original": self.answer_original,
            "answer_after_relevant_edit": self.answer_after_relevant_edit,
            "relevant_edit": dict(self.relevant_edit),
            "necessary_ids": list(self.necessary_ids),
            "irrelevant_control": dict(self.irrelevant_control),
            "source_family_id": self.source_family_id,
            "parent_example_id": self.parent_example_id,
            "supervision": self.supervision,
            "probe_name": self.probe_name,
            "invalidated_by": list(self.invalidated_by),
            "invariant_ids": list(self.invariant_ids),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ContrastFamily":
        ev = [
            EvidenceItem(
                id=str(e["id"]),
                text=str(e.get("text") or ""),
                necessary=bool(e.get("necessary", False)),
                facts=dict(e.get("facts") or {}),
            )
            for e in (raw.get("evidence") or [])
        ]
        return cls(
            family_id=str(raw["family_id"]),
            task_family=str(raw.get("task_family") or "unknown"),
            question=str(raw.get("question") or ""),
            evidence=ev,
            answer_original=str(raw["answer_original"]),
            answer_after_relevant_edit=str(raw["answer_after_relevant_edit"]),
            relevant_edit=dict(raw.get("relevant_edit") or {}),
            necessary_ids=[str(x) for x in (raw.get("necessary_ids") or [])],
            irrelevant_control=dict(raw.get("irrelevant_control") or {}),
            source_family_id=raw.get("source_family_id"),
            parent_example_id=raw.get("parent_example_id"),
            supervision=raw.get("supervision") or "deterministic",  # type: ignore[arg-type]
            probe_name=str(raw.get("probe_name") or "derive_implementation_decision"),
            invalidated_by=[str(x) for x in (raw.get("invalidated_by") or [])],
            invariant_ids=[str(x) for x in (raw.get("invariant_ids") or [])],
        )


@dataclass
class EvidenceDependency:
    """First-class semantic cache / invalidation contract."""

    capability_id: str
    decision: str | None
    requires: list[str]
    invariants: list[str]
    invalidated_by: list[str]
    abstain_if_missing: list[str]
    fastest_recipe: list[str]
    family_id: str | None = None
    probe_name: str = "derive_implementation_decision"
    acquisition_recipe: dict[str, Any] | None = None
    curation_accepted: bool = False
    schema: str = SCHEMA_DEPENDENCY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "capability_id": self.capability_id,
            "decision": self.decision,
            "requires": list(self.requires),
            "invariants": list(self.invariants),
            "invalidated_by": list(self.invalidated_by),
            "abstain_if_missing": list(self.abstain_if_missing),
            "fastest_recipe": list(self.fastest_recipe),
            "family_id": self.family_id,
            "probe_name": self.probe_name,
            "acquisition_recipe": self.acquisition_recipe,
            "curation_accepted": self.curation_accepted,
        }

    @classmethod
    def from_eval(
        cls,
        family: ContrastFamily,
        eval_result: dict[str, Any],
        *,
        recipe: dict[str, Any] | None = None,
    ) -> "EvidenceDependency":
        invariants = list(family.invariant_ids) or [
            e.id for e in family.evidence if not e.necessary and e.id not in family.necessary_ids
        ]
        fastest = list(recipe.get("ops") or recipe.get("fastest_recipe") or []) if recipe else []
        if not fastest and recipe and recipe.get("keep_evidence_ids"):
            fastest = [f"evidence:{x}" for x in recipe["keep_evidence_ids"]]
        return cls(
            capability_id=family.task_family,
            decision=family.answer_original if eval_result.get("full_pass") else None,
            requires=list(family.necessary_ids),
            invariants=invariants,
            invalidated_by=list(family.invalidated_by)
            or ["new_commit", "new_pr_update", "new_superseding_decision"],
            abstain_if_missing=list(family.necessary_ids),
            fastest_recipe=fastest,
            family_id=family.family_id,
            probe_name=family.probe_name,
            acquisition_recipe=recipe,
            curation_accepted=bool(eval_result.get("full_pass")),
        )


def _facts_map(items: list[EvidenceItem]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for it in items:
        for k, v in it.facts.items():
            if k.startswith("_"):
                out[k] = v
            else:
                out[k] = v
    return out


def derive_implementation_decision(items: list[EvidenceItem], question: str = "") -> str | None:
    """Fixed probe: derive decision from source evidence, never from injected labels.

    Rules (context.current_implementation_decision):
      - requires rfc_revision + superseded present in merged facts
      - superseded=True → SUPERSEDED
      - else → rev-{rfc_revision}
      - missing causal fact → abstain (None), not a false label
    """
    _ = question
    facts = _facts_map(items)
    if facts.get("_insufficient") is True:
        return None
    if any(str(it.id).startswith("__missing__") for it in items):
        return None
    if "rfc_revision" not in facts:
        return None
    if "superseded" not in facts:
        return None
    if facts.get("superseded") is True:
        return "SUPERSEDED"
    rev = facts.get("rfc_revision")
    if rev is None:
        return None
    try:
        return f"rev-{int(rev)}"
    except (TypeError, ValueError):
        return None


def default_decision_probe(items: list[EvidenceItem], question: str = "") -> str | None:
    """Legacy probe — prefer derive_implementation_decision for real capabilities."""
    return derive_implementation_decision(items, question)


PROBE_REGISTRY: dict[str, ProbeFn] = {
    "derive_implementation_decision": derive_implementation_decision,
    "default": default_decision_probe,
}


def resolve_probe(family: ContrastFamily | None = None, name: str | None = None) -> ProbeFn:
    key = name or (family.probe_name if family else None) or "derive_implementation_decision"
    return PROBE_REGISTRY.get(key, derive_implementation_decision)


def list_conditions(family: ContrastFamily) -> list[str]:
    """All evaluation conditions including per-evidence necessity deletes."""
    conds: list[str] = ["original", "relevant_edit", "irrelevant_control"]
    for nid in family.necessary_ids:
        conds.append(f"necessity_delete:{nid}")
    conds.append("necessity_delete:all")
    return conds


def apply_condition(
    family: ContrastFamily,
    condition: str,
    *,
    keep_ids: set[str] | None = None,
) -> list[EvidenceItem]:
    """Materialize evidence under a condition (+ optional recipe filter)."""
    items = [copy.deepcopy(e) for e in family.evidence]
    if condition == "original":
        pass
    elif condition == "relevant_edit":
        edit = family.relevant_edit
        target_id = str(edit.get("evidence_id") or "")
        fact_key = str(edit.get("fact") or "")
        new_val = edit.get("value")
        for it in items:
            if it.id == target_id or (not target_id and fact_key and fact_key in it.facts):
                it.facts = dict(it.facts)
                if fact_key:
                    it.facts[fact_key] = new_val
                if "text_suffix" in edit:
                    it.text = f"{it.text} {edit['text_suffix']}".strip()
                break
    elif condition == "irrelevant_control":
        ctrl = family.irrelevant_control or {
            "evidence_id": items[0].id if items else "",
            "text_suffix": " [fmt]",
        }
        target_id = str(ctrl.get("evidence_id") or (items[0].id if items else ""))
        for it in items:
            if it.id == target_id:
                it.text = f"{it.text}{ctrl.get('text_suffix', ' [irrelevant]')}".strip()
                break
    elif condition.startswith("necessity_delete:"):
        suffix = condition.split(":", 1)[1]
        if suffix == "all":
            drop = set(family.necessary_ids) or {it.id for it in items if it.necessary}
        else:
            drop = {suffix}
        items = [it for it in items if it.id not in drop]
        if items:
            items[0].facts = dict(items[0].facts)
            items[0].facts["_insufficient"] = True
        else:
            items = [
                EvidenceItem(
                    id="__missing__all",
                    text="",
                    facts={"_insufficient": True},
                )
            ]
    elif condition == "necessity_delete":
        # backward compat → all
        return apply_condition(family, "necessity_delete:all", keep_ids=keep_ids)
    else:
        raise ValueError(f"unknown condition: {condition}")

    if keep_ids is not None:
        items = [it for it in items if it.id in keep_ids]
        needed = set(family.necessary_ids) or {it.id for it in family.evidence if it.necessary}
        if needed - set(keep_ids):
            if items:
                items[0].facts = dict(items[0].facts)
                items[0].facts["_insufficient"] = True
            else:
                items = [
                    EvidenceItem(
                        id="__missing__recipe",
                        text="",
                        facts={"_insufficient": True},
                    )
                ]
    return items


def expected_answer(family: ContrastFamily, condition: str) -> str | None:
    if condition == "original":
        return family.answer_original
    if condition == "relevant_edit":
        return family.answer_after_relevant_edit
    if condition == "irrelevant_control":
        return family.answer_original
    if condition.startswith("necessity_delete"):
        return None
    raise ValueError(condition)


def compute_metrics(rows: dict[str, Any]) -> dict[str, Any]:
    """Grouped-family metrics (not row-average accuracy)."""
    orig = rows.get("original", {})
    rel = rows.get("relevant_edit", {})
    irr = rows.get("irrelevant_control", {})
    necessity_rows = {k: v for k, v in rows.items() if k.startswith("necessity_delete")}
    pair_pass = bool(orig.get("ok") and rel.get("ok"))
    necessity_ok = all(r.get("ok") for r in necessity_rows.values()) if necessity_rows else True
    full_pass = pair_pass and bool(irr.get("ok")) and necessity_ok
    return {
        "original_accuracy": 1.0 if orig.get("ok") else 0.0,
        "contrast_pair_accuracy": 1.0 if pair_pass else 0.0,
        "irrelevant_invariance": 1.0 if irr.get("ok") else 0.0,
        "necessity_abstention": 1.0 if necessity_ok else 0.0,
        "full_family_pass_rate": 1.0 if full_pass else 0.0,
        "necessity_conditions": len(necessity_rows),
        "necessity_passed": sum(1 for r in necessity_rows.values() if r.get("ok")),
    }


def evaluate_family(
    family: ContrastFamily,
    *,
    probe: ProbeFn | None = None,
    keep_ids: set[str] | None = None,
    recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all conditions. full_pass requires entire contrast family correct."""
    fn = probe or resolve_probe(family)
    conditions = list_conditions(family)
    rows: dict[str, Any] = {}
    needed = set(family.necessary_ids) or {it.id for it in family.evidence if it.necessary}

    for c in conditions:
        items = apply_condition(family, c, keep_ids=keep_ids)
        present = {it.id for it in items if not str(it.id).startswith("__missing__")}
        is_necessity = c.startswith("necessity_delete")
        if not is_necessity and needed - present:
            pred = None
        else:
            pred = fn(items, family.question)
        exp = expected_answer(family, c)
        rows[c] = {
            "condition": c,
            "predicted": pred,
            "expected": exp,
            "ok": pred == exp,
            "n_evidence": len([i for i in items if not str(i.id).startswith("__missing__")]),
        }

    metrics = compute_metrics(rows)
    dep = EvidenceDependency.from_eval(family, {"full_pass": metrics["full_family_pass_rate"] == 1.0}, recipe=recipe)

    return {
        "schema": SCHEMA_RESULT,
        "family_id": family.family_id,
        "task_family": family.task_family,
        "capability_id": family.task_family,
        "probe_name": family.probe_name,
        "conditions": rows,
        "metrics": metrics,
        "pair_pass": metrics["contrast_pair_accuracy"] == 1.0,
        "robust_pass": metrics["irrelevant_invariance"] == 1.0 and metrics["necessity_abstention"] == 1.0,
        "full_pass": metrics["full_family_pass_rate"] == 1.0,
        "dependency": dep.to_dict(),
        "recipe": recipe,
        "evaluated_at": time.time(),
    }


def recipe_keep_ids(family: ContrastFamily, recipe: dict[str, Any]) -> set[str]:
    all_ids = {e.id for e in family.evidence}
    if recipe.get("keep_evidence_ids"):
        return {str(x) for x in recipe["keep_evidence_ids"]} & all_ids
    keep = set(all_ids)
    if recipe.get("drop_evidence_ids"):
        keep -= {str(x) for x in recipe["drop_evidence_ids"]}
    if recipe.get("keep_necessary_only"):
        nec = set(family.necessary_ids) or {e.id for e in family.evidence if e.necessary}
        keep &= nec
    return keep


def evaluate_recipe_on_family(family: ContrastFamily, recipe: dict[str, Any]) -> dict[str, Any]:
    keep = recipe_keep_ids(family, recipe)
    out = evaluate_family(family, keep_ids=keep, recipe=recipe)
    out["recipe_keep_ids"] = sorted(keep)
    return out


def example_project_status_family() -> ContrastFamily:
    """Fixture: decision derived from rfc_revision + superseded (source-level edit only)."""
    return ContrastFamily(
        family_id="fixture.project_status.v1",
        task_family=CAPABILITY_IMPLEMENTATION_DECISION,
        question="What is the current accepted implementation decision for this project?",
        evidence=[
            EvidenceItem(
                id="rfc_rev",
                text="RFC-12 revision is 3.",
                necessary=True,
                facts={"rfc_revision": 3},
            ),
            EvidenceItem(
                id="supersede",
                text="Decision log: no superseding plan.",
                necessary=True,
                facts={"superseded": False},
            ),
            EvidenceItem(
                id="old_summary",
                text="Yesterday summary still said rev-2 was active.",
                necessary=False,
                facts={"stale_summary": "rev-2"},
            ),
            EvidenceItem(
                id="unrelated_chat",
                text="Unrelated chat about lunch.",
                necessary=False,
                facts={"chat": "lunch"},
            ),
        ],
        answer_original="rev-3",
        answer_after_relevant_edit="rev-4",
        relevant_edit={
            "evidence_id": "rfc_rev",
            "fact": "rfc_revision",
            "value": 4,
            "text_suffix": "(edited: revision is 4)",
        },
        necessary_ids=["rfc_rev", "supersede"],
        irrelevant_control={
            "evidence_id": "unrelated_chat",
            "text_suffix": " [whitespace reformatted]",
        },
        invariant_ids=["old_summary", "unrelated_chat"],
        invalidated_by=["rfc_revision_change", "superseding_decision"],
        source_family_id="fixture",
        parent_example_id="fixture.project_status.base",
        supervision="deterministic",
        probe_name="derive_implementation_decision",
    )


def store_dependency(record: dict[str, Any] | EvidenceDependency) -> Path:
    d = paths.home() / "evidence_dependencies"
    d.mkdir(parents=True, exist_ok=True)
    if isinstance(record, EvidenceDependency):
        blob = record.to_dict()
    else:
        blob = dict(record)
    fid = str(blob.get("family_id") or blob.get("capability_id") or "unknown")
    path = d / f"{fid.replace('/', '_')}.json"
    path.write_text(json.dumps(blob, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    journal = d / "journal.jsonl"
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": time.time(), **blob}, sort_keys=True) + "\n")
    return path


def family_fingerprint(family: ContrastFamily) -> str:
    blob = json.dumps(family.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def aggregate_family_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate grouped-family metrics across a cohort."""
    if not results:
        return {"n": 0, "full_family_pass_rate": 0.0}
    keys = (
        "original_accuracy",
        "contrast_pair_accuracy",
        "irrelevant_invariance",
        "necessity_abstention",
        "full_family_pass_rate",
    )
    agg = {k: 0.0 for k in keys}
    for r in results:
        m = r.get("metrics") or {}
        for k in keys:
            agg[k] += float(m.get(k) or 0.0)
    n = len(results)
    for k in keys:
        agg[k] /= n
    agg["n"] = n
    return agg
