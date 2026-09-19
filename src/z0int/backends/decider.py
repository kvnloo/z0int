"""Decider-2B DecisionBackend — Mapika/decider-2b via bundled upstream `decider` runtime."""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import (
    BackendCapabilities,
    BackendHealth,
    DecisionAnswer,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
)


@dataclass
class _Loaded:
    decider: Any
    model_dir: str
    load_ms: float


def _default_device() -> str:
    return os.environ.get("Z0INT_DECIDER_DEVICE", "cuda")


def _use_graphs() -> bool | None:
    raw = os.environ.get("Z0INT_DECIDER_USE_GRAPHS")
    if raw is None:
        return None
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _resolve_model_dir(*, hf: str, revision: str) -> Path:
    from z0int.models_mgmt import model_cached

    from huggingface_hub import snapshot_download

    if model_cached(hf, revision):
        return Path(snapshot_download(repo_id=hf, revision=revision, local_files_only=True))
    return Path(snapshot_download(repo_id=hf, revision=revision))


def _bootstrap_decider_runtime(model_dir: Path) -> None:
    root = str(model_dir.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def _runtime_import_error() -> str | None:
    try:
        import torch  # noqa: F401
    except ImportError as exc:
        return f"torch not installed: {exc}"
    return None


def _normalize_probs(probs: dict[str, float]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for key, val in probs.items():
        fval = float(val)
        if not math.isfinite(fval) or fval < 0:
            raise ValueError(f"invalid probability for {key!r}: {val!r}")
        cleaned[str(key)] = fval
    total = sum(cleaned.values())
    if total <= 0:
        raise ValueError("empty probability mass from decider")
    return {k: v / total for k, v in cleaned.items()}


def _question_to_decider(q: DecisionQuestion) -> dict[str, Any]:
    if q.type == "boolean":
        return {
            "type": "noul",
            "instructions": q.instructions,
            "criteria": {
                "false": q.false_criterion or "no, the statement does not hold",
                "true": q.true_criterion or "yes, the statement holds",
            },
        }
    if q.type == "choice":
        return {
            "type": "choice",
            "instructions": q.instructions,
            "criteria": {o.id: o.description for o in q.options},
        }
    return {
        "type": "score",
        "instructions": q.instructions,
        "criteria": list(q.levels),
    }


def _answer_from_decider(q: DecisionQuestion, raw: dict[str, Any]) -> DecisionAnswer:
    qtype = raw.get("type")
    confidence = raw.get("confidence")
    conf_val = float(confidence) if confidence is not None else None

    if qtype == "noul" or q.type == "boolean":
        p_true = float(raw.get("noul", 0.5))
        probs = _normalize_probs({"false": 1.0 - p_true, "true": p_true})
        return DecisionAnswer(
            question_id=q.id,
            type="boolean",
            probabilities=probs,
            value=p_true >= 0.5,
            confidence=conf_val,
        )

    if qtype == "choice" or q.type == "choice":
        probs_raw = raw.get("probabilities") or {}
        probs = _normalize_probs({str(k): float(v) for k, v in probs_raw.items()})
        choice = str(raw.get("choice") or max(probs, key=probs.get))
        return DecisionAnswer(
            question_id=q.id,
            type="choice",
            probabilities=probs,
            value=choice,
            confidence=conf_val,
        )

    probs_raw = raw.get("probabilities") or {}
    probs = _normalize_probs({str(k): float(v) for k, v in probs_raw.items()})
    score_val = raw.get("score")
    if score_val is None and probs:
        score_val = sum(int(k) * v for k, v in probs.items())
    return DecisionAnswer(
        question_id=q.id,
        type="score",
        probabilities=probs,
        value=float(score_val if score_val is not None else 0.0),
        confidence=conf_val,
    )


class DeciderBackend:
    ID = "decider"

    def __init__(
        self,
        *,
        model_id: str = "decider_2b",
        hf: str,
        revision: str,
        device: str | None = None,
        model_dir: Path | None = None,
        use_graphs: bool | None = None,
    ):
        self.model_id = model_id
        self.hf = hf
        self.revision = revision
        self.device = device or _default_device()
        self.use_graphs = use_graphs if use_graphs is not None else _use_graphs()
        self._model_dir = model_dir
        self._loaded: _Loaded | None = None

    @classmethod
    def for_manifest_id(cls, manifest_id: str = "decider_2b") -> "DeciderBackend":
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
            kind="calibrated_decision",
            description="Mapika Decider-2B one-pass typed probabilities (Qwen3.5-2B-Base)",
            supports_boolean=True,
            supports_choice=True,
            supports_score=True,
            max_choice_options=255,
            max_score_levels=10,
            supports_batch_questions=True,
            local=True,
        )

    def _model_path(self) -> Path:
        if self._model_dir is not None:
            return self._model_dir.expanduser()
        return _resolve_model_dir(hf=self.hf, revision=self.revision)

    def health(self, *, load: bool = False) -> BackendHealth:
        err = _runtime_import_error()
        if err:
            return BackendHealth(
                id=self.ID,
                configured=True,
                ready=False,
                loaded=False,
                model=self.model_id,
                detail=err,
                diagnostics={"hf": self.hf, "manifest_id": self.model_id, "revision": self.revision},
            )
        try:
            path = self._model_path()
            present = (
                path.is_dir()
                and (path / "model.safetensors").is_file()
                and (path / "decider" / "infer.py").is_file()
            )
        except Exception as exc:  # noqa: BLE001
            return BackendHealth(
                id=self.ID,
                configured=True,
                ready=False,
                loaded=False,
                model=self.model_id,
                detail=f"weights probe failed: {exc}",
                diagnostics={"hf": self.hf, "manifest_id": self.model_id, "revision": self.revision},
            )
        if load:
            try:
                self._ensure_loaded()
                loaded = True
                detail = f"weights loaded on {self.device}"
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
            checkpoint=str(path) if present else None,
            diagnostics={
                "hf": self.hf,
                "manifest_id": self.model_id,
                "revision": self.revision,
                "device": self.device,
                "runtime": "decider",
                "base_model": "Qwen/Qwen3.5-2B-Base",
                "license": "apache-2.0",
                "commercial_use": True,
                "readout": "single-pass option-letter logits at answer slots",
            },
        )

    def _ensure_loaded(self) -> _Loaded:
        if self._loaded is not None:
            return self._loaded
        import_err = _runtime_import_error()
        if import_err:
            raise RuntimeError(import_err)
        path = self._model_path()
        if not path.is_dir():
            raise FileNotFoundError(f"decider checkpoint not found: {path}")
        _bootstrap_decider_runtime(path)
        from decider.infer import Decider

        t0 = time.perf_counter()
        kwargs: dict[str, Any] = {"device": self.device}
        if self.use_graphs is not None:
            kwargs["use_graphs"] = self.use_graphs
        decider = Decider(str(path), **kwargs)
        load_ms = (time.perf_counter() - t0) * 1000.0
        self.device = str(decider.dev)
        self._loaded = _Loaded(decider=decider, model_dir=str(path), load_ms=load_ms)
        return self._loaded

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        loaded = self._ensure_loaded()
        start = time.perf_counter()
        questions = {q.id: _question_to_decider(q) for q in request.questions}
        raw = loaded.decider.system_one(request.state, questions)
        answers: list[DecisionAnswer] = []
        raw_probs: dict[str, Any] = {}
        for q in request.questions:
            ans_raw = (raw.get("answers") or {}).get(q.id)
            if not isinstance(ans_raw, dict):
                raise ValueError(f"decider returned no answer for question {q.id!r}")
            raw_probs[q.id] = dict(ans_raw.get("probabilities") or {})
            answers.append(_answer_from_decider(q, ans_raw))
        usage = raw.get("usage") or {}
        return DecisionResult(
            backend=self.ID,
            model=self.model_id,
            revision=self.revision,
            answers=tuple(answers),
            latency_ms=(time.perf_counter() - start) * 1000.0,
            diagnostics={
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens", 0),
                "device": self.device,
                "model_dir": loaded.model_dir,
                "load_ms": loaded.load_ms,
                "runtime": "decider",
                "runtime_model": raw.get("model"),
                "raw_probabilities": raw_probs,
                "probability_status": "upstream rounded probabilities renormalized once for contract validation",
                "readout": "single forward pass; softmax over option-letter logits at answer slots",
            },
        )
