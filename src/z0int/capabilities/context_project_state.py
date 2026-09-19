"""Frozen capability: context.current_project_state."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from z0int.contrastive_evidence import (
    CAPABILITY_CURRENT_PROJECT_STATE,
    ContrastFamily,
    EvidenceDependency,
    EvidenceItem,
    evaluate_family,
    evaluate_recipe_on_family,
    example_project_status_family,
    store_dependency,
)

SCHEMA_EPISODE = "z0int.context_project_state_episode.v0"


def fixture_family() -> ContrastFamily:
    return example_project_status_family()


def family_from_workspace_snapshot(snapshot: dict[str, Any]) -> ContrastFamily | None:
    project = snapshot.get("project") or snapshot.get("repo")
    if not project:
        return None
    head = snapshot.get("repo_head") or snapshot.get("git_head")
    pr = snapshot.get("open_pr") or snapshot.get("pr_number")
    rfc_rev = snapshot.get("rfc_revision", snapshot.get("implementation_revision"))
    if rfc_rev is None:
        return None
    superseded = bool(snapshot.get("superseded", False))
    try:
        rev_int = int(rfc_rev)
    except (TypeError, ValueError):
        return None
    contrast_rev = snapshot.get("rfc_revision_contrast", rev_int + 1)
    try:
        contrast_rev = int(contrast_rev)
    except (TypeError, ValueError):
        contrast_rev = rev_int + 1
    if superseded:
        answer = "SUPERSEDED"
        answer_after = "SUPERSEDED"
    else:
        answer = f"rev-{rev_int}"
        answer_after = f"rev-{contrast_rev}"

    evidence = [
        EvidenceItem(
            id="repo_head",
            text=f"git HEAD {head}",
            necessary=True,
            facts={"repo_head": head, "rfc_revision": int(rfc_rev)},
        ),
        EvidenceItem(
            id="supersede",
            text=f"superseded={superseded}",
            necessary=True,
            facts={"superseded": superseded},
        ),
    ]
    if pr is not None:
        evidence.append(
            EvidenceItem(id="open_pr", text=f"open PR #{pr}", necessary=False, facts={"open_pr": pr})
        )
    changed = snapshot.get("changed_files") or []
    if changed:
        evidence.append(
            EvidenceItem(
                id="changed_files",
                text=f"changed: {', '.join(str(x) for x in changed[:5])}",
                necessary=False,
                facts={"changed_files": list(changed[:20])},
            )
        )

    return ContrastFamily(
        family_id=f"wc.{project}.{head or 'unknown'}.{int(time.time())}",
        task_family=CAPABILITY_CURRENT_PROJECT_STATE,
        question=f"What is the current accepted state for project {project}?",
        evidence=evidence,
        answer_original=answer,
        answer_after_relevant_edit=answer_after,
        relevant_edit={
            "evidence_id": "repo_head",
            "fact": "rfc_revision",
            "value": contrast_rev,
            "text_suffix": f"(HEAD still {head or 'unknown'})",
        },
        necessary_ids=["repo_head", "supersede"],
        invariant_ids=[e.id for e in evidence if not e.necessary],
        invalidated_by=["git_head_change", "pr_update", "superseding_decision"],
        source_family_id=str(project),
        parent_example_id=snapshot.get("context_id") or snapshot.get("session"),
        supervision="live_verified",
        probe_name="derive_implementation_decision",
    )


def compile_episode(snapshot: dict[str, Any], *, label: str | None = None) -> dict[str, Any]:
    family = family_from_workspace_snapshot(snapshot)
    if family is None:
        return {"ok": False, "reason": "insufficient_snapshot_fields"}
    state_before = {
        k: snapshot.get(k)
        for k in (
            "project",
            "app",
            "harness",
            "session",
            "task",
            "task_phase",
            "repo_head",
            "open_pr",
            "changed_files",
        )
        if snapshot.get(k) not in (None, "")
    }
    return {
        "schema": SCHEMA_EPISODE,
        "capability_id": CAPABILITY_CURRENT_PROJECT_STATE,
        "family_id": family.family_id,
        "state_before": state_before,
        "available_evidence": [e.id for e in family.evidence],
        "label": label or family.answer_original,
        "supervision": family.supervision,
        "compiled_at": time.time(),
    }


def evaluate_and_store(family: ContrastFamily, recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    out = evaluate_recipe_on_family(family, recipe) if recipe else evaluate_family(family)
    dep = EvidenceDependency(**{k: v for k, v in out["dependency"].items() if k != "schema"})
    path = store_dependency(dep)
    out["dependency_path"] = str(path)
    return out


def families_jsonl_path(root: Path | None = None) -> Path:
    from z0int import paths

    home = paths.home() if root is None else root
    d = home / "context_families"
    d.mkdir(parents=True, exist_ok=True)
    return d / "context.current_project_state.jsonl"


def append_family_jsonl(family: ContrastFamily, *, path: Path | None = None) -> Path:
    """Append one compiled contrast family for cohort races / autoresearch."""
    out = path or families_jsonl_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(family.to_dict(), sort_keys=True) + "\n")
    return out


def compile_and_store(snapshot: dict[str, Any], *, label: str | None = None) -> dict[str, Any]:
    """Compile workspace snapshot → episode + stored contrast family."""
    ep = compile_episode(snapshot, label=label)
    if not ep.get("family_id"):
        return {"ok": False, **ep}
    fam = family_from_workspace_snapshot(snapshot)
    if fam is None:
        return {"ok": False, "reason": "family_build_failed", "episode": ep}
    fam_path = append_family_jsonl(fam)
    ep["ok"] = True
    ep["family_path"] = str(fam_path)
    ep["family"] = fam.to_dict()
    return ep


def load_families_jsonl(path: Path | str) -> list[ContrastFamily]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(ContrastFamily.from_dict(json.loads(line)))
    return rows
