"""OS Episode Compiler: workspace-copilot → z0int vault.

Ownership split:
  workspace-copilot owns sensors, episode join, shadow predict, prepare/commit UI
  z0int owns specialist training, receipts, sealed promotion

This module imports *already-sanitized* semantic episodes/shadow rows only.
It never reads raw keystrokes, titles, pane text, clipboard, or screenshots.

Schemas:
  os.context_episode.v0   compiled training episode (no future leakage)
  os.next_context.v0      shadow prediction join
  os.next_operator.v0     operator-family label vocabulary
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from . import paths

SCHEMA_EPISODE = "os.context_episode.v0"
SCHEMA_SHADOW = "os.next_context.v0"
SCHEMA_OPERATOR = "os.next_operator.v0"
SCHEMA_BUNDLE = "z0int.os_episode_bundle.v1"

# Flow os.next_operator.v0 vocabulary (inspect_result first).
# Hierarchical refine later; do not invent free-text labels.
OPERATOR_FAMILIES = (
    "inspect_result",
    "resume_previous",
    "open_context",
    "retrieve",
    "run_test",
    "delegate",
    "noop",
)

# Map workspace-copilot action_family / legacy labels → Flow operator vocab
_FAMILY_MAP = {
    "inspect_result": "inspect_result",
    "harness": "inspect_result",
    "resume_previous": "resume_previous",
    "open_context": "open_context",
    "switch_app": "open_context",
    "switch_workspace": "open_context",
    "switch_pane": "open_context",
    "switch_project": "open_context",
    "open_file": "open_context",
    "navigate": "open_context",
    "retrieve": "retrieve",
    "search": "retrieve",
    "read": "retrieve",
    "run_test": "run_test",
    "test": "run_test",
    "verify": "run_test",
    "delegate": "delegate",
    "noop": "noop",
    "stay": "noop",
    # legacy uppercase z0int labels
    "SWITCH_APP": "open_context",
    "OPEN_FILE": "open_context",
    "NAVIGATE": "open_context",
    "READ": "retrieve",
    "SEARCH": "retrieve",
    "EDIT": "open_context",
    "TEST": "run_test",
    "SHELL": "open_context",
    "BROWSER": "open_context",
    "COPY": "open_context",
    "PASTE": "open_context",
    "WAIT": "noop",
    "VERIFY": "run_test",
    "DELEGATE": "delegate",
    "NOOP": "noop",
    "OTHER": "open_context",
}


def workspace_copilot_db() -> Path:
    override = os.environ.get("WORKSPACE_COPILOT_STATE_DIR")
    if override:
        return Path(override).expanduser() / "workspace.db"
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state_home / "workspace-copilot" / "workspace.db"


def episodes_dir() -> Path:
    d = paths.home() / "episodes" / "os_context"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _json_load(raw: object) -> Any:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(str(raw))


def normalize_operator(family: str | None, *, target: str | None = None) -> str:
    if not family:
        return "open_context"
    raw = str(family).strip()
    if raw in _FAMILY_MAP:
        return _FAMILY_MAP[raw]
    key = raw.lower()
    if key in _FAMILY_MAP:
        return _FAMILY_MAP[key]
    if raw in OPERATOR_FAMILIES:
        return raw
    if key in OPERATOR_FAMILIES:
        return key
    # harness terminal targets often land as completed/waiting labels
    if key in {"completed", "waiting", "blocked", "failed"}:
        return "inspect_result"
    return "open_context"


def _sanitize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Drop any residual high-risk keys if they ever leak into sanitized JSON."""
    banned = (
        "title",
        "window_title",
        "clipboard",
        "selection_text",
        "pane_text",
        "command_args",
        "url",
        "raw",
        "screenshot",
        "keystroke",
        "password",
        "token",
        "secret",
    )
    out: dict[str, Any] = {}
    for k, v in state.items():
        lk = str(k).lower()
        if any(b in lk for b in banned):
            continue
        if isinstance(v, dict):
            out[k] = _sanitize_state(v)
        else:
            out[k] = v
    return out


