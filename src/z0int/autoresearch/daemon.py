from __future__ import annotations

import time
from typing import Any

from . import store
from .queue import claim_next, complete_job, list_queue
from .replay import run_abab_job, run_contrastive_job
from .resources import should_pause


def status() -> dict[str, Any]:
    ctrl = store.read_control()
    q = list_queue(20)
    return {
        "schema": "z0int.autoresearch_status.v1",
        "paused": bool(ctrl.get("paused")),
        "queue_depth": len(q),
        "queue_head": q[:5],
        "results_path": str(store.results_path()),
        "resource": should_pause(),
    }


def pause() -> dict[str, Any]:
    c = store.read_control()
    c["paused"] = True
    store.write_control(c)
    return status()


def resume() -> dict[str, Any]:
    c = store.read_control()
    c["paused"] = False
    store.write_control(c)
    return status()


def run_once(*, force: bool = False) -> dict[str, Any]:
    import os

    ctrl = store.read_control()
    if ctrl.get("paused") and not force:
        return {"ok": True, "skipped": True, "reason": "paused"}
    if not force and os.environ.get("Z0INT_AUTORESEARCH_IGNORE_RESOURCES") != "1":
        gate = should_pause()
        if gate.get("pause"):
            return {"ok": True, "skipped": True, "reason": "resource_governor", "gate": gate}
    job = claim_next()
    if not job:
        return {"ok": True, "skipped": True, "reason": "empty_queue"}
    try:
        from .replay import _unwrap_payload

        kind = _unwrap_payload(job).get("kind") or (job.get("payload") or {}).get("mutation_axis")
        result = (
            run_contrastive_job(job)
            if kind == "contrastive_evidence"
            else run_abab_job(job)
        )
        complete_job(job["id"], status="done")
        return result
    except Exception as exc:
        complete_job(job["id"], status="error")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "job_id": job["id"]}


def run_daemon(*, poll_seconds: float = 5.0, max_iterations: int | None = None) -> dict[str, Any]:
    n = 0
    outcomes = []
    while max_iterations is None or n < max_iterations:
        n += 1
        out = run_once()
        outcomes.append(out)
        if out.get("skipped") and out.get("reason") == "empty_queue":
            break
        if max_iterations is None and out.get("skipped"):
            time.sleep(poll_seconds)
            continue
        if max_iterations is not None and n >= max_iterations:
            break
        time.sleep(0.05)
    return {"ok": True, "iterations": n, "outcomes": outcomes[-10:]}


def report(limit: int = 20) -> dict[str, Any]:
    p = store.results_path()
    rows = []
    if p.is_file():
        lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
        import json

        for line in lines:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return {"schema": "z0int.autoresearch_report.v1", "n": len(rows), "rows": rows, "status": status()}
