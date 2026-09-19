# Decision backend Pareto analysis

Contract: `decision-capability-v1`

No universal winner declared. Dominance is per-capability only.

## rlm.worker_needed

**Pareto-optimal:** decider_2b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.667 | 51.31253799481783 | 0.4919 | 0.000 | 3 |

## tool_family_select

**Pareto-optimal:** decider_2b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 1.000 | 51.37042199567077 | 0.0380 | 0.000 | 2 |

## retry_or_escalate

**Pareto-optimal:** (none with runnable results)
**Excluded (dangerous false > 0):** decider_2b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 47.10611199698178 | 0.5604 | 0.500 | 2 |

## context_compress_needed

**Pareto-optimal:** decider_2b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 48.22369950124994 | 0.6150 | 0.000 | 2 |

## verification_needed

**Pareto-optimal:** decider_2b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| decider_2b | 0.500 | 50.707857499219244 | 0.4736 | 0.000 | 2 |

