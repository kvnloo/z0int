# Network cutover — harness adapters

## OMP

Canonical extension tree: `omp-extensions/z0int-bridge/` in this repo.
`z0int onboard` symlinks each child of `omp-extensions/` into `~/.omp/agent/extensions/`.
Do not maintain a second copy under `~/.omp` by hand.

## Hermes

Thin adapter: `adapters/hermes_z0int/` (docs path `adapters/hermes-z0int/`).
Normalizes envelopes, emits `z0int.allocation_observation.v1` on close, joins outcomes.
Identity uses `harness_id/session_id/process_id/trace_id/turn_id/bridge_generation/build_id` — never generic `omp_*` field names.

## Concurrency

Multiple OMP sessions + one Hermes session must not share `session_id` or `trace_id`.
Each close observation carries its own identity; Kerdoios import is append-only.
