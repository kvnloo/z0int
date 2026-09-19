"""OpenJev direct-logit DecisionBackend for manifest openjev_* models."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .base import (
    BackendCapabilities,
    BackendHealth,
    DecisionAnswer,
    DecisionRequest,
    DecisionResult,
)


@dataclass
class _Loaded:
    model: Any
    tokenizer: Any
    metadata: dict[str, Any]


class OpenJevDirectBackend:
    ID = "openjev_direct"

    def __init__(self, *, model_id: str, hf: str, revision: str):
        self.model_id = model_id
        self.hf = hf
        self.revision = revision
        self._loaded: _Loaded | None = None

    @classmethod
    def for_manifest_id(cls, manifest_id: str) -> "OpenJevDirectBackend":
        from z0int.models_mgmt import load_manifest

        meta = (load_manifest().get("models") or {}).get(manifest_id) or {}
        hf = str(meta.get("hf") or "")
        rev = str(meta.get("revision") or "")
        if not hf or not rev:
            raise ValueError(f"manifest {manifest_id!r} missing hf/revision")
        return cls(model_id=manifest_id, hf=hf, revision=rev)

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            id=self.ID,
            kind="direct_option_logits",
            description=f"OpenJev direct logits ({self.model_id})",
            supports_boolean=True,
            supports_choice=True,
            supports_score=False,
            max_choice_options=16,
            max_score_levels=0,
            supports_batch_questions=True,
            local=True,
        )

    def health(self, *, load: bool = False) -> BackendHealth:
        from z0int.models_mgmt import model_present

        meta = {"hf": self.hf, "revision": self.revision, "type": "hf"}
        present = model_present(self.model_id, meta)
        if load:
            try:
                self._ensure_loaded()
                loaded = True
                detail = "weights loaded"
            except Exception as exc:  # noqa: BLE001
                loaded = False
                detail = f"load failed: {exc}"
        else:
            loaded = False
            detail = "weights present" if present else "weights not cached locally"
        return BackendHealth(
            id=self.ID,
            configured=True,
            ready=present,
            loaded=loaded,
            model=self.model_id,
            detail=detail,
            diagnostics={"hf": self.hf, "manifest_id": self.model_id, "revision": self.revision},
        )

    def _ensure_loaded(self) -> _Loaded:
        if self._loaded is not None:
            return self._loaded
        from openjev_phase1.core import load_causal_model
        from openjev_phase1.direct import score as direct_score

        self._direct_score = direct_score
        model, tokenizer, metadata = load_causal_model(self.hf, self.revision)
        self._loaded = _Loaded(model=model, tokenizer=tokenizer, metadata=metadata)
        return self._loaded

    def _row_from_question(self, request: DecisionRequest, q) -> dict[str, Any]:
        if q.type == "boolean":
            options = [
                {"id": "false", "description": q.false_criterion or "false"},
                {"id": "true", "description": q.true_criterion or "true"},
            ]
        elif q.type == "choice":
            options = [{"id": o.id, "description": o.description} for o in q.options]
        else:
            options = [{"id": lvl, "description": lvl} for lvl in q.levels]
        return {
            "id": q.id,
            "state": request.state,
            "question": q.instructions,
            "options": options,
        }

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        loaded = self._ensure_loaded()
        start = time.perf_counter()
        answers: list[DecisionAnswer] = []
        input_tokens = 0
        for q in request.questions:
            row = self._row_from_question(request, q)
            scored = self._direct_score(loaded.model, loaded.tokenizer, row, loaded.metadata)
            input_tokens += int(scored.get("input_tokens") or 0)
            probs_list = scored["probabilities"]
            option_ids = scored["option_ids"]
            distribution = {oid: float(p) for oid, p in zip(option_ids, probs_list)}
            best_idx = max(range(len(probs_list)), key=probs_list.__getitem__)
            if q.type == "boolean":
                value: bool | str | float = option_ids[best_idx] == "true"
            elif q.type == "choice":
                value = option_ids[best_idx]
            else:
                value = float(best_idx)
            answers.append(
                DecisionAnswer(
                    question_id=q.id,
                    type=q.type,
                    probabilities=distribution,
                    value=value,
                    confidence=float(max(probs_list)),
                )
            )
        return DecisionResult(
            backend=self.ID,
            model=self.model_id,
            revision=self.revision,
            answers=tuple(answers),
            latency_ms=(time.perf_counter() - start) * 1000.0,
            diagnostics={
                "input_tokens": input_tokens,
                "hf": self.hf,
                "readout": "native last-position logits restricted to declared answer slots",
            },
        )
