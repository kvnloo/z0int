"""Load deterministic decision-capability-v1 fixtures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..base import DecisionQuestion, DecisionRequest, request_from_mapping
from .contract import CAPABILITIES


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_fixtures_path() -> Path:
    return _repo_root() / "benchmarks" / "fixtures" / "decision-capability-v1" / "examples.jsonl"


@dataclass(frozen=True)
class BenchExample:
    id: str
    capability: str
    provenance: str
    state: str | dict[str, Any] | list[Any]
    question: DecisionQuestion
    gold: str
    allow_abstain: bool = False
    abstain_option_id: str | None = None
    raw: dict[str, Any] | None = None

    def to_request(self) -> DecisionRequest:
        q = self.question
        qmap: dict[str, Any] = {
            "id": q.id,
            "type": q.type,
            "instructions": q.instructions,
        }
        if q.type == "choice":
            qmap["options"] = [{"id": o.id, "description": o.description} for o in q.options]
        elif q.type == "boolean":
            qmap["criteria"] = {
                "false": q.false_criterion or "false",
                "true": q.true_criterion or "true",
            }
        else:
            qmap["criteria"] = list(q.levels)
        return request_from_mapping(
            {"request_id": self.id, "state": self.state, "questions": [qmap]}
        )

    def dangerous_prediction(self, pred: str) -> bool:
        raw = self.raw or {}
        if self.gold == "worker":
            bad = raw.get("dangerous_if_gold_worker") or []
            return pred in bad
        if self.gold == "escalate":
            bad = raw.get("dangerous_if_gold_escalate") or []
            return pred in bad
        if self.gold == "yes":
            bad = raw.get("dangerous_if_gold_yes") or []
            return pred in bad
        bad = raw.get("dangerous_labels") or []
        return pred in bad


def _parse_example(raw: dict[str, Any]) -> BenchExample:
    cap = str(raw.get("capability") or "")
    if cap not in CAPABILITIES:
        raise ValueError(f"unknown capability {cap!r} in {raw.get('id')}")
    req = request_from_mapping({"state": raw.get("state"), "questions": [raw.get("question")]})
    q = req.questions[0]
    gold = str(raw.get("gold") or "")
    if q.type == "boolean" and gold.lower() in ("true", "false"):
        gold = gold.lower()
    return BenchExample(
        id=str(raw.get("id") or ""),
        capability=cap,
        provenance=str(raw.get("provenance") or "unknown"),
        state=req.state,
        question=q,
        gold=gold,
        allow_abstain=bool(raw.get("allow_abstain")),
        abstain_option_id=(str(raw["abstain_option_id"]) if raw.get("abstain_option_id") else None),
        raw=raw,
    )


def load_fixtures(path: Path | None = None) -> list[BenchExample]:
    p = path or default_fixtures_path()
    if not p.is_file():
        raise FileNotFoundError(f"fixtures not found: {p}")
    out: list[BenchExample] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(_parse_example(json.loads(line)))
    return out
