"""Backend-neutral research proposal drivers for autoresearch (P0).

agy is RESEARCH/HYPOTHESIS GENERATION only — not an LLM provider / Kerdoios resource.
"""

from .convert import proposal_to_fly_candidate
from .driver import AgyResearchDriver, DeterministicSearchDriver, ResearchDriver, get_driver
from .job import ResearchJob, create_research_job
from .pipeline import run_research_once
from .proposal import (
    ALLOWED_KNOBS,
    LOCKED_HISTORY,
    ResearchProposalV1,
    ResearchProposalError,
    load_proposal,
    validate_proposal,
)

__all__ = [
    "ALLOWED_KNOBS",
    "LOCKED_HISTORY",
    "AgyResearchDriver",
    "DeterministicSearchDriver",
    "ResearchDriver",
    "ResearchJob",
    "ResearchProposalError",
    "ResearchProposalV1",
    "create_research_job",
    "get_driver",
    "load_proposal",
    "proposal_to_fly_candidate",
    "run_research_once",
    "validate_proposal",
]

from .canonicalize import candidate_fingerprint, effective_candidate, fingerprints_equal
from .promotion import paired_decide, noop_result

__all__ += [
    "candidate_fingerprint",
    "effective_candidate",
    "fingerprints_equal",
    "paired_decide",
    "noop_result",
]

