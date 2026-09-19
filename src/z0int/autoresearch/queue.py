from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from . import store


def _conn() -> sqlite3.Connection:
    path = store.queue_db()
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            status TEXT NOT NULL,
            priority REAL NOT NULL DEFAULT 0,
            payload TEXT NOT NULL,
            credit_key TEXT,
            UNIQUE(trace_id, credit_key)
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS arms (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            arm TEXT NOT NULL,
            treatment_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            UNIQUE(job_id, arm, treatment_hash)
        )
        """
    )
    c.commit()
    return c


def enqueue_trace(
    trace_id: str,
    *,
    verified_success: bool | None,
    verifier_id: str | None,
    payload: dict[str, Any] | None = None,
    priority: float | None = None,
) -> dict[str, Any]:
    """Only real verified_success=true with verifier identity may enqueue."""
    if verified_success is not True:
        return {
            "ok": False,
            "enqueued": False,
            "reason": "not_verified_success",
            "trace_id": trace_id,
        }
    if not verifier_id:
        return {
            "ok": False,
            "enqueued": False,
            "reason": "missing_verifier_id",
            "trace_id": trace_id,
        }
    credit_key = f"enqueue:{trace_id}:{verifier_id}"
    job_id = str(uuid.uuid4())
    pl = dict(payload or {})
    axis = str(pl.get("kind") or pl.get("mutation_axis") or "context_policy")
    body = {
        "trace_id": trace_id,
        "verifier_id": verifier_id,
        "payload": pl,
        "mutation_axis": axis,
        "kind": axis,
    }
    pr = float(priority) if priority is not None else _default_priority(payload or {})
    with _conn() as c:
        try:
            c.execute(
                "INSERT INTO jobs (id, trace_id, created_at, status, priority, payload, credit_key) VALUES (?,?,?,?,?,?,?)",
                (job_id, trace_id, time.time(), "queued", pr, json.dumps(body), credit_key),
            )
            c.commit()
        except sqlite3.IntegrityError:
            return {
                "ok": True,
                "enqueued": False,
                "reason": "duplicate_credit",
                "trace_id": trace_id,
            }
    return {"ok": True, "enqueued": True, "job_id": job_id, "trace_id": trace_id, "priority": pr}


def _default_priority(payload: dict[str, Any]) -> float:
    # expected_future_savings * recurrence * promotion * info_gain / cost
    efs = float(payload.get("expected_future_savings") or 1.0)
    rec = float(payload.get("recurrence_probability") or 0.5)
    prom = float(payload.get("promotion_probability") or 0.3)
    ig = float(payload.get("information_gain") or 1.0)
    cost = max(float(payload.get("expected_experiment_cost") or 1.0), 1e-6)
    return (efs * rec * prom * ig) / cost


def list_queue(limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, trace_id, created_at, status, priority, payload FROM jobs ORDER BY priority DESC, created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "trace_id": r["trace_id"],
                "created_at": r["created_at"],
                "status": r["status"],
                "priority": r["priority"],
                "payload": json.loads(r["payload"]),
            }
        )
    return out


def claim_next() -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, trace_id, payload FROM jobs WHERE status='queued' ORDER BY priority DESC, created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        c.execute("UPDATE jobs SET status='running' WHERE id=? AND status='queued'", (row["id"],))
        if c.total_changes == 0:
            return None
        c.commit()
        return {
            "id": row["id"],
            "trace_id": row["trace_id"],
            "payload": json.loads(row["payload"]),
        }


def complete_job(job_id: str, *, status: str = "done") -> None:
    with _conn() as c:
        c.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
        c.commit()


def record_arm(
    job_id: str,
    arm: str,
    treatment_hash: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent arm credit — duplicate (job, arm, treatment) rejected."""
    arm_id = f"{job_id}:{arm}:{treatment_hash}"
    with _conn() as c:
        try:
            c.execute(
                "INSERT INTO arms (id, job_id, arm, treatment_hash, status, result_json) VALUES (?,?,?,?,?,?)",
                (arm_id, job_id, arm, treatment_hash, status, json.dumps(result) if result else None),
            )
            c.commit()
            return {"ok": True, "recorded": True, "arm_id": arm_id}
        except sqlite3.IntegrityError:
            return {"ok": True, "recorded": False, "reason": "duplicate_arm", "arm_id": arm_id}
