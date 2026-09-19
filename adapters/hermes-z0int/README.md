# Hermes ↔ z0int thin adapter

Normalize Hermes envelopes into z0int bridge identity + close observations.
Does **not** own cognition, promotion, or Kerdoios planning.

Install path: package lives in-tree; Hermes plugins may import via:

```python
from adapters.hermes_z0int import normalize_envelope, close_observation, join_outcome
```

Or install path relative to repo root on `PYTHONPATH`.

Identity fields (never `omp_*` generic names):

- `harness_id` (always `hermes` here)
- `session_id`, `process_id`, `trace_id`, `turn_id`
- `bridge_generation`, `build_id`
