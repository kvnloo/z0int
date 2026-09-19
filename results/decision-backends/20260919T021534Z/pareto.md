# Decision backend Pareto analysis

Contract: `decision-capability-v1`

No universal winner declared. Dominance is per-capability only.

## rlm.worker_needed

**Pareto-optimal:** (none with runnable results)
**Excluded (dangerous false > 0):** openjev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| openjev_06b | 0.667 | 29.707446999964304 | 0.6786 | 0.333 | 3 |

## tool_family_select

**Pareto-optimal:** openjev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| openjev_06b | 0.000 | 31.997551501262933 | 1.5919 | 0.000 | 2 |

## retry_or_escalate

**Pareto-optimal:** (none with runnable results)
**Excluded (dangerous false > 0):** openjev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| openjev_06b | 0.500 | 28.11393199954182 | 0.9999 | 0.500 | 2 |

## context_compress_needed

**Pareto-optimal:** openjev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| openjev_06b | 0.500 | 30.05827299784869 | 1.0000 | 0.000 | 2 |

## verification_needed

**Pareto-optimal:** openjev_06b

| backend | accuracy | p50 ms | mean Brier | dangerous | denom |
|---------|----------|--------|------------|-----------|-------|
| openjev_06b | 0.500 | 37.856279999687104 | 0.9807 | 0.000 | 2 |

