"""Ingest OMP WorkerNeededReplayV1 results into Tokenomics analytics events.

Private grant bodies stay on disk under ~/.z0int/replay/rlm-worker-needed/.
This module only reads result.jsonl summaries (hashes/IDs/labels).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .. import paths
from ..tokenomics_emit import emit_raw

SCHEMA = "z0int.rlm.worker_needed_replay_ingest.v1"
RESULTS_NAME = "results.jsonl"


def results_path(root: Path | None = None) -> Path:
    layout = paths.ensure_layout(root)
    return layout["replay"] / "rlm-worker-needed" / RESULTS_NAME


def ingest_worker_needed_results(
    *,
    root: Path | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    path = results_path(root)
    if not path.is_file():
        return {"ok": True, "ingested": 0, "path": str(path), "note": "no results yet"}

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = []
    for ln in lines[-limit:]:
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue

    emitted = 0
    by_gold: dict[str, int] = {}
    for row in rows:
        gold = str(row.get("gold") or "UNKNOWN")
        by_gold[gold] = by_gold.get(gold, 0) + 1
        emit_raw(
            {
                "schema": SCHEMA,
                "ts": time.time(),
                "capability_id": "rlm.worker_needed",
                "experiment_id": row.get("experiment_id") or "rlm-worker-needed-replay-v1",
                "pair_id": row.get("pair_id"),
                "trace_id": row.get("trace_id"),
                "task_snapshot_id": row.get("task_snapshot_id"),
                "replay_snapshot_id": row.get("snapshot_id"),
                "replay_snapshot_hash": row.get("replay_snapshot_hash"),
                "gold": gold,
                "label_reason": row.get("label_reason"),
                "tokenomics_joined": bool(row.get("tokenomics_joined")),
                "native_pass": (row.get("native_aggregate") or {}).get("pass"),
                "worker_pass": (row.get("worker_aggregate") or {}).get("pass"),
                "native_wall_ms": (row.get("native_aggregate") or {}).get("wallMs"),
                "worker_wall_ms": (row.get("worker_aggregate") or {}).get("wallMs"),
                "native_tokens": (row.get("native_aggregate") or {}).get("tokens"),
                "worker_tokens": (row.get("worker_aggregate") or {}).get("tokens"),
                # Never invent savings; cost stays UNKNOWN unless measured upstream.
                "cost_usd": None,
                "estimated_tokens_avoided": None,
                "measured_tokens_avoided": None,
            },
            root=root,
        )
        emitted += 1

    return {
        "ok": True,
        "ingested": emitted,
        "path": str(path),
        "by_gold": by_gold,
        "events_path": str(paths.ensure_layout(root)["tokenomics"] / "events.jsonl"),
    }


def cmd_ingest(*, as_json: bool = True, limit: int = 50) -> int:
    rep = ingest_worker_needed_results(limit=limit)
    print(json.dumps(rep, indent=2 if as_json else None))
    return 0 if rep.get("ok") else 1
