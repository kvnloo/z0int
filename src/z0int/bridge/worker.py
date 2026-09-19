"""Resident JSONL bridge worker: python -u -m z0int.bridge.worker

Protocol: one JSON object per line on stdin; one JSON response per line on stdout.
Request ids are required for concurrent ops.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

from z0int.bridge.generation import publish_current
from z0int.bridge.protocol import BRIDGE_PROTOCOL, OPS, compute_build_id
from z0int.bridge.runtime import BridgeRuntime


def _respond(req_id: str | None, body: dict[str, Any]) -> None:
    out = {"id": req_id, **body}
    sys.stdout.write(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def serve(generation: int | None = None) -> int:
    gen = int(generation if generation is not None else os.environ.get("Z0INT_BRIDGE_GENERATION", "1"))
    instance = os.environ.get("Z0INT_BRIDGE_INSTANCE") or uuid.uuid4().hex[:12]
    build = compute_build_id()
    rt = BridgeRuntime(generation=gen, instance_id=instance, build_id=build)
    # Do not publish current here — shim publishes only after successful handshake + swap.
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request must be object")
            req_id = req.get("id")
            op = req.get("op")
            if op not in OPS:
                _respond(req_id if isinstance(req_id, str) else None, {"ok": False, "error": f"unknown_op:{op}"})
                continue
            if op == "hello":
                _respond(req_id, {"ok": True, **rt.identity()})
                continue
            if op == "self_check":
                _respond(req_id, rt.self_check())
                continue
            if op == "status":
                _respond(req_id, rt.decision_status())
                continue
            if op == "decision_warm":
                payload = req.get("payload") if isinstance(req.get("payload"), dict) else {}
                backend = str(payload.get("backend") or req.get("backend") or "decider_2b")
                _respond(req_id, rt.decision_warm(backend=backend))
                continue
            if op == "decision":
                payload = req.get("payload") if isinstance(req.get("payload"), dict) else {}
                backend = str(payload.get("backend") or req.get("backend") or "decider_2b")
                capability_id = payload.get("capability_id") or req.get("capability_id")
                request_mapping = payload.get("request")
                if not isinstance(request_mapping, dict):
                    _respond(req_id, {"ok": False, "error": "payload.request must be object", **rt.identity()})
                    continue
                _respond(
                    req_id,
                    rt.decision(
                        backend=backend,
                        request_mapping=request_mapping,
                        capability_id=str(capability_id) if capability_id else None,
                        trace_id=str(req.get("trace_id") or payload.get("trace_id") or "") or None,
                    ),
                )
                continue
            if op == "drain":
                rt.mark_drain()
                _respond(req_id, {"ok": True, "draining": True, **rt.identity()})
                continue
            if op == "shutdown":
                _respond(req_id, {"ok": True, "shutdown": True, **rt.identity()})
                return 0
            if op == "turn_open":
                payload = req.get("payload") if isinstance(req.get("payload"), dict) else {}
                prompt = str(payload.get("prompt") or req.get("prompt") or "")
                result = rt.turn_open(
                    trace_id=str(req.get("trace_id") or payload.get("trace_id") or ""),
                    session_id=req.get("session_id") if isinstance(req.get("session_id"), str) else payload.get("session_id"),
                    prompt=prompt,
                    omp_pid=req.get("omp_pid") if isinstance(req.get("omp_pid"), int) else payload.get("omp_pid"),
                    writer_generation=req.get("bridge_generation")
                    if isinstance(req.get("bridge_generation"), int)
                    else rt.generation,
                )
                _respond(req_id, result)
                continue
            if op in {"turn_close", "agent_end"}:
                payload = req.get("payload") if isinstance(req.get("payload"), dict) else {}
                result = rt.turn_close(
                    trace_id=str(req.get("trace_id") or payload.get("trace_id") or ""),
                    session_id=req.get("session_id") if isinstance(req.get("session_id"), str) else payload.get("session_id"),
                    omp_pid=req.get("omp_pid") if isinstance(req.get("omp_pid"), int) else payload.get("omp_pid"),
                    measured=payload.get("measured"),
                    input_tokens=payload.get("input_tokens"),
                    output_tokens=payload.get("output_tokens"),
                    execution_completed=bool(payload.get("execution_completed", True)),
                    verified_success=payload.get("verified_success"),
                    source=str(payload.get("source") or ("bridge_agent_end" if op == "agent_end" else "bridge_turn_end")),
                    provider=payload.get("provider") if isinstance(payload.get("provider"), str) else None,
                    model=payload.get("model") if isinstance(payload.get("model"), str) else None,
                    verification_source=payload.get("verification_source") if isinstance(payload.get("verification_source"), str) else None,
                    writer_generation=req.get("bridge_generation")
                    if isinstance(req.get("bridge_generation"), int)
                    else rt.generation,
                )
                _respond(req_id, result)
                continue
            _respond(req_id, {"ok": False, "error": f"unhandled_op:{op}"})
        except Exception as exc:  # noqa: BLE001
            _respond(req_id if isinstance(req_id, str) else None, {"ok": False, "error": str(exc)})
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    gen = None
    if "--generation" in argv:
        i = argv.index("--generation")
        if i + 1 < len(argv):
            gen = int(argv[i + 1])
    return serve(generation=gen)


if __name__ == "__main__":
    raise SystemExit(main())
