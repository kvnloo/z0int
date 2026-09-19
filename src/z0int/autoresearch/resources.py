from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ResourceClass(str, Enum):
    """Autoresearch resource classes.

    research_remote — agy / remote hypothesis workers (continue under GPU load)
    cpu_light       — bookkeeping, ABAB, Tokenomics emit
    gpu_train       — Evolution Lab training
    gpu_benchmark   — frozen fly bench
    """

    RESEARCH_REMOTE = "research_remote"
    CPU_LIGHT = "cpu_light"
    GPU_TRAIN = "gpu_train"
    GPU_BENCHMARK = "gpu_benchmark"


@dataclass
class ResourceLimits:
    gpu_util_pause_above: float = 35.0
    gpu_memory_free_min_mb: float = 2500.0
    cpu_load_pause_above: float = 0.70
    interactive_grace_seconds: float = 15.0


DEFAULTS = ResourceLimits()


def _load_avg_ratio() -> float:
    try:
        load1, _, _ = os.getloadavg()
        n = os.cpu_count() or 1
        return float(load1) / float(n)
    except Exception:
        return 0.0


def _gpu_stats() -> tuple[float | None, float | None]:
    """Return (util_pct, free_mb) or (None, None)."""
    try:
        import subprocess

        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=2,
        )
        line = out.strip().splitlines()[0]
        util_s, free_s = [x.strip() for x in line.split(",")]
        return float(util_s), float(free_s)
    except Exception:
        return None, None


def interactive_recent(grace: float | None = None) -> bool:
    """True if an interactive harness touch file is fresh."""
    from z0int import paths

    g = grace if grace is not None else DEFAULTS.interactive_grace_seconds
    marker = paths.home() / "runtime" / "interactive.touch"
    if not marker.is_file():
        heart = paths.home() / "stream" / "bridge_heart.jsonl"
        if heart.is_file():
            age = time.time() - heart.stat().st_mtime
            return age < g
        return False
    return (time.time() - marker.stat().st_mtime) < g


def should_pause(limits: ResourceLimits | None = None) -> dict[str, Any]:
    """Legacy GPU/CPU contention gate (used by context-policy daemon).

    Equivalent to can_run(GPU_BENCHMARK).
    """
    return can_run(ResourceClass.GPU_BENCHMARK, limits=limits)


def can_run(
    resource_class: ResourceClass | str,
    *,
    limits: ResourceLimits | None = None,
) -> dict[str, Any]:
    """Class-aware resource gate.

    research_remote / cpu_light: never pause for GPU util/VRAM.
    gpu_train / gpu_benchmark: pause on interactive / GPU / CPU contention.
    """
    lim = limits or DEFAULTS
    cls = ResourceClass(resource_class) if not isinstance(resource_class, ResourceClass) else resource_class
    reasons: list[str] = []
    cpu = _load_avg_ratio()
    util, free_mb = _gpu_stats()
    interactive = interactive_recent(lim.interactive_grace_seconds)

    if cls in {ResourceClass.RESEARCH_REMOTE, ResourceClass.CPU_LIGHT}:
        if os.environ.get("Z0INT_PAUSE_RESEARCH") == "1":
            reasons.append("env:Z0INT_PAUSE_RESEARCH")
        return {
            "pause": bool(reasons),
            "reasons": reasons,
            "resource_class": cls.value,
            "cpu_load_ratio": cpu,
            "gpu_util": util,
            "gpu_free_mb": free_mb,
            "interactive": interactive,
        }

    if interactive:
        reasons.append("interactive_traffic")
    if cpu > lim.cpu_load_pause_above:
        reasons.append(f"cpu_load:{cpu:.2f}")
    if util is not None and util > lim.gpu_util_pause_above:
        reasons.append(f"gpu_util:{util}")
    if free_mb is not None and free_mb < lim.gpu_memory_free_min_mb:
        reasons.append(f"gpu_mem_free:{free_mb}")
    return {
        "pause": bool(reasons),
        "reasons": reasons,
        "resource_class": cls.value,
        "cpu_load_ratio": cpu,
        "gpu_util": util,
        "gpu_free_mb": free_mb,
        "interactive": interactive,
    }
