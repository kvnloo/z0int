# Decision backends

z0int owns setup, typed decision contracts, evidence, and routing.
Backends implement local (or remote) judgment engines behind one contract.

## Contract

- `DecisionRequest` — state + boolean / choice / score questions
- `DecisionResult` — complete per-question probability distributions
- `DecisionBackend` — `capabilities`, `health(load=…)`, `evaluate(request)`

Importing `z0int.backends.base` is stdlib-only (no torch).

## Decision roster (canonical)

`manifests/models.yaml` → `decision_roster.candidates` lists **Jev/System-One-style
decision backends** — not general LLM roster entries (Kimi/Qwen/GLM belong elsewhere).
Kerdoios sees installed weights as secondary `ResourceOffer`s; z0int remains source of truth.

| ID | HF / source | Status | Notes |
|----|-------------|--------|-------|
| `laya_421m` | `convaiinnovations/laya` | pinned | ~421M calibrated; CPU/MPS-friendly |
| `decider_2b` | `Mapika/decider-2b` | pinned | Qwen3.5-2B one-pass typed probs |
| `nanojev_06b` | `C-Tianyu/NanoJev` | pinned + adapter | parallel decision heads |
| `reflex` | browser / GitHub | optional | WebGPU demo; no HF pin yet |
| `system_one_4b` | `pngwn/system-one-qwen3.5-4b-scorer` | pinned | **CC-BY-NC-4.0** (non-commercial) |
| `openjev_06b` / `openjev_4b` | Qwen base + direct logits | pinned | OpenJev substrate |

Next: benchmark all candidates on one capability contract (`rlm.worker_needed`, tool
select, retry/escalate, intent route, compression gate) and maintain a Pareto table
(p50, accuracy, calibration, VRAM, platform).

## Local vs remote

| Backend | Kind | Notes |
|---------|------|-------|
| `nanojev` | local semantic model | Pinned HF bundle `nanojev_06b`; CUDA V0 |
| `laya` / `decider` / `system_one_4b` | manifest candidates | Adapters TBD; weights via `z0int models sync` |
| `reflex` | browser / WebGPU | optional; no torch load path yet |
| OpenJev / vLLM / MB / fly | existing lanes | Not rewritten in the first backend PR; thin adapters later |

Probabilities that sum to one are **complete normalized distributions**.
Calibration is checkpoint/task dependent — do not treat “sums to 1” as calibrated.

## NanoJev install

```bash
z0int onboard --auto --sync-models   # or: z0int models sync
# managed path:
#   ~/.z0int/models/nanojev_06b/{best.safetensors,config.json,tokenizer/,backbone_config/}
# pin: C-Tianyu/NanoJev@4a19595eada0857133c0d2be024f879a4077054b
```

Override checkpoint: `Z0INT_NANOJEV_CHECKPOINT=/path/to/bundle`.

## CLI

```bash
z0int backends list --json          # no GPU load
z0int backends doctor --json        # filesystem/config only
z0int backends doctor --load        # explicit weight load
z0int backends eval --backend nanojev --input tests/fixtures/nanojev_request.json --json
```

## Ready means

- **configured** — backend registered / path known
- **ready** — checkpoint complete on disk
- **loaded** — weights resident in process

Ordinary `z0int doctor` never loads NanoJev weights.
