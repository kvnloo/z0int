# Contrastive evidence-sufficiency

Nimble-inspired **unit of learning**, not Nimble weights.

## Four condition classes

| Condition | Expect |
|-----------|--------|
| `original` | preserve decision |
| `relevant_edit` | flip decision (source fact edit, not answer injection) |
| `irrelevant_control` | preserve |
| `necessity_delete:{id}` | abstain per required evidence item |
| `necessity_delete:all` | abstain when all necessary removed |

Probe `derive_implementation_decision` reads **source facts** (`rfc_revision`, `superseded`) — never `facts.decision`.

## P0 capability

```text
context.current_project_state
context.current_implementation_decision  (narrower fixture)
```

## CLI

```bash
z0int contrastive eval --json --store
z0int contrastive race --json
z0int context-state fixture --json
z0int context-state compile snapshot.json --json
```

## Metrics

Grouped-family gate (not row-average):

```text
P(entire contrast family correct) = full_family_pass_rate
```

`EvidenceDependency` records `requires`, `invariants`, `invalidated_by`, `fastest_recipe` for semantic cache invalidation.

`curation_accepted` ≠ `verified_success`.

## Workspace loop (P0)

```text
REAL ACTION → workspace-copilot observes
           → z0int context-state compile [--store]
           → contrast family + EvidenceDependency
           → autoresearch data-recipe race
           → Tokenomics measures recipe cost / future savings
```

```bash
workspace-copilot context-snapshot --json
workspace-copilot context-snapshot --json --store   # compile + append family
z0int contrastive race --families-jsonl ~/.z0int/context_families/context.current_project_state.jsonl
```

