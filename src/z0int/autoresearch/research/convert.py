"""Convert ResearchProposalV1 → Evolution Lab FlyCandidate (parameter mutations only)."""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from .proposal import ALLOWED_KNOBS, LOCKED_HISTORY, ResearchProposalError, ResearchProposalV1


def _ensure_el(root: Path) -> None:
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


def proposal_to_fly_candidate(
    proposal: ResearchProposalV1,
    *,
    champion: dict[str, Any] | None = None,
    evolution_lab_root: Path | None = None,
) -> Any:
    root = Path(evolution_lab_root or os.environ.get("EVOLUTION_LAB_ROOT") or "/home/kvn/tmp/evolution-lab")
    _ensure_el(root)
    from dataclasses import replace

    from evolution_lab.autoresearch_propose import champion_from_genome, default_champion_candidate
    from evolution_lab.schema import genome_from_dict
    from evolution_lab.select import FlyCandidate

    if champion and "genome" in champion:
        base = FlyCandidate.from_dict(champion)
    elif champion and isinstance(champion.get("candidate"), dict) and "genome" in champion["candidate"]:
        base = FlyCandidate.from_dict(champion["candidate"])
    else:
        base = default_champion_candidate()

    knob = str(proposal.target.get("knob") or "")
    value = proposal.target.get("value")
    if knob not in ALLOWED_KNOBS:
        raise ResearchProposalError(f"unsupported knob {knob}")

    genome = genome_from_dict(deepcopy(base.genome))
    if genome.architecture.history != LOCKED_HISTORY:
        genome = replace(genome, architecture=replace(genome.architecture, history=LOCKED_HISTORY))

    dagger_rounds = int(base.dagger_rounds)
    lr = float(base.plasticity_lr)
    epochs = int(base.plasticity_epochs)
    k_winners = int(base.k_winners or 0)

    if knob == "hidden":
        genome = replace(
            genome,
            architecture=replace(
                genome.architecture,
                hidden=int(value),
                family="local_plasticity",
                history=LOCKED_HISTORY,
            ),
        )
    elif knob == "dagger_rounds":
        dagger_rounds = int(value)
    elif knob == "plasticity_lr":
        lr = float(value)
    elif knob == "plasticity_epochs":
        epochs = int(value)
    elif knob == "k_winners":
        k_winners = int(value)
    elif knob == "seed":
        genome = replace(genome, training=replace(genome.training, seed=int(value)))
    else:
        raise ResearchProposalError(f"unhandled knob {knob}")

    return champion_from_genome(
        genome,
        dagger_rounds=dagger_rounds,
        plasticity_lr=lr,
        plasticity_epochs=epochs,
        k_winners=k_winners,
        description=f"agy:{proposal.proposal_id}:{knob}={value}",
    )
