# decision-capability-v2 dataset plan (draft)

Status: **design only** — do not treat v1 smoke fixtures as a production frontier.

## Goal

Build ~50–100 **independently labeled, replayable** decision examples per capability from real OMP / Tokenomics traces, with verifier-backed gold labels that do not come from the backend being scored.

## Contract sketch

- **Schema:** `decision-capability-v2` (future; not implemented in bench runner yet)
- **Provenance:** each row carries `trace_id`, `task_snapshot_id`, `verifier_id`, `label_source`, `replay_bundle_uri`
- **Label rule:** gold derived from counterfactual outcome, frozen verifier, or human adjudication — never from the candidate backend under test
- **Evidence strength:** rows count toward VALIDATED only when independently labeled and replayable end-to-end

## Priority order (capability → target n)

| Priority | Capability | Target n | Rationale |
|----------|------------|----------|-----------|
| 1 | `rlm.worker_needed` | 50–100 | Shadow lane candidate (Decider); safety-critical |
| 2 | `context_compress_needed` | 50–100 | High tokenomics leverage |
| 3 | `verification_needed` | 50–100 | Laya CPU niche; ship-gate signal |
| 4 | `tool_family_select` | 50–100 | Routing quality vs latency |
| 5 | `retry_or_escalate` | 50–100 | Currently no safe model; needs real failure taxonomy |

## Sourcing pipeline (minimal v2)

1. **Collect** OMP shadow + authority outcomes already logged via Tokenomics (`harness=z0int`, `role=decision_backend`, capability tag).
2. **Filter** rows with frozen task snapshot + independent verifier result (test pass, grant miss, escalation policy hit, etc.).
3. **Label** using verifier/counterfactual script — e.g. worker needed iff grant repair failed and isolated worker succeeded on replay.
4. **Dedupe** by `task_snapshot_id`; keep earliest adjudicated label on conflict.
5. **Export** JSONL compatible with `BenchExample` loader + extended provenance fields.
6. **Hold out** 20% by trace_id hash for promotion gates.

## Row fields (additive over v1)

```json
{
  "id": "rlm.worker_needed/omp/<trace>/<snapshot>",
  "capability": "rlm.worker_needed",
  "provenance": "omp.tokenomics.v2",
  "trace_id": "...",
  "task_snapshot_id": "...",
  "label_source": "verifier.replay",
  "verifier_id": "rlm.grant_sufficiency.v1",
  "state": { "...": "..." },
  "question": { "...": "..." },
  "gold": "worker",
  "allow_abstain": true,
  "dangerous_if_gold_worker": ["native"]
}
```

## Non-goals (this phase)

- No OMP authority wiring
- No Kerdoios routing
- No openjev_4b benchmark
- No expansion of v1 smoke fixture count (11 rows remain regression/smoke)

## Promotion gate to VALIDATED Pareto

Reuse eligibility layer:

- `validated_min_examples = 50` (configurable)
- competence gate unchanged (trivial baseline + margin + optional production floor)
- dangerous_false hard exclusion unchanged

When v2 reaches ≥50 rows per capability, re-run four-backend Pareto on v2 contract only — keep v1 as CI smoke.

## Next engineering slice (when authorized)

1. Tokenomics export adapter: `z0int tokenomics export-decisions --capability ...`
2. Verifier replay harness for label confirmation
3. `benchmarks/fixtures/decision-capability-v2/` directory + loader flag in bench CLI
4. Shadow integration (observe-only) to feed the export pipeline
