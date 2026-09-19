"""Canonical effective candidates + fingerprints for promotion integrity.

Resolves implicit defaults (e.g. k_winners=0 → 10% of hidden) so no-op
proposals are rejected before spending bench compute.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


def effective_k_winners(*, hidden: int, k_winners: int | None) -> int:
    """Match evolution_lab.engine / models runtime resolution."""
    kw = int(k_winners or 0)
    if kw > 0:
        return kw
    return max(5, int(round(0.10 * int(hidden))))


@dataclass(frozen=True)
class CanonicalCandidate:
    hidden: int
    history: int
    dagger_rounds: int
    plasticity_lr: float
    plasticity_epochs: int
    k_winners_raw: int
    k_winners_effective: int
    seed: int
    family: str = "local_plasticity"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def knobs_for_brief(self) -> dict[str, Any]:
        """Knobs shown to agy — effective values, not sparse raw defaults."""
        return {
            "hidden": self.hidden,
            "dagger_rounds": self.dagger_rounds,
            "plasticity_lr": self.plasticity_lr,
            "plasticity_epochs": self.plasticity_epochs,
            "k_winners": self.k_winners_effective,
            "k_winners_raw": self.k_winners_raw,
            "seed": self.seed,
            "history": self.history,
        }


def _as_candidate_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        if "candidate" in obj and isinstance(obj["candidate"], dict):
            return obj["candidate"]
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()  # type: ignore[no-any-return]
    # FlyCandidate-like
    return {
        "genome": getattr(obj, "genome", {}),
        "dagger_rounds": getattr(obj, "dagger_rounds", 0),
        "plasticity_lr": getattr(obj, "plasticity_lr", 0.35),
        "plasticity_epochs": getattr(obj, "plasticity_epochs", 20),
        "k_winners": getattr(obj, "k_winners", 0),
    }


def effective_candidate(candidate: Any) -> CanonicalCandidate:
    c = _as_candidate_dict(candidate)
    genome = c.get("genome") or {}
    arch = genome.get("architecture") or {}
    training = genome.get("training") or {}
    hidden = int(arch.get("hidden") or 128)
    history = int(arch.get("history") or 8)
    raw_kw = int(c.get("k_winners") or arch.get("k_winners") or 0)
    return CanonicalCandidate(
        hidden=hidden,
        history=history,
        dagger_rounds=int(c.get("dagger_rounds") or 0),
        plasticity_lr=float(c.get("plasticity_lr") or training.get("plasticity_lr") or 0.35),
        plasticity_epochs=int(c.get("plasticity_epochs") or training.get("plasticity_epochs") or 20),
        k_winners_raw=raw_kw,
        k_winners_effective=effective_k_winners(hidden=hidden, k_winners=raw_kw),
        seed=int(training.get("seed") or 0),
        family=str(arch.get("family") or "local_plasticity"),
    )


def candidate_fingerprint(candidate: Any) -> str:
    """Stable hash over effective search knobs (not genome_id / description)."""
    canon = effective_candidate(candidate)
    payload = {
        "family": canon.family,
        "hidden": canon.hidden,
        "history": canon.history,
        "dagger_rounds": canon.dagger_rounds,
        "plasticity_lr": round(float(canon.plasticity_lr), 8),
        "plasticity_epochs": canon.plasticity_epochs,
        "k_winners_effective": canon.k_winners_effective,
        "seed": canon.seed,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprints_equal(a: Any, b: Any) -> bool:
    return candidate_fingerprint(a) == candidate_fingerprint(b)