def compile_episode(row: dict[str, Any]) -> dict[str, Any] | None:
    """Compile one context_episodes row into a leakage-safe training episode.

    Features use only state_before (+ meta available at open). Labels use
    action_family / state_after / horizons — never mixed into features.
    """
    if not row.get("closed"):
        return None
    state_before = _sanitize_state(_json_load(row.get("state_before_json")))
    state_after = _sanitize_state(_json_load(row.get("state_after_json")))
    family = row.get("action_family") or ""
    target = row.get("action_target") or ""
    operator = normalize_operator(str(family) if family else None, target=str(target) if target else None)
    episode_id = (
        f"osep_{row.get('id')}_"
        + hashlib.sha256(
            f"{row.get('context_id')}|{row.get('ts_before')}|{family}|{target}".encode()
        ).hexdigest()[:12]
    )
    return {
        "schema": SCHEMA_EPISODE,
        "episode_id": episode_id,
        "source": {
            "system": "workspace-copilot",
            "context_id": row.get("context_id"),
            "open_event_id": row.get("open_event_id"),
            "close_event_id": row.get("close_event_id"),
            "db_row_id": row.get("id"),
        },
        # FEATURES — available at prediction time only
        "state_before": state_before,
        "available_evidence": _evidence_keys(state_before),
        # LABELS — not features
        "actual_operator": operator,
        "actual_family_raw": family,
        "actual_target": target,
        "state_after": state_after,
        "horizon_ms": row.get("horizon_ms"),
        "ts_before": row.get("ts_before"),
        "ts_after": row.get("ts_after"),
        "latencies": {
            "episode_ms": (
                None
                if row.get("ts_before") is None or row.get("ts_after") is None
                else max(0.0, (float(row["ts_after"]) - float(row["ts_before"])) * 1000.0)
            )
        },
        "outcome": {
            "closed": True,
            "is_noop": operator == "NOOP",
        },
        "compiled_at": time.time(),
    }


def _evidence_keys(state: dict[str, Any]) -> list[str]:
    """Typed modality names present in state (for ablation later)."""
    keys = []
    for k in (
        "app",
        "project",
        "workspace",
        "monitor",
        "harness",
        "harness_state",
        "session",
        "task",
        "task_phase",
        "task_status",
        "pane",
        "objective",
    ):
        if state.get(k) not in (None, ""):
            keys.append(k)
    return keys


def compile_shadow(row: dict[str, Any]) -> dict[str, Any]:
    """Join a shadow_predictions row into os.next_context.v0 shape."""
    topk = _json_load(row.get("topk_json"))
    state = _sanitize_state(_json_load(row.get("state_json")))
    receipt = _json_load(row.get("receipt_json"))
    actual_op = normalize_operator(row.get("actual_family"), target=row.get("actual_target"))
    return {
        "schema": SCHEMA_SHADOW,
        "pred_id": row.get("pred_id"),
        "ts": row.get("ts"),
        "context_id": row.get("context_id"),
        "state": state,
        "topk": topk,
        "latency_ms": row.get("latency_ms"),
        "actual_operator": actual_op,
        "actual_family_raw": row.get("actual_family"),
        "actual_target": row.get("actual_target"),
        "actual_context_id": row.get("actual_context_id"),
        "ranked": row.get("ranked"),
        "horizon_ms": row.get("horizon_ms"),
        "confidence": row.get("confidence"),
        "margin": row.get("margin"),
        "entropy": row.get("entropy"),
        "receipt": receipt if isinstance(receipt, dict) else {},
        "compiled_at": time.time(),
    }


