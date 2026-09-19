"""ResearchDriver abstraction: deterministic SearchDriver + agy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .job import ResearchJob
from .proposal import (
    ResearchProposalError,
    ResearchProposalV1,
    json_schema,
    validate_proposal,
    write_json_schema,
)


@dataclass
class ResearchDriverResult:
    proposal: ResearchProposalV1 | None
    status: str  # ok | error | unavailable | timeout | malformed
    duration_ms: float
    model: str | None = None
    effort: str | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None
    command: list[str] | None = None


class ResearchDriver(Protocol):
    name: str

    def propose(
        self,
        job: ResearchJob,
        *,
        search_space: dict[str, Any],
        champion_knobs: dict[str, Any] | None = None,
        timeout_s: float = 900.0,
    ) -> ResearchDriverResult: ...


class DeterministicSearchDriver:
    """Wraps Evolution Lab's one-knob SearchDriver (no agy)."""

    name = "deterministic"

    def __init__(self, evolution_lab_root: Path | None = None) -> None:
        self.evolution_lab_root = Path(
            evolution_lab_root or os.environ.get("EVOLUTION_LAB_ROOT") or "/home/kvn/tmp/evolution-lab"
        )

    def propose(
        self,
        job: ResearchJob,
        *,
        search_space: dict[str, Any],
        champion_knobs: dict[str, Any] | None = None,
        timeout_s: float = 900.0,
    ) -> ResearchDriverResult:
        t0 = time.perf_counter()
        try:
            import sys

            root = str(self.evolution_lab_root)
            if root not in sys.path:
                sys.path.insert(0, root)
            import numpy as np
            from evolution_lab.autoresearch_propose import default_champion_candidate, propose_candidate
            from evolution_lab.select import FlyCandidate, load_config

            cfg = load_config(self.evolution_lab_root / "autoresearch" / "config.json")
            # Prefer champion.json from job if present
            champ_path = job.path("champion.json")
            if champ_path.is_file():
                raw = json.loads(champ_path.read_text(encoding="utf-8"))
                cand_raw = raw.get("candidate") or raw
                champion = FlyCandidate.from_dict(cand_raw) if "genome" in cand_raw else default_champion_candidate()
            else:
                champion = default_champion_candidate()
            rng = np.random.default_rng(abs(hash(job.job_id)) % (2**32))
            nxt = propose_candidate(champion, rng, cfg)
            # Infer which knob changed
            knob, value = _diff_knob(champion, nxt)
            prop = ResearchProposalV1(
                proposal_id=f"det-{uuid.uuid4().hex[:12]}",
                hypothesis=f"Mutating {knob} to {value} improves latency under PRODUCT_TARGET gates.",
                mechanism=f"Deterministic SearchDriver one-knob walk: {nxt.description}",
                mutation_kind="parameter",
                target={"knob": knob, "value": value},
                expected_metric="latency_score",
                expected_direction="minimize",
                expected_magnitude=0.05,
                invariants=["history locked at 8", "frozen judge"],
                falsifiers=[f"{knob}={value} fails gates or does not beat champion"],
                confidence=0.4,
            )
            prop = validate_proposal(prop, search_space=search_space or cfg.get("search_space") or {}, champion_knobs=champion_knobs)
            out = job.path("proposal.json")
            out.write_text(json.dumps(prop.to_dict(), indent=2) + "\n", encoding="utf-8")
            return ResearchDriverResult(
                proposal=prop,
                status="ok",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                model="deterministic_search_driver",
            )
        except Exception as exc:  # noqa: BLE001
            return ResearchDriverResult(
                proposal=None,
                status="error",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )


def _diff_knob(a: Any, b: Any) -> tuple[str, Any]:
    if a.dagger_rounds != b.dagger_rounds:
        return "dagger_rounds", b.dagger_rounds
    if abs(float(a.plasticity_lr) - float(b.plasticity_lr)) > 1e-12:
        return "plasticity_lr", b.plasticity_lr
    if a.plasticity_epochs != b.plasticity_epochs:
        return "plasticity_epochs", b.plasticity_epochs
    if int(a.k_winners or 0) != int(b.k_winners or 0):
        return "k_winners", b.k_winners
    ah = int((a.genome.get("architecture") or {}).get("hidden") or 0)
    bh = int((b.genome.get("architecture") or {}).get("hidden") or 0)
    if ah != bh:
        return "hidden", bh
    as_ = int((a.genome.get("training") or {}).get("seed") or 0)
    bs_ = int((b.genome.get("training") or {}).get("seed") or 0)
    return "seed", bs_


