# z0int roadmap

This roadmap captures the long-term direction for z0int.

The guiding constraint is simple:

> **Optimize for measurable reduction in frontier-model work without reducing verified task quality.**

z0int is not trying to replace a frontier model with one small personal model. It is trying to progressively compile repeated parts of a user's cognition and workflow into retrieval, deterministic routines, mushroom-body-style decision heads, and specialized fly controllers.

The existing OpenJev code is the current runtime substrate. [Evolution Lab](https://github.com/kvnloo/evolution-lab) is the experiment/search engine. [AODL](https://github.com/kvnloo/aodl) is an optional future intent/orchestration representation, not a prerequisite for useful results.

## North star

```text
user-owned digital history
        |
        v
private provenance-preserving data plane
        |
        v
episodes: context -> decision/action -> outcome
        |
        v
Evolution Lab + ABAB
        |
        +--> deterministic routine
        +--> mushroom-body specialist
        +--> temporal / fly specialist
        +--> local semantic scorer
        +--> small SLM/SVLM when it actually wins
        |
        v
shadow evaluation + frozen verifier
        |
        v
production hierarchy
        |
        +--> local specialist
        +--> Jev / stronger local model
        +--> frontier LLM only for the hard tail
```

Success means the frontier LLM receives **less irrelevant context**, performs **fewer repetitive decisions**, and spends more of its compute on genuinely novel reasoning.

---

## P0 - GPU population evolution (new critical path)

**Status: next implementation**

Use local GPU (RTX 3080 Ti) as a massive parallel search engine for tiny mushroom-body / fly candidates. Do not use it to speed up a single 640-weight inference.

1. Add `local_jax` backend reproducing current `local_plasticity` in `float32`.
2. Parity against CPU on locked Evolution Lab recovery splits.
3. `vmap` over population `P`; scale until VRAM or throughput saturates.
4. GPU filters; **frozen CPU judge** serial-rebenches before keep.
5. Record joules/verified candidate via NVML when available.

vLLM SLM teacher/fallback is a parallel lane, not a substitute.

Then continue P0 OpenJev substrate preservation below.

---

## P0b - preserve the measured OpenJev foundation

**Status: existing substrate**

Keep the current reproducible decision-runtime work intact:

- typed runtime-defined choices;
- direct generation-free option scoring;
- shared-state reuse;
- trainable small scorers;
- frozen benchmark fixtures and raw evidence;
- Evolution Lab integration.

Do not rewrite historical benchmark claims without new row-level evidence.

**Exit:** the current OpenJev evaluation remains reproducible while z0int grows around it.

---

## P1 - private onboarding and data plane

**Priority: critical path**

Build a local-first onboarding process designed to ingest a broad user-owned history.

Initial adapters should target:

- GitHub repositories, commits, issues, pull requests, reviews, and discussions;
- Google Takeout, including relevant Search/Chrome, Drive, Gmail, Calendar, and related exports;
- personal message archives;
- ChatGPT data exports;
- Claude conversation exports;
- Hermes / OMP / Pi / Codex / Claude Code / Cursor / OpenCode histories where available;
- Hermes `state.db` and safe local state;
- later, prospective Memento computer-use recordings.

Requirements:

- preserve source, timestamp, author/actor, and provenance;
- distinguish authored content from received/third-party content where possible;
- local raw-data vault;
- exclusion/deletion support;
- secret/credential filtering;
- privacy classification;
- no raw private corpus committed to public git;
- external training sees only explicitly sanitized non-PII material.

Do **not** collapse every source into one giant text file.

**Exit:** a repeatable local ingest can rebuild a private indexed corpus from source exports.

---

## P2 - episode compiler and automatic supervision

**Priority: critical path**

Convert raw history into training/evaluation episodes.

Canonical idea:

```text
available context / observation
        |
        v
decision or action
        |
        v
next state / tool result / verifier
        |
        v
outcome
```

Useful automatic supervision includes:

- harness tool/action choice;
- retries and recovery actions;
- command/test results;
- PR review and merge/reject outcomes;
- Jev probability distributions;
- conversation corrections and follow-ups;
- model/effort routing choices;
- deterministic verification results.

Training records should carry:

- source reference;
- privacy class;
- label source;
- label confidence;
- outcome/verifier;
- model/teacher distribution when available.

Avoid random train/test leakage. Split primarily by **time**, session, and held-out task/repo families.

Maintain a small sealed human-audited evaluation set. It is for judging the auto-labelers and models, not bulk training.

**Exit:** one command can compile sanitized history into reproducible train/val/confirm/OOD episode sets.

---

## P3 - first useful personal specialists

**Priority: immediate product value**

Start with bounded decisions that already have strong labels and obvious fallbacks.

First candidate families:

- intent / skill routing;
- tool-family selection;
- context relevance and retrieval;
- retry / recover / escalate;
- verification-needed / done;
- model / effort routing.

Train and compare:

- deterministic rules;
- ridge / linear baseline;
- MLP / GRU controls;
- mushroom-body `local_plasticity`;
- OpenJev trainable scorer;
- small SLM/SVLM only when justified by the task.

Do not optimize for raw top-1 accuracy alone. Measure **risk/coverage**: how much traffic can a specialist safely absorb before escalating?

Deploy in shadow first.

**Exit:** at least one specialist safely removes measurable frontier-model latency/context on real traffic.

---

## P4 - evolve the dataset, not just the model

**Priority: core research loop**

Extend Evolution Lab genomes so the **data recipe is evolvable**.

Example search variables:

```text
data:
  source mixture
  history window
  temporal horizon
  gold/silver/teacher weights
  hard-negative ratio
  pseudo-label threshold
  context fields
  privacy-safe feature projection

model:
  family
  encoder
  PN/KC dimensions
  k-winners
  recurrence
  plasticity
  MaleCNS-derived circuit taps

policy:
  confidence threshold
  abstention threshold
  fallback
```

ABAB should operate at two timescales:

- **A:** diagnose the highest-value uncertainty or failure concentration;
- **B:** execute a dataset/model experiment against the frozen judge;
- optional **C:** run the cheapest discriminating experiment when another broad sweep would waste compute.

The judge, sealed battery, privacy policy, and safety gates are never evolvable.

**Exit:** measured examples where changing the data recipe improves a production specialist more than ordinary parameter tuning.

---

## P5 - an army of flies

**Priority: specialization after the first win**

Do not build one universal fly.

Build independent specialists for recurring decision families, each with its own verifier, confidence calibration, fallback, and promotion record.

Potential specialists:

- coding-tool router;
- skill/context router;
- recovery controller;
- verification controller;
- memory relevance filter;
- subagent/model router;
- computer-use transition controller;
- routine compiler detector.

The mushroom body is the default cheap learner for bounded associative decisions.

MaleCNS / richer fly circuits are a **research substrate for temporal computation**, not automatically a production dependency. Search circuit subsets, taps, pinouts, recurrence, and plastic regions only where temporal structure appears to matter.

Any MaleCNS-derived computation that wins should be challenged by:

- direct input;
- GRU/RNN;
- random reservoir;
- rewired topology;
- distilled small motif.

If a distilled motif preserves the useful behavior, deploy the motif rather than the full simulation.

**Exit:** multiple independently verified specialists collectively absorb meaningful repeated agent traffic.

---

## P6 - identity and intent compiler

**Priority: long-term personalization**

Carry forward the central `sft-svlm` thesis:

> **learn stable behavior; retrieve mutable truth.**

Learned identity may include stable patterns such as:

- preferred level of detail;
- recurring workflow choices;
- risk/verification preferences;
- routing tendencies;
- interaction style;
- common intent transformations.

Retrieval remains responsible for:

- current projects;
- current documents;
- mutable facts;
- conversations;
- relationships/context;
- fresh external information;
- provenance.

The personal layer should transform:

```text
raw request
+ relevant retrieved identity/context
        |
        v
intent hypothesis
constraints
desired outcome
likely workflow
required context
confidence
```

The goal is not psychological profiling. The goal is better task execution and less repeated context reconstruction.

**Exit:** personal context measurably improves held-out intent resolution or reduces context/tool/model work without harming task success.

---

## P7 - AODL bridge for explicit intent

**Priority: optional after measured intent wins**

[AODL](https://github.com/kvnloo/aodl) can provide a portable typed language for intent and orchestration once z0int can reliably infer those structures.

Potential path:

```text
natural language
     |
     v
z0int personal intent compiler
     |
     v
AODL intent graph / constraints / budgets
     |
     v
Hermes / OMP / other harness compiler
```

Do not block z0int training or deployment on AODL.

Do not add `mushroomBody`, `fly`, `MaleCNS`, or `Jev` as new AODL kinds merely to mirror implementation details.

Use AODL when an explicit typed representation makes execution, portability, verification, or intent inspection measurably better.

**Exit:** one real workflow where z0int -> AODL improves execution or inspection versus the unstructured baseline.

---

## P8 - computer-use and SVLM data

**Priority: begins prospectively**

There is no historical Memento corpus yet, so visual computer-use learning starts by improving collection going forward.

Extend Memento-style recording toward event-synchronous episodes:

```text
screen_before
+ OCR / AX / app state
        |
human or agent action
        |
screen_after_stable
+ state delta
        |
outcome
```

Sensitive typed values must never become ordinary training text.

Historical actionless video can support self-supervised representation learning, but actual action-grounded training should prefer newly instrumented traces.

Revisit the original SVLM path here as a **measured competitor**, not the assumed final architecture.

**Exit:** a vision/temporal specialist beats structured/text-only controls on a computer-use family after paying its full encoder cost.

---

## P9 - self-compiling personal intelligence

The desired steady state is a hierarchy:

```text
deterministic rule / compiled routine
              |
              v
mushroom-body specialist
              |
              v
temporal / fly specialist
              |
              v
OpenJev / local semantic model
              |
              v
Jev / stronger decision model
              |
              v
frontier LLM
```

Repeated behavior should migrate downward only when verified.

Novel tasks begin near the top. As they recur and produce enough evidence:

```text
frontier reasoning
      -> bounded decision family
      -> trained specialist
      -> stable routine
      -> deterministic code
```

The hard tail remains with the frontier model.

---

## Evaluation contract

Primary measurements:

- verified task success;
- safe coverage / escalation rate;
- end-to-end latency;
- p95/p99 decision latency;
- frontier-model calls removed;
- input tokens/context removed;
- downstream corrections/retries;
- OOD transfer;
- human intervention;
- deployment cost;
- joules per verified success when actually measurable.

Hard gates:

- no additional hard-policy violations;
- privacy boundary holds;
- secrets are not exposed to training/inference paths that do not require them;
- candidate beats or matches a simple baseline;
- sealed holdout does not regress beyond the registered margin.

A candidate that is biologically interesting but does not improve the measured frontier is not promoted.

---

## Repo responsibilities

| Repo | Role |
| --- | --- |
| `kvnloo/z0intelligence` (package `z0int`) | personal decision runtime, scorers, onboarding/training surfaces |
| `kvnloo/evolution-lab` | experiment genomes, ABAB, DAgger, search, frozen promotion gates |
| `kvnloo/frontier-kb` | research memory, evidence, claims, kill criteria |
| `kvnloo/aodl` | optional typed intent/orchestration IR |
| `NousResearch/hermes-agent` | runtime state, tools, messaging, memory, execution |
| `can1357/oh-my-pi` | fast coding harness and judgment/decision surfaces |
| `kvnloo/Memento` | prospective local screen/computer-use data source |

---

## Non-goals

- Uploading a person's raw private corpus to a public repository.
- Memorizing all mutable personal facts into model weights.
- Training MaleCNS simply because it is biologically interesting.
- Replacing frontier LLMs on genuinely open-ended reasoning.
- Adding frameworks before a measured bottleneck requires them.
- Letting the training loop modify its own judge, privacy boundary, or sealed evaluation set.
- Claiming that a small specialist understands a person's identity simply because it memorized their text.

The project succeeds when **verified outcomes improve while expensive generic inference decreases**.

## Compiler stack status (2026-09-18 integration)

The routine → cascade → ABAB credit → AODL plan → repair loop is **implemented in source** on branch `integrate/z0int-future-stack`. See README “Future compiler stack” for the honesty split (synthetic measured vs not product-validated). Live promotion still requires sealed private cohorts and independent full-cascade credit before traffic.