def import_from_db(
    *,
    db_path: Path | None = None,
    limit: int = 50_000,
    closed_only: bool = True,
) -> dict[str, Any]:
    """Read workspace.db and write JSONL episode + shadow bundles under ~/.z0int."""
    db = Path(db_path) if db_path else workspace_copilot_db()
    if not db.is_file():
        return {"ok": False, "error": f"missing workspace-copilot db: {db}"}

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        q = "SELECT * FROM context_episodes"
        if closed_only:
            q += " WHERE closed = 1"
        q += " ORDER BY id DESC LIMIT ?"
        ep_rows = [dict(r) for r in con.execute(q, (int(limit),)).fetchall()]
        sh_rows = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM shadow_predictions ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        ]
        hz_rows = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM prediction_horizons ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        ]
        # P3 routine + P3d utility tables may be absent on older DBs
        try:
            routines = [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM routine_candidates ORDER BY support DESC LIMIT 200"
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            routines = []
        try:
            utility_rows = [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM automation_utility ORDER BY updated_at DESC LIMIT 200"
                ).fetchall()
            ]
            receipt_rows = [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM automation_receipts ORDER BY id DESC LIMIT 5000"
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            utility_rows = []
            receipt_rows = []
    finally:
        con.close()

    out_dir = episodes_dir()
    ep_path = out_dir / "episodes.jsonl"
    sh_path = out_dir / "shadow.jsonl"
    hz_path = out_dir / "horizons.jsonl"
    rt_path = out_dir / "routine_candidates.jsonl"
    meta_path = out_dir / "import_meta.json"

    compiled = []
    for row in reversed(ep_rows):  # chronological
        ep = compile_episode(row)
        if ep:
            compiled.append(ep)

    with ep_path.open("w", encoding="utf-8") as fh:
        for ep in compiled:
            fh.write(json.dumps(ep, sort_keys=True) + "\n")

    shadows = [compile_shadow(r) for r in reversed(sh_rows)]
    with sh_path.open("w", encoding="utf-8") as fh:
        for s in shadows:
            fh.write(json.dumps(s, sort_keys=True) + "\n")

    with hz_path.open("w", encoding="utf-8") as fh:
        for h in reversed(hz_rows):
            fh.write(
                json.dumps(
                    {
                        "schema": "os.prediction_horizon.v0",
                        "pred_id": h.get("pred_id"),
                        "horizon_ms": h.get("horizon_ms"),
                        "actual_operator": normalize_operator(h.get("actual_family"), target=h.get("actual_target")),
                        "actual_family_raw": h.get("actual_family"),
                        "actual_target": h.get("actual_target"),
                        "ranked": h.get("ranked"),
                        "manual_equivalent": h.get("manual_equivalent"),
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    with rt_path.open("w", encoding="utf-8") as fh:
        for r in routines:
            fh.write(
                json.dumps(
                    {
                        "schema": "os.routine_candidate.v0",
                        "fingerprint": r.get("fingerprint"),
                        "ngram_n": r.get("ngram_n"),
                        "sequence": _json_load(r.get("sequence_json")),
                        "project": r.get("project"),
                        "support": r.get("support"),
                        "sessions": r.get("sessions"),
                        "same_ratio": r.get("same_ratio"),
                        "median_duration_ms": r.get("median_duration_ms"),
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    util_path = out_dir / "automation_utility.jsonl"
    rcpt_path = out_dir / "automation_receipts.jsonl"
    with util_path.open("w", encoding="utf-8") as fh:
        for r in utility_rows:
            fh.write(
                json.dumps(
                    {"schema": "os.automation_utility.v0", **{k: r.get(k) for k in r}},
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )
    with rcpt_path.open("w", encoding="utf-8") as fh:
        for r in receipt_rows:
            details = r.get("details_json")
            if isinstance(details, str):
                details = _json_load(details)
            fh.write(
                json.dumps(
                    {
                        "schema": "os.automation_receipt.v0",
                        "id": r.get("id"),
                        "ts": r.get("ts"),
                        "fingerprint": r.get("fingerprint"),
                        "phase": r.get("phase"),
                        "suggestion_id": r.get("suggestion_id"),
                        "ok": r.get("ok"),
                        "details": details,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    # operator label histogram
    hist: dict[str, int] = {}
    for ep in compiled:
        op = ep["actual_operator"]
        hist[op] = hist.get(op, 0) + 1

    meta = {
        "schema": SCHEMA_BUNDLE,
        "ok": True,
        "db": str(db),
        "episodes": len(compiled),
        "shadow": len(shadows),
        "horizons": len(hz_rows),
        "routines": len(routines),
        "automation_utility": len(utility_rows),
        "automation_receipts": len(receipt_rows),
        "operator_histogram": hist,
        "paths": {
            "episodes": str(ep_path),
            "shadow": str(sh_path),
            "horizons": str(hz_path),
            "routines": str(rt_path),
            "automation_utility": str(util_path),
            "automation_receipts": str(rcpt_path),
        },
        "operator_schema": SCHEMA_OPERATOR,
        "operator_vocab": list(OPERATOR_FAMILIES),
        "imported_at": time.time(),
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def import_via_cli(*, limit: int = 50_000) -> dict[str, Any]:
    """Prefer CLI export if workspace-copilot exposes one; else direct db."""
    bin_path = os.environ.get("WORKSPACE_COPILOT_BIN", "workspace-copilot")
    # Try a few possible export commands; fail open to db import.
    for args in (
        [bin_path, "--json", "episodes", "export"],
        [bin_path, "--json", "flow", "export"],
    ):
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
            if proc.returncode == 0 and proc.stdout.strip().startswith("{"):
                # not standardized yet
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            break
    return import_from_db(limit=limit)


def stats() -> dict[str, Any]:
    """Live db + imported vault metrics."""
    db = workspace_copilot_db()
    out: dict[str, Any] = {"ok": True, "db": str(db), "db_exists": db.is_file()}
    if db.is_file():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            out["live"] = {
                "context_episodes": con.execute("SELECT COUNT(*) FROM context_episodes").fetchone()[0],
                "closed_episodes": con.execute("SELECT COUNT(*) FROM context_episodes WHERE closed=1").fetchone()[0],
                "shadow_predictions": con.execute("SELECT COUNT(*) FROM shadow_predictions").fetchone()[0],
                "prediction_horizons": con.execute("SELECT COUNT(*) FROM prediction_horizons").fetchone()[0],
                "routine_candidates": con.execute("SELECT COUNT(*) FROM routine_candidates").fetchone()[0],
            }
        finally:
            con.close()
    meta_path = episodes_dir() / "import_meta.json"
    if meta_path.is_file():
        out["imported"] = json.loads(meta_path.read_text(encoding="utf-8"))
    return out