class AgyResearchDriver:
    """Official `agy` CLI headless research worker."""

    name = "agy"

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or os.environ.get("AGY_BIN") or shutil.which("agy") or "agy"

    def available(self) -> bool:
        return bool(shutil.which(self.binary) or Path(self.binary).is_file())

    def propose(
        self,
        job: ResearchJob,
        *,
        search_space: dict[str, Any],
        champion_knobs: dict[str, Any] | None = None,
        timeout_s: float = 900.0,
    ) -> ResearchDriverResult:
        t0 = time.perf_counter()
        if not self.available():
            return ResearchDriverResult(
                proposal=None,
                status="unavailable",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                error="agy binary not found",
            )
        schema_path = job.path("proposal.schema.json")
        write_json_schema(schema_path)
        # Headless + --sandbox cannot prompt for RunCommand; shell-reading BRIEF.md
        # is auto-denied. Keep BRIEF.md on disk for audit, but inline its body so
        # the research agent needs no file tools. Still point at BRIEF.md path.
        brief_body = job.brief_path.read_text(encoding="utf-8") if job.brief_path.is_file() else ""
        # BRIEF.md remains on disk for audit. Under headless --sandbox, ViewFile/RunCommand
        # are auto-denied, so the prompt carries the BRIEF body directly (no tool use).
        prompt = (
            "You are a research worker for FlyForge autoresearch.\n"
            "Using ONLY the BRIEF below, emit exactly one ResearchProposalV1 JSON object\n"
            "matching the provided JSON schema. mutation_kind MUST be parameter.\n"
            "Do not edit files. Do not call tools. Do not run shell commands.\n\n"
            f"--- BEGIN BRIEF ---\n{brief_body}\n--- END BRIEF ---"
        )
        cmd = [
            self.binary,
            "--mode=plan",
            "--agent",
            "research",
            "--sandbox",
            "--output-format",
            "json",
            "--json-schema",
            str(schema_path),
            f"--print-timeout={int(timeout_s)}s",
            "-p",
            prompt,
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(job.job_dir),
                capture_output=True,
                text=True,
                timeout=timeout_s + 30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ResearchDriverResult(
                proposal=None,
                status="timeout",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                error="agy print-timeout",
                command=cmd,
            )
        except FileNotFoundError:
            return ResearchDriverResult(
                proposal=None,
                status="unavailable",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                error="agy spawn failed",
                command=cmd,
            )

        duration_ms = (time.perf_counter() - t0) * 1000.0
        stdout = proc.stdout or ""
        (job.path("agy.stdout.txt")).write_text(stdout, encoding="utf-8")
        (job.path("agy.stderr.txt")).write_text(proc.stderr or "", encoding="utf-8")
        (job.path("agy.cmd.json")).write_text(json.dumps({"cmd": cmd, "returncode": proc.returncode}, indent=2) + "\n")

        try:
            envelope = json.loads(stdout.strip().splitlines()[-1] if stdout.strip() else "{}")
        except json.JSONDecodeError:
            return ResearchDriverResult(
                proposal=None,
                status="malformed",
                duration_ms=duration_ms,
                error="agy stdout not JSON",
                command=cmd,
                raw={"stdout": stdout[:2000]},
            )

        model = None
        effort = None
        response = envelope.get("response") if isinstance(envelope, dict) else None
        usage = envelope.get("usage") if isinstance(envelope, dict) else None
        if isinstance(envelope, dict):
            model = envelope.get("model") or (usage or {}).get("model")
        try:
            body = None
            # Prefer structured_output from agy json envelope when present.
            if isinstance(envelope, dict) and isinstance(envelope.get("structured_output"), dict):
                body = envelope["structured_output"]
            elif isinstance(response, str):
                text = response.strip()
                if not text:
                    denied = (envelope or {}).get("denied_actions") if isinstance(envelope, dict) else None
                    raise ResearchProposalError(
                        f"empty agy response (denied_actions={denied})"
                    )
                if text.startswith("```"):
                    # strip first fenced block
                    parts = text.split("```")
                    for part in parts:
                        chunk = part.strip()
                        if chunk.startswith("json"):
                            chunk = chunk[4:].strip()
                        if chunk.startswith("{"):
                            text = chunk
                            break
                # response may concatenate fenced JSON + trailing object; take first object
                if text.startswith("{"):
                    decoder = json.JSONDecoder()
                    body, _ = decoder.raw_decode(text)
                else:
                    body = json.loads(text)
            elif isinstance(response, dict):
                body = response
            else:
                body = envelope if isinstance(envelope, dict) and "mutation_kind" in envelope else None
            if not isinstance(body, dict):
                raise ResearchProposalError("no proposal object in agy response")
            prop = ResearchProposalV1.from_dict(body)
            prop = validate_proposal(prop, search_space=search_space, champion_knobs=champion_knobs)
            job.path("proposal.json").write_text(json.dumps(prop.to_dict(), indent=2) + "\n", encoding="utf-8")
            usage_out = usage if isinstance(usage, dict) else None
            return ResearchDriverResult(
                proposal=prop,
                status="ok",
                duration_ms=duration_ms,
                model=str(model) if model else None,
                effort=str(effort) if effort else None,
                raw=envelope if isinstance(envelope, dict) else {"envelope": envelope},
                command=cmd,
                usage=usage_out,
            )
        except Exception as exc:  # noqa: BLE001
            return ResearchDriverResult(
                proposal=None,
                status="malformed" if "JSON" in type(exc).__name__ or "proposal" in str(exc).lower() else "error",
                duration_ms=duration_ms,
                model=str(model) if model else None,
                error=f"{type(exc).__name__}: {exc}",
                raw=envelope if isinstance(envelope, dict) else None,
                command=cmd,
            )


def get_driver(name: str, *, evolution_lab_root: Path | None = None) -> ResearchDriver:
    if name in {"agy", "antigravity"}:
        return AgyResearchDriver()
    return DeterministicSearchDriver(evolution_lab_root=evolution_lab_root)
