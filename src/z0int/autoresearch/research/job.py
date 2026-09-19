"""Research job artifacts: BRIEF.md + world/gap/champion/contract snapshots."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ResearchJob:
    job_id: str
    job_dir: Path

    @property
    def brief_path(self) -> Path:
        return self.job_dir / "BRIEF.md"

    def path(self, name: str) -> Path:
        return self.job_dir / name


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")


def create_research_job(
    *,
    root: Path,
    objective: str,
    champion: dict[str, Any],
    measurement_gaps: list[dict[str, Any]],
    world: dict[str, Any] | None,
    search_space: dict[str, Any],
    product_target: dict[str, Any],
    objective_weights: dict[str, Any],
    recent_failures: list[dict[str, Any]] | None = None,
    abab_hypotheses: list[dict[str, Any]] | None = None,
    profiler: dict[str, Any] | None = None,
    job_id: str | None = None,
    canonical_champion: dict[str, Any] | None = None,
    incumbent: dict[str, Any] | None = None,
) -> ResearchJob:
    jid = job_id or f"rj-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    job_dir = Path(root) / "runs" / "autoresearch" / "jobs" / jid
    job_dir.mkdir(parents=True, exist_ok=True)
    job = ResearchJob(job_id=jid, job_dir=job_dir)

    _dump(job.path("world.json"), world or {})
    _dump(job.path("measurement-gaps.json"), measurement_gaps)
    _dump(job.path("champion.json"), champion)
    if canonical_champion is not None:
        _dump(job.path("canonical-champion.json"), canonical_champion)
    if incumbent is not None:
        _dump(job.path("incumbent.json"), incumbent)
    _dump(
        job.path("benchmark-contract.json"),
        {
            "schema": "z0int.flyforge.benchmark_contract.v1",
            "product_target": product_target,
            "objective": objective_weights,
            "search_space": search_space,
            "locked_history": 8,
            "frozen_judge": ["evolution_lab/bench.py", "evolution_lab/select.py", "data/p0/*"],
            "mutation_kind_p0": "parameter",
            "allowed_knobs": list(search_space.keys()),
        },
    )
    _dump(
        job.path("profiler.json"),
        profiler
        or {
            "note": "Hosted joules unknown; latency proxy is primary score.",
            "latency_score": "0.7*advise_warm_p99_ms + 0.3*closed_loop_ms",
        },
    )
    failures = recent_failures or []
    hyps = abab_hypotheses or []
    gaps_txt = "\n".join(
        f"- {g.get('capability_id') or g.get('name') or g.get('gap') or g}: "
        f"priority={g.get('gap_priority') or g.get('priority') or g.get('score') or 'n/a'}"
        for g in measurement_gaps[:12]
    ) or "- (no Tokenomics gaps available; use champion latency + open ABAB hypotheses)"
    fail_txt = "\n".join(
        f"- {f.get('experiment_id') or f.get('id')}: {f.get('description') or f.get('status')} "
        f"score={f.get('latency_score')}"
        for f in failures[:8]
    ) or "- (none recorded)"
    hyp_txt = "\n".join(
        f"- {h.get('id')}: {h.get('claim')} (status={h.get('status')}, eig={h.get('eig')})"
        for h in hyps[:8]
    ) or "- (none)"
    space_txt = json.dumps(search_space, indent=2)
    brief = f"""# Research BRIEF — {jid}

## Objective
{objective}

Emit **exactly one** ResearchProposalV1 JSON object.
mutation_kind MUST be `parameter` (no source edits, no judge edits).

## Current champion (raw snapshot)
```json
{json.dumps(champion, indent=2, default=str)[:2500]}
```

## Canonical champion (effective knobs — use THESE)
```json
{json.dumps(canonical_champion or {}, indent=2, default=str)[:2000]}
```

## Frozen incumbent for this job
```json
{json.dumps(incumbent or {}, indent=2, default=str)[:1500]}
```

## Recent failed / discarded candidates
{fail_txt}

## Current ABAB hypotheses
{hyp_txt}

## Highest Tokenomics measurement gaps
{gaps_txt}

## Frozen invariants (do not violate)
- Do NOT edit bench.py, select.py, data/p0 splits, observe.py secret filters, or promotion gates.
- history remains locked at 8.
- Hard gates: closed_loop_reward >= 1.0; confirm/val >= 0.95; ood >= 0.85; violations == 0.
- Promotion score (minimize): 0.7 * advise_warm_p99_ms + 0.3 * closed_loop_ms.

## Search-space limits (parameter only)
```json
{space_txt}
```

Allowed knobs: hidden, dagger_rounds, plasticity_lr, plasticity_epochs, k_winners, seed.
For `seed`, propose absolute seed = champion.seed + delta where delta ∈ seed_delta.
target MUST be `{{"knob": <name>, "value": <allowed discrete value>}}`.
Propose a value different from the *effective* champion knob values above.
If your proposal is equivalent to the incumbent after resolving defaults
(e.g. k_winners=0 with hidden=96 already means effective k_winners=10),
it will be rejected as NO_OP without benchmarking.

## Output
Return only ResearchProposalV1 matching the provided JSON schema.
No secrets. No raw personal data. No code patches.
"""
    job.brief_path.write_text(brief, encoding="utf-8")
    return job
