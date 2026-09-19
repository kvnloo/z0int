"""P0.7A — Handler classification for before_agent_start handlers.

Classification:
  PURE_SHADOW         — result not required for provider request; may be deferred
  SYNC_IDENTITY_ASYNC_IO — identity/state needed synchronously; persistence deferred
  CRITICAL_SYNC       — data required before provider request can be constructed
  UNKNOWN             — not yet classified
"""
from __future__ import annotations

PURE_SHADOW = [
    ("flyforge-jev", "Writes shadow logs to ~/.z0int/shadow/; does not affect provider request"),
    ("vllm-jev-shadow", "Fire-and-forget vLLM Jev decision via void async IIFE"),
]
SYNC_IDENTITY_ASYNC_IO = [
    ("vllm-jev-system", "Returns system prompt synchronously, no async work"),
    ("z0int-bridge", "Allocates traceId/sessionId/generation synchronously; turn_open deferred"),
]
CRITICAL_SYNC = [
    ("typesafe-jev", "Route decision may be required for WorkRequirement construction (not found as separate extension)"),
]
UNKNOWN = []

def handler_classification() -> dict[str, list[tuple[str, str]]]:
    return {
        "PURE_SHADOW": PURE_SHADOW,
        "SYNC_IDENTITY_ASYNC_IO": SYNC_IDENTITY_ASYNC_IO,
        "CRITICAL_SYNC": CRITICAL_SYNC,
        "UNKNOWN": UNKNOWN,
    }
