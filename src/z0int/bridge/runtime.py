"""Bridge turn open/close logic (resident; no per-turn process spawn for z0int).

Production preflight is owned by z0intelligence (no Evolution Lab on live path).
Kerdoios remains optional residual planner via subprocess when configured.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from z0int import paths
from z0int.bridge import generation as gen
from z0int.bridge.decision_cache import ResidentDecisionCache
from z0int.bridge.protocol import (
    BRIDGE_PROTOCOL,
    SCHEMA_EVENT,
    SCHEMA_HEART,
    SCHEMA_OPEN,
    compute_build_id,
    repo_root,
)
from z0int.receipt import append_receipt, close_turn


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _stream_dir() -> Path:
    d = paths.home() / "stream"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_key(session_id: str | None, omp_pid: int | None = None) -> str:
    sid = (session_id or "unknown").replace("/", "_")[:120]
    pid = omp_pid if omp_pid is not None else os.getppid()
    return f"{sid}__pid{pid}"


def session_open_path(session_id: str | None, omp_pid: int | None = None) -> Path:
    key = session_key(session_id, omp_pid)
    d = _stream_dir() / "sessions" / key
    d.mkdir(parents=True, exist_ok=True)
    return d / "open.json"


def write_session_open(row: dict[str, Any], session_id: str | None, omp_pid: int | None = None) -> Path:
    path = session_open_path(session_id, omp_pid)
    path.write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_session_open(session_id: str | None, omp_pid: int | None = None) -> dict[str, Any] | None:
    path = session_open_path(session_id, omp_pid)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def clear_session_open(session_id: str | None, omp_pid: int | None = None) -> None:
    path = session_open_path(session_id, omp_pid)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _meta_stamp(
    *,
    generation: int,
    instance_id: str,
    build_id: str,
    session_id: str | None,
    omp_pid: int | None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "bridge_protocol": BRIDGE_PROTOCOL,
        "bridge_generation": generation,
        "bridge_instance_id": instance_id,
        "bridge_build_id": build_id,
        "omp_session_id": session_id,
        "omp_pid": omp_pid,
        "trace_id": trace_id,
    }


def _run_json(cmd: list[str], cwd: str | Path, timeout: float) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    raw = (proc.stdout or "").strip()
    if not raw:
        return {"ok": False, "error": proc.stderr or f"exit_{proc.returncode}"}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return {"ok": False, "error": "json_parse", "raw": raw[:400]}


def preflight(prompt: str) -> dict[str, Any]:
    """z0intelligence-owned production preflight — never imports Evolution Lab."""
    from z0int.preflight import preflight_dict

    return preflight_dict(prompt)


def kerdoios_plan(capability_id: str, work: dict[str, Any] | None) -> dict[str, Any] | None:
    if not work:
        return None
    kerd_root = Path(
        os.environ.get("KERDOIOS_ROOT")
        or "/home/kvn/.hermes/profiles/chiefstaff/plugins/kerdoios"
    )
    kerd_py = (
        os.environ.get("KERDOIOS_PYTHON")
        or os.environ.get("EVOLUTION_LAB_PYTHON")
        or "/workspace/evolution-lab/.venv/bin/python"
    )
    args = [
        kerd_py,
        "-m",
        "kerdoios",
        "plan",
        "--capability-id",
        capability_id,
        "--observed",
        "--workers",
        "1",
        "--mode",
        str(work.get("mode") or "balanced"),
    ]
    if isinstance(work.get("coding"), (int, float)):
        args.extend(["--coding", str(work["coding"])])
    if isinstance(work.get("reasoning"), (int, float)):
        args.extend(["--reasoning", str(work["reasoning"])])
    return _run_json(args, kerd_root, 12.0)


def kerdoios_record(
    *,
    provider: str,
    model: str,
    capability_id: str,
    completed: bool,
    input_tokens: int | None,
    output_tokens: int | None,
) -> None:
    kerd_root = Path(
        os.environ.get("KERDOIOS_ROOT")
        or "/home/kvn/.hermes/profiles/chiefstaff/plugins/kerdoios"
    )
    kerd_py = (
        os.environ.get("KERDOIOS_PYTHON")
        or os.environ.get("EVOLUTION_LAB_PYTHON")
        or "/workspace/evolution-lab/.venv/bin/python"
    )
    args = [
        kerd_py,
        "-m",
        "kerdoios",
        "record",
        "--provider",
        provider,
        "--model",
        model,
        "--task-type",
        "coding",
        "--capability-id",
        capability_id,
        "--cost",
        "0",
    ]
    if completed:
        args.append("--completed")
    if input_tokens is not None:
        args.extend(["--input-tokens", str(input_tokens)])
    if output_tokens is not None:
        args.extend(["--output-tokens", str(output_tokens)])
    _run_json(args, kerd_root, 5.0)


class BridgeRuntime:
    def __init__(
        self,
        *,
        generation: int,
        instance_id: str | None = None,
        build_id: str | None = None,
    ) -> None:
        self.generation = int(generation)
        self.instance_id = instance_id or uuid.uuid4().hex[:12]
        self.build_id = build_id or compute_build_id()
        self.started_at = time.time()
        self.closing: set[str] = set()
        self.draining = False
        # Per-generation resident DecisionBackend instances (not shared across reloads).
        self._decision_backends = ResidentDecisionCache()

    def identity(self) -> dict[str, Any]:
        return {
            "protocol": BRIDGE_PROTOCOL,
            "generation": self.generation,
            "instance_id": self.instance_id,
            "build_id": self.build_id,
            "started_at": self.started_at,
            "draining": self.draining,
            "pid": os.getpid(),
            "repo": str(repo_root()),
        }

    def self_check(self) -> dict[str, Any]:
        errors: list[str] = []
        try:
            from z0int.receipt import append_receipt as _  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            errors.append(f"receipt_import:{exc}")
        try:
            paths.ensure_layout()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"layout:{exc}")
        try:
            compute_build_id()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"build_id:{exc}")
        # Observational only — never load DecisionBackends here.
        return {
            "ok": not errors,
            "errors": errors,
            "decision_backends": self._decision_backends.status(),
            **self.identity(),
        }

    def decision_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "decision_backends": self._decision_backends.status(),
            **self.identity(),
        }

    def decision_warm(self, *, backend: str) -> dict[str, Any]:
        if self.draining:
            return {"ok": False, "error": "draining", **self.identity()}
        out = self._decision_backends.warm(backend)
        out.update(self.identity())
        return out

    def decision(
        self,
        *,
        backend: str,
        request_mapping: dict[str, Any],
        capability_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if self.draining:
            return {"ok": False, "error": "draining", "status": "error", **self.identity()}
        from z0int.backends.base import request_from_mapping

        req = request_from_mapping(request_mapping)
        out = self._decision_backends.evaluate(
            backend_id=backend,
            request=req,
            capability_id=capability_id,
        )
        out.update(self.identity())
        if trace_id:
            out["trace_id"] = trace_id
        return out

    def _maybe_quarantine(self, row: dict[str, Any], writer_generation: int | None) -> bool:
        if gen.is_stale(writer_generation):
            gen.quarantine(row, reason=f"stale_generation:{writer_generation}")
            return True
        return False

    def turn_open(
        self,
        *,
        trace_id: str,
        session_id: str | None,
        prompt: str,
        omp_pid: int | None = None,
        writer_generation: int | None = None,
    ) -> dict[str, Any]:
        if self.draining:
            return {"ok": False, "error": "draining"}
        t0 = time.perf_counter()
        stamp = _meta_stamp(
            generation=self.generation,
            instance_id=self.instance_id,
            build_id=self.build_id,
            session_id=session_id,
            omp_pid=omp_pid,
            trace_id=trace_id,
        )
        if writer_generation is not None and writer_generation != self.generation:
            # open must be current generation only
            row = {"op": "turn_open", "error": "generation_mismatch", **stamp, "writer_generation": writer_generation}
            gen.quarantine(row, reason="open_generation_mismatch")
            return {"ok": False, "error": "generation_mismatch", **stamp}

        pf = preflight(prompt)
        capability_id = pf.get("capability_id") if isinstance(pf.get("capability_id"), str) else "coding.next_action"
        route = pf.get("route") if isinstance(pf.get("route"), str) else "model"
        plan = None
        if route == "model":
            wr = pf.get("work_requirement") if isinstance(pf.get("work_requirement"), dict) else None
            plan = kerdoios_plan(str(capability_id), wr)

        latency_ms = (time.perf_counter() - t0) * 1000.0
        wr = pf.get("work_requirement") if isinstance(pf.get("work_requirement"), dict) else {}
        cf = pf.get("counterfactual") if isinstance(pf.get("counterfactual"), dict) else {}
        baseline_in = pf.get("baseline_input_tokens")
        if not isinstance(baseline_in, (int, float)):
            baseline_in = wr.get("estimated_input_tokens") if isinstance(wr, dict) else None
        if not isinstance(baseline_in, (int, float)):
            baseline_in = cf.get("estimated_input_tokens") if isinstance(cf, dict) else None
        baseline_out = pf.get("baseline_output_tokens")
        if not isinstance(baseline_out, (int, float)):
            baseline_out = wr.get("estimated_output_tokens") if isinstance(wr, dict) else None
        if not isinstance(baseline_out, (int, float)):
            baseline_out = cf.get("estimated_output_tokens") if isinstance(cf, dict) else None
        avoided = pf.get("estimated_frontier_tokens_avoided")
        if not isinstance(avoided, (int, float)):
            avoided = 0
        is_local = route in ("local", "local_model", "routine", "specialist")
        plan_provider = None
        plan_model = None
        if isinstance(plan, dict) and isinstance(plan.get("placements"), list) and plan["placements"]:
            top = plan["placements"][0]
            if isinstance(top, dict):
                if isinstance(top.get("provider"), str):
                    plan_provider = top["provider"]
                if isinstance(top.get("model"), str):
                    plan_model = top["model"]

        receipt = {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": trace_id,
            "session_id": session_id,
            "capability_id": capability_id,
            "provider": "local_mb" if is_local else (plan_provider or ("kerdoios_plan" if plan else "frontier")),
            "model": "mb_local" if is_local else plan_model,
            "prediction": pf.get("label") if isinstance(pf.get("label"), str) else pf.get("prediction"),
            "confidence": pf.get("p") if isinstance(pf.get("p"), (int, float)) else pf.get("confidence"),
            "action_taken": route,
            "route": route,
            "execution": "log_only",
            "outcome": None,
            "input_tokens": 0 if is_local else None,
            "output_tokens": 0 if is_local else None,
            "baseline_input_tokens": baseline_in,
            "baseline_output_tokens": baseline_out,
            "estimated_frontier_tokens_avoided": avoided,
            "measured_frontier_tokens": None,
            "latency_ms": latency_ms,
            "fallbacks": 0,
            "ts": time.time(),
            **stamp,
        }
        row = {
            "schema": SCHEMA_EVENT,
            "ts": receipt["ts"],
            "prompt": prompt[:400],
            "preflight": pf,
            "kerdoios_plan": plan,
            "latency_ms": latency_ms,
            "execution": "log_only",
            "receipt": receipt,
            **stamp,
        }
        if self._maybe_quarantine(row, writer_generation):
            return {"ok": False, "error": "quarantined_stale", **stamp}

        _append(_stream_dir() / "bridge.jsonl", row)
        try:
            append_receipt(receipt)
        except Exception:
            pass
        _append(
            paths.home() / "shadow" / "preflight.jsonl",
            {
                "ts": receipt["ts"],
                "trace_id": trace_id,
                "route": route,
                "capability_id": capability_id,
                "avoided": avoided,
                "plan_ok": (plan.get("ok") is not False and not plan.get("error")) if isinstance(plan, dict) else None,
                **stamp,
            },
        )
        open_row = {
            "schema": SCHEMA_OPEN,
            "trace_id": trace_id,
            "session_id": session_id,
            "capability_id": capability_id,
            "route": route,
            "baseline_input_tokens": baseline_in,
            "baseline_output_tokens": baseline_out,
            "provider": receipt["provider"],
            "ts": receipt["ts"],
            "closed": False,
            **stamp,
        }
        _append(_stream_dir() / "open_turns.jsonl", open_row)
        write_session_open(open_row, session_id, omp_pid)
        # Compat: last_open remains session-scoped path marker, not global authority.
        # Still write a pointer file under sessions only — do not use global last_open as owner.
        return {"ok": True, "trace_id": trace_id, "receipt": receipt, "open": open_row, **stamp}

    def turn_close(
        self,
        *,
        trace_id: str,
        session_id: str | None,
        omp_pid: int | None = None,
        measured: float | int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        execution_completed: bool = True,
        verified_success: bool | None = None,
        source: str = "bridge_turn_end",
        verification_source: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        writer_generation: int | None = None,
    ) -> dict[str, Any]:
        stamp = _meta_stamp(
            generation=self.generation,
            instance_id=self.instance_id,
            build_id=self.build_id,
            session_id=session_id,
            omp_pid=omp_pid,
            trace_id=trace_id,
        )
        # Prefer explicit session open ownership
        open_row = read_session_open(session_id, omp_pid)
        if open_row and open_row.get("trace_id") != trace_id:
            # wrong session open — still allow close of explicit trace, but note
            stamp = {**stamp, "session_open_mismatch": open_row.get("trace_id")}
        if open_row and open_row.get("closed") is True and open_row.get("trace_id") == trace_id:
            return {"ok": True, "already_closed": True, "trace_id": trace_id, **stamp}
        if trace_id in self.closing:
            return {"ok": True, "already_closed": True, "trace_id": trace_id, **stamp}
        self.closing.add(trace_id)

        # Close may carry a different generation than open — record both.
        open_gen = open_row.get("bridge_generation") if open_row else None
        if open_gen is not None and int(open_gen) != self.generation:
            stamp = {**stamp, "open_bridge_generation": open_gen, "close_bridge_generation": self.generation}

        try:
            from z0int.receipt import Outcome

            oc = Outcome(
                execution_completed=execution_completed,
                verified_success=verified_success,
                source=source,
                verification_source=verification_source,
            )
            closed = close_turn(
                trace_id,
                measured_frontier_tokens=int(measured) if measured is not None else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider=provider,
                model=model,
                outcome=oc,
                source=source,
            )
            if "ok" not in closed:
                closed = {**closed, "ok": True}
        except Exception as exc:  # noqa: BLE001
            closed = {"ok": False, "error": str(exc), "trace_id": trace_id}

        ok = not closed.get("error") and closed.get("ok") is not False
        heart = {
            "schema": SCHEMA_HEART,
            "ts": time.time(),
            "ok": ok,
            "source": source,
            "measured": measured,
            "provider": provider,
            "model": model,
            "execution_completed": execution_completed,
            "verified_success": verified_success,
            "outcome_tier": (closed.get("outcome_join") or {}).get("outcome_tier")
            if isinstance(closed.get("outcome_join"), dict)
            else None,
            "error": closed.get("error"),
            "writer_generation": writer_generation,
            **stamp,
        }
        if gen.is_stale(writer_generation):
            gen.quarantine(heart, reason="close_stale_generation")
        else:
            _append(_stream_dir() / "bridge_heart.jsonl", heart)

        if ok and open_row and open_row.get("trace_id") == trace_id:
            open_row = {**open_row, "closed": True, "closed_ts": time.time(), "measured": measured, "source": source}
            write_session_open(open_row, session_id, omp_pid)

        # Kerdoios economics: completed only when verified
        try:
            cap = (
                open_row.get("capability_id")
                if isinstance(open_row, dict) and isinstance(open_row.get("capability_id"), str)
                else "coding.next_action"
            )
            kerdoios_record(
                provider=provider or "omp_bridge",
                model=model or "unknown",
                capability_id=str(cap),
                completed=verified_success is True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception:
            pass

        # Autoresearch: only verified_success=true with verifier identity
        try:
            if verified_success is True:
                from z0int.autoresearch.queue import enqueue_trace

                enqueue_trace(
                    trace_id,
                    verified_success=True,
                    verifier_id=verification_source or source,
                    payload={
                        "snapshot": {
                            "task_snapshot_id": trace_id,
                            "required_ops": ["exact_path"],
                            "baseline_wall_ms": 800,
                            "frontier_tokens": int(measured or 0),
                        }
                    },
                )
        except Exception:
            pass

        return {"ok": ok, "trace_id": trace_id, "closed": closed, **stamp}

    def mark_drain(self) -> None:
        self.draining = True
