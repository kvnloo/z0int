"""P0.7A — Zero-cost shadow latency regression."""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class ShadowLatencyRecord:
    handler: str
    event: str
    started_at: float
    sync_duration_ms: float
    background_duration_ms: float | None = None
    queue_delay_ms: float | None = None
    status: str = "ok"


def make_regression() -> str:
    return "before_agent_start blocking baseline recorded; B must not scale with shadow delay"
