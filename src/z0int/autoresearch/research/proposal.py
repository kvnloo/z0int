"""ResearchProposalV1 — strict parameter-mutation proposals for FlyForge search space."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

PROPOSAL_SCHEMA = "z0int.research_proposal.v1"
LOCKED_HISTORY = 8
ALLOWED_KNOBS = ("hidden", "dagger_rounds", "plasticity_lr", "plasticity_epochs", "k_winners", "seed")
MutationKind = Literal["parameter"]  # P0 only; kernel_impl is P1 design-only
Direction = Literal["minimize", "maximize", "improve"]


class ResearchProposalError(ValueError):
    """Invalid or out-of-space research proposal."""


@dataclass
class ResearchProposalV1:
    proposal_id: str
    hypothesis: str
    mechanism: str
    mutation_kind: MutationKind
    target: dict[str, Any]  # {"knob": str, "value": number}
    expected_metric: str
    expected_direction: Direction
    expected_magnitude: float
    invariants: list[str] = field(default_factory=list)
    falsifiers: list[str] = field(default_factory=list)
    benchmark_plan: str = "fly_bench_v1"
    references: list[str] = field(default_factory=list)
    confidence: float = 0.5
    schema: str = PROPOSAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchProposalV1":
        if not isinstance(data, dict):
            raise ResearchProposalError("proposal must be object")
        pid = str(data.get("proposal_id") or "").strip() or f"rp-{uuid.uuid4().hex[:12]}"
        mk = str(data.get("mutation_kind") or "").strip()
        if mk != "parameter":
            raise ResearchProposalError(f"P0 requires mutation_kind=parameter, got {mk!r}")
        target = data.get("target")
        if not isinstance(target, dict):
            raise ResearchProposalError("target must be object {knob,value}")
        return cls(
            proposal_id=pid,
            hypothesis=str(data.get("hypothesis") or "").strip(),
            mechanism=str(data.get("mechanism") or "").strip(),
            mutation_kind="parameter",
            target={
                "knob": str(target.get("knob") or "").strip(),
                "value": target.get("value"),
            },
            expected_metric=str(data.get("expected_metric") or "latency_score").strip(),
            expected_direction=str(data.get("expected_direction") or "minimize").strip(),  # type: ignore[arg-type]
            expected_magnitude=float(data.get("expected_magnitude") or 0.0),
            invariants=[str(x) for x in (data.get("invariants") or [])],
            falsifiers=[str(x) for x in (data.get("falsifiers") or [])],
            benchmark_plan=str(data.get("benchmark_plan") or "fly_bench_v1"),
            references=[str(x) for x in (data.get("references") or [])],
            confidence=float(data.get("confidence") or 0.5),
            schema=str(data.get("schema") or PROPOSAL_SCHEMA),
        )


def json_schema() -> dict[str, Any]:
    """JSON Schema for agy --json-schema."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ResearchProposalV1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "proposal_id",
            "hypothesis",
            "mechanism",
            "mutation_kind",
            "target",
            "expected_metric",
            "expected_direction",
            "expected_magnitude",
            "invariants",
            "falsifiers",
            "benchmark_plan",
            "confidence",
        ],
        "properties": {
            "schema": {"type": "string", "const": PROPOSAL_SCHEMA},
            "proposal_id": {"type": "string", "minLength": 1},
            "hypothesis": {"type": "string", "minLength": 8},
            "mechanism": {"type": "string", "minLength": 4},
            "mutation_kind": {"type": "string", "const": "parameter"},
            "target": {
                "type": "object",
                "additionalProperties": False,
                "required": ["knob", "value"],
                "properties": {
                    "knob": {"type": "string", "enum": list(ALLOWED_KNOBS)},
                    "value": {"type": ["number", "integer"]},
                },
            },
            "expected_metric": {"type": "string"},
            "expected_direction": {"type": "string", "enum": ["minimize", "maximize", "improve"]},
            "expected_magnitude": {"type": "number"},
            "invariants": {"type": "array", "items": {"type": "string"}},
            "falsifiers": {"type": "array", "items": {"type": "string"}},
            "benchmark_plan": {"type": "string"},
            "references": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }


