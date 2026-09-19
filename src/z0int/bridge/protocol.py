"""Bridge worker wire protocol constants and build fingerprint."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

BRIDGE_PROTOCOL = "z0int.bridge.v2"
SCHEMA_EVENT = "z0int.bridge.v2"
SCHEMA_HEART = "z0int.bridge_heart.v2"
SCHEMA_OPEN = "z0int.open_turn.v2"

# Ops the worker understands (V0).
OPS = frozenset(
    {
        "hello",
        "self_check",
        "turn_open",
        "turn_close",
        "agent_end",
        "status",
        "drain",
        "shutdown",
        "decision",
        "decision_warm",
    }
)


def repo_root() -> Path:
    env = os.environ.get("Z0INT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # src/z0int/bridge/protocol.py -> repo root
    return Path(__file__).resolve().parents[3]


def compute_build_id(root: Path | None = None) -> str:
    """Fingerprint working tree, not HEAD alone (uncommitted edits matter)."""
    root = root or repo_root()
    h = hashlib.sha256()
    head = "nogit"
    try:
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    h.update(head.encode())
    try:
        diff = subprocess.check_output(
            ["git", "-C", str(root), "diff", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        h.update(diff)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        h.update(b"nodiff")
    try:
        porcelain = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        h.update(porcelain.encode())
        # hash untracked bridge-related paths named in porcelain
        for line in porcelain.splitlines():
            if not line or line.startswith(" "):
                continue
            path = line[3:].strip()
            if path.startswith("src/z0int/bridge/") or path.startswith("omp-extensions/z0int-bridge/"):
                fp = root / path
                if fp.is_file():
                    try:
                        h.update(fp.read_bytes())
                    except OSError:
                        pass
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    # always include resident sources if present
    for rel in (
        "src/z0int/bridge/decision_cache.py",
        "src/z0int/bridge/protocol.py",
        "src/z0int/bridge/runtime.py",
        "src/z0int/bridge/worker.py",
        "src/z0int/bridge/generation.py",
        "omp-extensions/z0int-bridge/index.ts",
    ):
        fp = root / rel
        if fp.is_file():
            try:
                h.update(rel.encode())
                h.update(fp.read_bytes())
            except OSError:
                pass
    return h.hexdigest()[:16]
