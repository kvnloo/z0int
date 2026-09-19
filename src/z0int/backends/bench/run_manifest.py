"""Run-level manifest for decision backend benchmarks."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tokenomics_bridge import dataset_hash, tokenomics_git_sha


def _git_sha(repo_root: Path) -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_root), text=True, stderr=subprocess.DEVNULL)
        return out.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def _gpu_name() -> str | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            timeout=5,
        )
        return out.strip().splitlines()[0] if out.strip() else None
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def _pkg_version(name: str) -> str | None:
    try:
        mod = __import__(name)
        return getattr(mod, "__version__", None)
    except Exception:
        return None


def build_run_manifest(
    *,
    repo_root: Path,
    contract: str,
    fixtures_path: Path,
    candidates: list[str],
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    device_env: dict[str, str] | None = None,
    model_revisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "z0int.backends_bench.run_manifest.v1",
        "run_id": run_id,
        "contract": contract,
        "dataset_hash": dataset_hash(fixtures_path),
        "fixtures_path": str(fixtures_path),
        "candidates": list(candidates),
        "z0int_git_sha": _git_sha(repo_root),
        "tokenomics_git_sha": tokenomics_git_sha(),
        "python_version": platform.python_version(),
        "torch_version": _pkg_version("torch"),
        "transformers_version": _pkg_version("transformers"),
        "cuda_version": None,
        "gpu_name": _gpu_name(),
        "platform": platform.platform(),
        "device_env": device_env or {},
        "model_revisions": model_revisions or {},
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }


def write_run_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
