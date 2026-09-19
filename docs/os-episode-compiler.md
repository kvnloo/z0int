# OS Episode Compiler

workspace-copilot is the high-frequency teacher; z0intelligence is the learning/control cortex.

```text
workspace-copilot (sensors, UI, prepare/surface gates)
        │ sanitized episodes / shadow / horizons / routines
        ▼
z0int os-context import
        │ os.context_episode.v0  (features ≠ labels)
        ▼
os.next_operator shadow (PREDICT only)
        │ safe coverage @ precision floor
        ▼
PREPARE (later) → SURFACE canary → capability-scoped live
```

## CLI

```bash
z0int os-context import --json
z0int os-context stats --json
z0int os-context next-operator --json
```

## Invariants

- No raw titles/clipboard/pane text/URLs/keystrokes.
- Features = `state_before` only; labels = actual operator / state_after.
- `noop` is a real class.
- Gate stays PREDICT until PREPARE is wired; no COMMIT; bridge stays log_only.
- North-star path metric: time from context change to verified useful action (TTVA).
