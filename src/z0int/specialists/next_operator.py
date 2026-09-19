"""os.next_operator shadow specialist.

Predict operator family from sanitized state_before only.
Metric: safe coverage @ precision floor (not top-1 accuracy).
PREPARE-only initially — never COMMIT.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from z0int.os_context import OPERATOR_FAMILIES, episodes_dir, normalize_operator

SCHEMA = "os.next_operator.v0"
DEFAULT_PRECISION_FLOOR = 0.90


def _feat(state: dict[str, Any]) -> tuple[str, ...]:
    """Coarse discrete features — no free text."""
    return (
        str(state.get("app") or ""),
        str(state.get("project") or ""),
        str(state.get("harness") or ""),
        str(state.get("harness_state") or ""),
        str(state.get("workspace") or ""),
        str(state.get("task_phase") or ""),
    )


def load_episodes(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or (episodes_dir() / "episodes.jsonl")
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def fit_recency_prior(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Majority / recency baseline: P(op | app, project)."""
    counts: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    global_counts: Counter[str] = Counter()
    for ep in episodes:
        op = normalize_operator(ep.get("actual_operator") or "noop")
        feat = _feat(ep.get("state_before") or {})
        counts[feat][op] += 1
        global_counts[op] += 1
    return {
        "schema": SCHEMA,
        "kind": "recency_prior",
        "counts": { "|".join(k): dict(v) for k, v in counts.items() },
        "global": dict(global_counts),
        "n": len(episodes),
        "fitted_at": time.time(),
    }


def predict(
    state: dict[str, Any],
    model: dict[str, Any],
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    feat = _feat(state)
    key = "|".join(feat)
    local = model.get("counts", {}).get(key) or {}
    base = model.get("global") or {}
    # blend local with global
    scores: dict[str, float] = {}
    for op in OPERATOR_FAMILIES:
        scores[op] = 0.7 * float(local.get(op, 0)) + 0.3 * float(base.get(op, 0))
    total = sum(scores.values()) or 1.0
    probs = {op: scores[op] / total for op in OPERATOR_FAMILIES}
    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    top1, p1 = ranked[0]
    margin = (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else ranked[0][1]
    entropy = -sum(p * math.log(p + 1e-12) for p in probs.values())
    return {
        "schema": SCHEMA,
        "top1": top1,
        "p": p1,
        "margin": margin,
        "entropy": entropy,
        "topk": [{"operator": op, "p": p} for op, p in ranked],
        "gate": "PREDICT",
    }


def safe_coverage(
    episodes: list[dict[str, Any]],
    model: dict[str, Any],
    *,
    precision_floor: float = DEFAULT_PRECISION_FLOOR,
    min_p: float = 0.5,
) -> dict[str, Any]:
    """Fraction of transitions the cheap predictor can absorb at precision floor."""
    if not episodes:
        return {"schema": SCHEMA, "n": 0, "coverage": 0.0, "precision": None, "absorbed": 0}

    # score threshold sweep for coverage@precision
    scored = []
    for ep in episodes:
        pred = predict(ep.get("state_before") or {}, model)
        actual = ep.get("actual_operator") or "OTHER"
        scored.append((pred["p"], pred["top1"] == actual, pred["top1"], actual))

    # take predictions with p >= min_p, find if precision >= floor
    accepted = [(p, ok) for p, ok, _, _ in scored if p >= min_p]
    if not accepted:
        return {
            "schema": SCHEMA,
            "n": len(episodes),
            "coverage": 0.0,
            "precision": None,
            "absorbed": 0,
            "min_p": min_p,
            "precision_floor": precision_floor,
        }
    # raise min_p until precision met
    best_cov = 0.0
    best_prec = 0.0
    best_thr = 1.0
    for thr in sorted({p for p, _, _, _ in scored}, reverse=True):
        subset = [(p, ok) for p, ok, _, _ in scored if p >= thr]
        if not subset:
            continue
        prec = sum(1 for _, ok in subset if ok) / len(subset)
        cov = len(subset) / len(scored)
        if prec >= precision_floor and cov >= best_cov:
            best_cov, best_prec, best_thr = cov, prec, thr
    return {
        "schema": SCHEMA,
        "n": len(episodes),
        "coverage": best_cov,
        "precision": best_prec if best_cov else None,
        "threshold_p": best_thr if best_cov else None,
        "absorbed": int(round(best_cov * len(episodes))),
        "precision_floor": precision_floor,
        "gate": "PREDICT",  # not PREPARE/SURFACE/COMMIT
    }


def shadow_report(path: Path | None = None) -> dict[str, Any]:
    eps = load_episodes(path)
    model = fit_recency_prior(eps)
    cov = safe_coverage(eps, model)
    return {
        "ok": True,
        "model_kind": model["kind"],
        "n_episodes": model["n"],
        "coverage": cov,
        "global_prior": model.get("global"),
    }
