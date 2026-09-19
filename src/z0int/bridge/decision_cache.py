"""Per-generation resident DecisionBackend cache for the z0int bridge.

Loads backends once (background prewarm), reuses the exact instance for evaluate().
Status is observational and must never trigger a load.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from z0int.backends.base import DecisionBackend, DecisionRequest, result_to_dict


class BackendLoadState(str, Enum):
    UNLOADED = "unloaded"
    WARMING = "warming"
    READY = "ready"
    FAILED = "failed"


@dataclass
class BackendSlot:
    backend_id: str
    state: BackendLoadState = BackendLoadState.UNLOADED
    backend: DecisionBackend | None = None
    device: str | None = None
    model: str | None = None
    revision: str | None = None
    loaded_at: float | None = None
    load_ms: float | None = None
    error: str | None = None
    requests: int = 0
    failures: int = 0
    last_inference_ms: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _warm_thread: threading.Thread | None = field(default=None, repr=False)


def _create_backend(backend_id: str) -> DecisionBackend:
    # Prefer explicit Decider path so this slice works even if CLI registry
    # has not yet advertised decider_2b.
    if backend_id in {"decider_2b", "decider"}:
        from z0int.backends.decider import DeciderBackend

        return DeciderBackend.for_manifest_id("decider_2b")
    from z0int.backends.registry import create_backend

    return create_backend(backend_id)


class ResidentDecisionCache:
    """Owns DecisionBackend residency for one BridgeRuntime / generation."""

    def __init__(self) -> None:
        self._slots: dict[str, BackendSlot] = {}
        self._slots_lock = threading.Lock()

    def _slot(self, backend_id: str) -> BackendSlot:
        with self._slots_lock:
            slot = self._slots.get(backend_id)
            if slot is None:
                slot = BackendSlot(backend_id=backend_id)
                self._slots[backend_id] = slot
            return slot

    def status(self) -> dict[str, Any]:
        """Observational only — never loads."""
        with self._slots_lock:
            ids = list(self._slots)
        out: dict[str, Any] = {}
        for bid in ids:
            slot = self._slot(bid)
            with slot._lock:
                out[bid] = {
                    "state": slot.state.value,
                    "device": slot.device,
                    "model": slot.model,
                    "revision": slot.revision,
                    "loaded_at": slot.loaded_at,
                    "load_ms": slot.load_ms,
                    "requests": slot.requests,
                    "failures": slot.failures,
                    "last_inference_ms": slot.last_inference_ms,
                    "error": slot.error,
                }
        return out

    def warm(self, backend_id: str) -> dict[str, Any]:
        """Non-blocking prewarm. Never waits for model load."""
        slot = self._slot(backend_id)
        with slot._lock:
            if slot.state is BackendLoadState.READY:
                return {
                    "ok": True,
                    "backend": backend_id,
                    "status": "ready",
                    "state": slot.state.value,
                    "load_ms": slot.load_ms,
                    "device": slot.device,
                }
            if slot.state is BackendLoadState.WARMING:
                return {
                    "ok": True,
                    "backend": backend_id,
                    "status": "warming",
                    "state": slot.state.value,
                }
            if slot.state is BackendLoadState.FAILED:
                # Allow retry from failed.
                pass
            slot.state = BackendLoadState.WARMING
            slot.error = None
            thread = threading.Thread(
                target=self._warm_worker,
                args=(backend_id,),
                name=f"z0int-warm-{backend_id}",
                daemon=True,
            )
            slot._warm_thread = thread
            thread.start()
            return {
                "ok": True,
                "backend": backend_id,
                "status": "warming",
                "state": BackendLoadState.WARMING.value,
            }

    def _warm_worker(self, backend_id: str) -> None:
        slot = self._slot(backend_id)
        t0 = time.perf_counter()
        try:
            backend = _create_backend(backend_id)
            # Force weight load without evaluating a decision.
            health = backend.health(load=True)
            if not health.loaded:
                raise RuntimeError(health.detail or "backend health load failed")
            # Absorb first-inference CUDA/kernel warmup into prewarm so READY
            # means steady-state tens-of-ms latency, not just weights resident.
            try:
                from z0int.backends.base import DecisionOption, DecisionQuestion, DecisionRequest

                warmup_req = DecisionRequest(
                    state={
                        "granted_bytes": 512,
                        "pattern_hits": 1,
                        "grant_count": 1,
                        "complexity": "low",
                        "question_sha256": "0" * 64,
                        "question_chars": 1,
                    },
                    questions=(
                        DecisionQuestion(
                            id="decision",
                            type="choice",
                            instructions="warmup",
                            options=(
                                DecisionOption(id="native", description="native"),
                                DecisionOption(id="worker", description="worker"),
                                DecisionOption(id="abstain", description="abstain"),
                            ),
                        ),
                    ),
                )
                backend.evaluate(warmup_req)
            except Exception:
                # Weight load succeeded; inference warmup is best-effort.
                pass
            load_ms = (time.perf_counter() - t0) * 1000.0
            with slot._lock:
                slot.backend = backend
                slot.state = BackendLoadState.READY
                slot.load_ms = load_ms
                slot.loaded_at = time.time()
                slot.device = str((health.diagnostics or {}).get("device") or getattr(backend, "device", None) or "")
                slot.model = health.model or getattr(backend, "model_id", backend_id)
                slot.revision = str(getattr(backend, "revision", "") or "") or None
                slot.error = None
        except Exception as exc:  # noqa: BLE001
            with slot._lock:
                slot.state = BackendLoadState.FAILED
                slot.backend = None
                slot.error = str(exc)[:800]
                slot.load_ms = (time.perf_counter() - t0) * 1000.0
                slot.failures += 1

    def evaluate(
        self,
        *,
        backend_id: str,
        request: DecisionRequest,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate if READY; return warming/failed quickly otherwise. Never blocks on load."""
        slot = self._slot(backend_id)
        queue_wait_started = time.perf_counter()

        # Fast path state check without holding evaluate lock across load.
        with slot._lock:
            state = slot.state
            if state is BackendLoadState.UNLOADED:
                # Kick warm and fail-open immediately.
                pass
            if state is BackendLoadState.WARMING:
                return {
                    "ok": False,
                    "status": "warming",
                    "backend": backend_id,
                    "capability_id": capability_id,
                    "error": "backend_warming",
                    "runtime": {
                        "residency": "warming",
                        "queue_ms": 0.0,
                        "inference_ms": None,
                        "load_ms": slot.load_ms,
                    },
                }
            if state is BackendLoadState.FAILED:
                return {
                    "ok": False,
                    "status": "error",
                    "backend": backend_id,
                    "capability_id": capability_id,
                    "error": slot.error or "backend_failed",
                    "runtime": {
                        "residency": "failed",
                        "queue_ms": 0.0,
                        "inference_ms": None,
                        "load_ms": slot.load_ms,
                    },
                }
            if state is BackendLoadState.UNLOADED:
                should_warm = True
            else:
                should_warm = False
                backend = slot.backend
                assert backend is not None
        if should_warm:
            # Must not hold slot lock — warm() acquires it.
            self.warm(backend_id)
            return {
                "ok": False,
                "status": "warming",
                "backend": backend_id,
                "capability_id": capability_id,
                "error": "backend_unloaded_warmup_started",
                "runtime": {
                    "residency": "warming",
                    "queue_ms": 0.0,
                    "inference_ms": None,
                    "load_ms": None,
                },
            }

        # Serialize model evaluation on this slot (measure queue time).
        acquired = slot._lock.acquire(blocking=True)
        queue_ms = (time.perf_counter() - queue_wait_started) * 1000.0
        try:
            if not acquired:
                return {
                    "ok": False,
                    "status": "error",
                    "backend": backend_id,
                    "error": "lock_failed",
                }
            if slot.state is not BackendLoadState.READY or slot.backend is None:
                return {
                    "ok": False,
                    "status": slot.state.value if isinstance(slot.state, BackendLoadState) else "error",
                    "backend": backend_id,
                    "error": "backend_not_ready",
                    "runtime": {"residency": slot.state.value, "queue_ms": queue_ms},
                }
            backend = slot.backend
            t0 = time.perf_counter()
            try:
                result = backend.evaluate(request)
            except Exception as exc:  # noqa: BLE001
                slot.failures += 1
                return {
                    "ok": False,
                    "status": "error",
                    "backend": backend_id,
                    "capability_id": capability_id,
                    "error": str(exc)[:800],
                    "runtime": {
                        "residency": "warm",
                        "queue_ms": queue_ms,
                        "inference_ms": (time.perf_counter() - t0) * 1000.0,
                        "load_ms": slot.load_ms,
                    },
                }
            inference_ms = (time.perf_counter() - t0) * 1000.0
            slot.requests += 1
            slot.last_inference_ms = inference_ms
            payload = result_to_dict(result)
            return {
                "ok": True,
                "status": "ok",
                "backend": backend_id,
                "capability_id": capability_id,
                "result": payload,
                "runtime": {
                    "residency": "warm",
                    "queue_ms": queue_ms,
                    "inference_ms": inference_ms,
                    "load_ms": slot.load_ms,
                    "device": slot.device,
                    "model": slot.model,
                    "revision": slot.revision,
                    "backend_loaded": True,
                },
            }
        finally:
            slot._lock.release()