def _value_in_space(knob: str, value: Any, search_space: dict[str, Any], *, champion_knobs: dict[str, Any] | None = None) -> bool:
    if knob == "seed":
        # Prefer champion.seed + seed_delta ∈ space; else accept absolute int seed.
        deltas = search_space.get("seed_delta") or []
        if champion_knobs and "seed" in champion_knobs and deltas:
            base = int(champion_knobs["seed"])
            return any(int(value) == base + int(d) for d in deltas)
        return isinstance(value, (int, float)) and int(value) == value
    choices = search_space.get(knob) or []
    if not choices:
        return False
    if knob in {"plasticity_lr"}:
        return any(abs(float(value) - float(c)) < 1e-12 for c in choices)
    return any(value == c or int(value) == int(c) for c in choices)


FORBIDDEN_PATH_MARKERS = (
    "bench.py",
    "select.py",
    "data/p0",
    "observe.py",
    "kernel_impl",
    "edit judge",
    "modify gates",
)


def validate_proposal(
    proposal: ResearchProposalV1,
    *,
    search_space: dict[str, Any],
    champion_knobs: dict[str, Any] | None = None,
) -> ResearchProposalV1:
    if not proposal.hypothesis:
        raise ResearchProposalError("hypothesis required")
    if not proposal.mechanism:
        raise ResearchProposalError("mechanism required")
    if proposal.mutation_kind != "parameter":
        raise ResearchProposalError("only mutation_kind=parameter allowed in P0")
    knob = str(proposal.target.get("knob") or "")
    value = proposal.target.get("value")
    if knob not in ALLOWED_KNOBS:
        raise ResearchProposalError(f"knob {knob!r} outside allowed search space {ALLOWED_KNOBS}")
    if value is None:
        raise ResearchProposalError("target.value required")
    if not _value_in_space(knob, value, search_space, champion_knobs=champion_knobs):
        raise ResearchProposalError(f"value {value!r} for {knob} outside search_space")
    # history locked
    blob = json.dumps(proposal.to_dict(), sort_keys=True).lower()
    if "history" in knob or '"history"' in blob and "history=8" not in blob:
        # allow mentioning locked history in invariants text
        pass
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker in proposal.hypothesis.lower() and "do not" not in proposal.hypothesis.lower():
            # soft: reject explicit judge-mutation intent in target only
            pass
    text = " ".join(
        [
            proposal.hypothesis,
            proposal.mechanism,
            proposal.benchmark_plan,
            " ".join(proposal.references),
        ]
    ).lower()
    if any(x in text for x in ("edit bench.py", "patch select.py", "change gates", "unlock history")):
        raise ResearchProposalError("proposal attempts judge mutation")
    if champion_knobs and knob in champion_knobs:
        cur = champion_knobs[knob]
        try:
            if float(cur) == float(value) and knob != "seed":
                raise ResearchProposalError(f"proposal value equals champion {knob}={cur}")
        except (TypeError, ValueError):
            if cur == value:
                raise ResearchProposalError(f"proposal value equals champion {knob}={cur}") from None
    if proposal.expected_direction not in {"minimize", "maximize", "improve"}:
        raise ResearchProposalError("invalid expected_direction")
    if not (0.0 <= float(proposal.confidence) <= 1.0):
        raise ResearchProposalError("confidence must be in [0,1]")
    # force locked history invariant present
    inv = list(proposal.invariants)
    if not any("history" in i.lower() for i in inv):
        inv.append(f"history locked at {LOCKED_HISTORY}")
    proposal.invariants = inv
    return proposal


def load_proposal(path: Path | str) -> ResearchProposalV1:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ResearchProposalV1.from_dict(data)


def write_json_schema(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8")
    return path
