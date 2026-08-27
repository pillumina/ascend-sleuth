# ascend-sleuth

[![platform: Ascend NPU](https://img.shields.io/badge/platform-Ascend%20NPU-CC0000?logo=huawei&logoColor=white)](https://www.hiascend.com/)

[中文](README.md) · English

A diagnostic tool suite for Ascend training and inference support. It turns each problem investigation into reusable knowledge, so the next occurrence of a similar issue hits the answer directly.

Built to the [Agent Skills](https://agentskills.io/) standard, it runs in any compliant agent such as pi, Claude Code, or Codex.

**Jump to**: [Why](#why-it-exists) · [Quick start](#quick-start) · [The four skills](#the-four-skills) · [How it works](#how-it-works) · [Documentation](#documentation)

---

## Why it exists

Ascend support engineers deal with three classes of problems every day: training or inference interrupts (hangs, crashes, OOM), precision anomalies (loss divergence, FP8 decay), and performance regressions (throughput drops, high communication overhead). Root causes repeat heavily, yet the knowledge lives scattered across personal notes, IM threads, and wikis. New cases arrive weekly, A2/A3/A5 platform differences keep widening, and any scheme that depends on one person's manual upkeep decays within weeks.

ascend-sleuth structures this experience into a knowledge base. At diagnosis time, symptoms route to verified cases. After a problem is located, new knowledge enters a review queue, and a weekly maintenance pass handles deduplication, promotion, and retirement. The knowledge base calibrates itself through use, without depending on any individual's sustained effort.

## Quick start

### Installation

```bash
npx skills@latest add pillumina/ascend-sleuth
```

Pick the skills to install and the target agent, or manually add the `skills/` directory to the search path in pi or Claude Code. All four (recommended — `resume-diagnosis` is part of the feedback loop, see below):

```bash
npx skills@latest add pillumina/ascend-sleuth -g -a pi -a claude-code \
  -s diagnose -s to-postmortem -s knowledge-groom -s resume-diagnosis
```

Once loaded, invoke with `/skill:<name>` in your agent.

### A diagnosis

Give the agent the customer's symptoms, framework, and log snippets — the agent does not access customer environments; all information comes from you:

```
/skill:diagnose

Customer A5 (950) training hangs at step ~3000, all_to_all timeout, world_size=128.
Framework mindspeed-llm 2.5.0. Error stack tail: [paste relevant rank's log snippet]
```

The agent routes to `training/mindspeed-llm/` and matches cases. On a hit it produces a structured result (CASE-ID, confidence, fix, rollback); on a miss it falls back to deep investigation. When information is insufficient, the agent states explicitly what to obtain from the customer. Every step is traced — even if interrupted, `/skill:resume-diagnosis` picks up where it stopped.

### Capturing an investigation

Any source — a local agent session, a Kimi chat, hand-written notes, a wiki export — can flow into the knowledge base:

```
/skill:to-postmortem "[paste conversation or notes]"            # inline
/skill:to-postmortem ~/cases/custA/notes.md                     # single file
/skill:to-postmortem ~/cases/custA/ ~/cases/custB/hang.md       # multiple files
/skill:to-postmortem ~/cases/wiki-export/                       # directory (bulk import)
```

The agent extracts symptoms and root cause, proposes a namespace for confirmation, produces a YAML draft and postmortem with redaction applied, and lands them in the review queue. You can also just say "capture this one" after a `/skill:diagnose` finishes — the agent triggers it automatically.

## Knowledge acquisition

Once the skills are installed, the knowledge base takes one of three forms — pick by how you work. The install-command difference is `-g` (git mode) vs `-s` (skill selection):

| Form | Install command | Result | Best for |
|---|---|---|---|
| **Accumulate your own** (skills only) | `npx skills add -s diagnose -s to-postmortem -s knowledge-groom -s resume-diagnosis` | Installs `skills/` methodology only; `knowledge/` stays empty | New teams, different problem domains, private knowledge |
| **Consume existing** (full repo) | `npx skills add -g pillumina/ascend-sleuth` (git mode pulls the whole repo, including `knowledge/`) | Use upstream-verified cases directly, keep accumulating | Existing corpus, overlapping problem domain, want reuse |
| **Tailored surface** (sparse checkout) | `git clone` or `-g` first, then `git sparse-checkout` with a directory whitelist | Keep only the parts you need (e.g. `vllm-ascend` cells + `common/`) | Once the corpus grows, bandwidth/storage-constrained, only your framework's knowledge |

All three share the same skills and machinery, and they compose: an accumulating team can optionally feed sanitized cases back upstream, thickening the public corpus (see [Deployment modes](#deployment-modes), framework fork). Exact `-g`/`-s` behavior may differ across installer versions — `npx skills add --help` is authoritative.

**Sparse checkout caveat**: `_index.yaml` is a generated artifact covering the full corpus. After a sparse checkout, rerun `python3 scripts/build_index.py` to rebuild the index — it indexes only the cells you pulled, and retrieval stays within your knowledge surface. `common/` is mandatory (triage fallback depends on it) and must not be dropped from the whitelist. Design rationale in [ADR-0005](docs/adr/0005-knowledge-consumption-split.md).

## The four skills

| Skill | Purpose | When to use | Invocation |
|---|---|---|---|
| `diagnose` | Core diagnostic loop: route by symptoms, match and verify cases, deliver fixes or fall back to deep investigation; records a trace throughout | Training or inference problems of the interrupt / precision / performance classes | Explicit `/skill:diagnose` |
| `to-postmortem` | Distill an investigation into knowledge; accepts any source, runs validation and redaction, outputs into the review queue | After a problem is located, wherever it was located | Auto-triggerable |
| `knowledge-groom` | Periodic maintenance: batch-process the review queue, promote, deduplicate, recompute confidence, soft-retire, rebuild the index | Domain owner, weekly | Explicit `/skill:knowledge-groom` |
| `resume-diagnosis` | Resume an interrupted diagnosis: reads the state file and trace, restates the situation, then continues | Diagnosis interrupted by meetings or context compaction | Explicit `/skill:resume-diagnosis` |

Full operational detail (severity gates, trace rules, semantic validation) lives in each `skills/<name>/SKILL.md`. The three diagnostic skills are user-only — diagnostic decisions are human-triggered. `to-postmortem` may auto-trigger, lowering the barrier to capturing knowledge.

## How it works

Knowledge is organized in three tiers, loaded on demand to control context cost:

| Tier | Content | When loaded |
|---|---|---|
| Tier 1 | `triage-tree.yaml`: symptom-to-namespace mapping, at most 30 branches | Always |
| Tier 2 | Structured case rules under `knowledge/` | Two-phase after symptom match: read the generated index `knowledge/_index.yaml` to filter candidates, then load full bodies to verify |
| Tier 3 | Raw investigation records under `postmortems/` | Keyword-search fallback when the upper tiers miss |

Problems decompose along two orthogonal dimensions. **Where to look** is decided by training-vs-inference and framework, which selects the namespace (e.g. `training/mindspeed-llm/`) — this is the knowledge base's directory structure. **What kind** is decided by problem class: interrupt, precision, and performance each carry their own matching shape and default investigation approach — error-signature grep for interrupts, numeric threshold assertions for precision, profiler metric comparison for performance; these are never mixed.

Every diagnostic step is traced: which namespaces were loaded, which checks ran in what order. Traces exist for post-hoc attribution. A misdiagnosis is either a wrong case in the knowledge base or a deviation in the agent's execution — the two demand entirely different fixes, and confusing them corrupts cases that were correct.

Two loops drive the system. The diagram below is the full panorama; the specific mechanisms are developed later in this document and in the specialized docs — skip it on first read and come back when needed:

```
[Diagnosis loop · per incident · minutes]

 Engineer (customer symptoms / stack tails / version combo)
   └► /skill:diagnose
        ├► Tier 1  triage-tree.yaml symptom routing
        ├► Tier 2  _index.yaml phase-1 filter → top ≤5 full verification
        │           ├─ hit → severity gate → fix (data-loss-risk: halt only)
        │           │          └► feedback_pending marker → engineer reports
        │           │                → confidence rewritten (hits/misdiagnoses)
        │           └─ miss → Tier 3 postmortems/ search → human + agent deep dive
        └► trace throughout → diagnosis_state-<session_id>.yaml

[Evolution loop · weekly · git-gated]

 /skill:to-postmortem (any source: session / Kimi / notes / wiki)
   └► postmortems/inbox/ (review queue, redacted on entry)
        └► /skill:knowledge-groom weekly batch
             ├ pre-triage new_pattern / variant_of / covered_by (advice + evidence)
             ├ human review: accept / adjust / reject (~30s per item)
             ├ high-risk changes → kb/high-risk → dual-owner sign-off
             └ change PR (protected branch + CODEOWNERS + CI: build_index --check) → merge
                  ├ new     → promoted to knowledge/<ns>/ + _index.yaml rebuilt
                  ├ variant → merged into existing case (compat extended)
                  └ covered → postmortem retained in Tier 3 (not discarded)
                              └──► next diagnosis hits directly — the learning loop
```

![ascend-sleuth architecture](docs/diagrams/ascend-sleuth-architecture.png)

How the system improves itself with use, and what guardrails keep each mechanism from degrading the knowledge base, is fully designed in [docs/evolution.md](docs/evolution.md).

## Core design principles

A user-facing selection; the complete normative original (eleven principles, each with derivation and forbidden violations) is [docs/design-principles.md](docs/design-principles.md).

**Carry rules in structure, not in discipline.** Whatever can be fixed by file structure is not left to the model's compliance: phase-1 loading is pinned to reading the generated index, feedback tracking lives in a state-file marker, index freshness is hard-checked by a script. Rules written into structure do not fluctuate with execution quality.

**Retrieval nominates; verification gates.** Symptom matching only produces candidates. Fix suggestions are emitted only after diagnosis checks verify against real information from the customer environment, and root causes marked data-loss-risk yield halt-and-preserve instructions only. One extra round of questions costs far less than a single misdiagnosis.

**Semantics belong to the agent; the substrate stays lexical.** The agent normalizes an engineer's fuzzy description into a greppable error signature; the knowledge base itself remains YAML and git — diffable, auditable, revertible. This is the direct reason vector retrieval is not introduced; full argument and re-evaluation triggers in [ADR-0002](docs/adr/0002-retrieval-no-rag-lightweight-index.md).

**The size cap is an architectural commitment.** The 30-cases-per-namespace cap is not tidiness: it is what guarantees the full index loads in one read and brute-force filtering holds forever. The cap precedes any retrieval infrastructure.

**Automation proposes; humans decide.** Pre-triage, candidate-case drafting, and confidence recomputation only produce advice with evidence; adopting, adjusting, or rejecting is the maintainer's call. Human work moves up from structuring to quick approval — from twenty minutes per item to under half a minute.

**Human review runs in batches.** Under continuous intake, item-by-item immediate review contradicts how engineers work. Pending items enter the inbox queue; the owner processes them in one weekly sitting, and items lingering too long are flagged automatically.

**Observability precedes improvement.** Misdiagnosis attribution (fix the knowledge or fix the process), routing accuracy, and feedback capture rate all derive from traces. Without traces, none of these mechanisms can be evaluated — or improved.

**Methodology and knowledge assets are separate.** `skills/`, `scripts/`, `docs/` form a public, reusable framework; `knowledge/` and `postmortems/` are team-owned assets, redacted before entry. A team can either maintain one centralized repository or fork and accumulate its own knowledge — both modes share the same machinery.

## Documentation

- **[Design theory](docs/design-theory.md)** — the formal kernel (four axioms deriving all design principles) and its applicability
- **[Design principles](docs/design-principles.md)** — eleven normative articles constraining all design and evolution
- **[Self-evolution design](docs/evolution.md)** — how the system gets more accurate with use, and each mechanism's guardrails
- **[Roadmap](docs/roadmap.md)** — the gate-driven evolution plan; entry conditions and acceptance criteria per item
- **[Git workflow](docs/git-workflow.md)** — how review, gating, and merge land in practice (labels, CODEOWNERS, CI, dual sign-off)
- **[Evaluation](docs/eval.md)** — before/after regression checks for skill changes; [eval report 0001](docs/eval-reports/0001-vllm-ascend-batch.md) records the first real-data measurement
- **[Glossary](CONTEXT.md)** — canonical definitions of case, postmortem, groom, trace, and the rest

### Repository layout

The knowledge base itself (`knowledge/`) is organized by framework and category:

```
knowledge/
├── _index.yaml              Tier-2 generated index (scripts/build_index.py; read in phase 1, rebuilt on change; score only)
├── training/{mindspeed-llm,mindspeed-mm,verl}/
├── inference/{vllm-ascend,sglang}/
│   └── vllm-ascend/         (framework × category cells, ADR-0004)
│       ├── interrupt/  ├── precision/  ├── performance/  └── other/
├── common/                  authoritative cross-framework records (promoted by groom)
├── _archive/                soft-retired stale cases
└── platforms/{a2,a3,a5}.md  platform background
```

Key files and directories outside `knowledge/`:

```
triage-tree.yaml             Tier-1 routing (symptom → namespace)
postmortems/                 Tier-3 raw records; inbox/ is the review queue
examples/sample-case.yaml    canonical sample (full schema demo)
CONTEXT.md                   domain glossary
scripts/                     build_index.py, trace_metrics.py, replay_prep.py, issue_filter.py
eval/golden/                 regression fixtures
docs/                        documentation system (see Documentation index above)
CODEOWNERS.example           enable once owners are named
.github/                     kb-checks CI + scenario PR templates
```

Before changing a skill itself, run the golden regression suite per [docs/eval.md](docs/eval.md) and confirm that scenarios which previously matched still do.

## Deployment modes

Both modes are supported; the inbox, groom, index, and CI machinery work identically in each:

- **Centralized**: training and inference teams share one repository; `CODEOWNERS` assigns approval rights by namespace, and changes to `common/` or `triage-tree.yaml` require dual-owner sign-off.
- **Framework fork**: a team forks this repository and accumulates or imports its own knowledge; upstream syncs methodology directories only (`skills/ scripts/ docs/ examples/ eval/ .github/`) — knowledge directories never merge from upstream, so there is no conflict surface.

Git-level details of review, distribution, and merge are in [docs/git-workflow.md](docs/git-workflow.md).

## Daily workflow

```
Incident arrives → /skill:diagnose (local agent diagnosis + knowledge match)
  For emergencies, tell the agent it's urgent → stabilize advice first, no deep dive
Problem located → /skill:to-postmortem → postmortems/inbox/ (review queue)
  (whether located via /diagnose, Kimi, or by hand — everything funnels here)
Interrupted → /skill:resume-diagnosis
Domain owner weekly → /skill:knowledge-groom batch-processes inbox
  → change PRs (triage labels + high-risk dual sign-off + kb-checks CI) → merge (index rebuilt per batch)
Fix applied → report the outcome (diagnose/resume asks on startup) → confidence rewritten
```

Fixes the agent delivers are suggestions; humans apply them to customer environments. The agent never touches production.

## Roadmap

The roadmap is gate-driven: every item defines an entry condition (data- or event-triggered) and acceptance criteria, rather than a calendar date.

- **v1 (implemented)**: three-tier retrieval with generated index, intake queue with groom batching, trace and feedback loop, git gating and CI.
- **v1.5 (unlocked by gates)**: router evolution from trace misroutes, semi-automated fixture replay, agent-drafted candidate cases, per-team metrics and capacity forecasting.
- **v2**: trace structure mining, trusted auto-promotion.
- **Explicitly not doing**: vector retrieval/RAG, ANN, cross-organization federation (argument in [ADR-0002](docs/adr/0002-retrieval-no-rag-lightweight-index.md)).

Requirements, acceptance criteria, entry gates, and standing checkpoints for each item: [docs/roadmap.md](docs/roadmap.md).
