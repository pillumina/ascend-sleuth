# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

ascend-sleuth is an Agent Skills-based diagnostic system for Huawei Ascend NPU training/inference issues. It structures support knowledge into an evolvable, multi-tier system so problem diagnosis improves over time rather than rotting.

This is a **knowledge/skills repo** — there is no build, no lint, no test suite, no application code. Everything is YAML case files, Markdown skill definitions, and Markdown postmortems.

## Architecture

### Three-tier knowledge loading (controls context cost)

| Tier | Content | When loaded |
|------|---------|-------------|
| Tier 1 | `triage-tree.yaml` — symptom → namespace routing (≤30 branches) | Always |
| Tier 2 | `knowledge/<ns>/*.yaml` — structured case rules | Two-phase: index first (id/symptoms/quickly_check ~70 tok each), then full body for candidates ≤5 |
| Tier 3 | `postmortems/` — raw investigation records | Keyword grep fallback when Tier 2 misses |

### Two orthogonal problem dimensions

- **Where** (training vs inference × framework) — determines which namespace directory to search. Encoded in `triage-tree.yaml`'s `search_namespaces`.
- **What** (interrupt / precision / performance) — determines the diagnosis path and `quickly_check` shape. Interrupt uses error-signature grep, precision uses numeric threshold assertions, performance uses profiler metric comparisons. **Do not mix these.**

### Skills

Four skills in `skills/<name>/SKILL.md`, following the [Agent Skills](https://agentskills.io/) spec:

- **`diagnose`** — Core diagnostic loop: symptom collection → triage-tree routing → two-phase Tier 2 loading → verify diagnosis checks → output fix or fall back to deep investigation. Writes trace to `diagnosis_state-<session_id>.yaml` on every step. `disable-model-invocation: true` (user-triggered only).
- **`to-postmortem`** — Knowledge injection entry. Accepts inline paste, single file, multiple files, or directory. Extracts symptoms/root cause/fix, suggests namespace, runs semantic validation + redaction, outputs YAML draft + postmortem.md. Decoupled from diagnose — any investigation source can feed it.
- **`knowledge-groom`** — Weekly maintenance: promote postmortems to Tier 2, validate references, detect value duplication, recalculate confidence scores with time decay, soft-retire stale cases, suggest namespace splits. `disable-model-invocation: true`.
- **`resume-diagnosis`** — Reads `diagnosis_state-*.yaml` to resume an interrupted diagnosis session. `disable-model-invocation: true`.

### Case schema (YAML in `knowledge/<ns>/`)

Each case file has: `id`, `title`, `category` (interrupt|precision|performance), `tags`, `platforms`, `compat` (multi-dimensional: framework/CANN/HDK version ranges), `confidence` (hits/misdiagnoses/score managed by groom), `symptoms`, `quickly_check` (primary + fallback regex), `diagnosis` steps with `command_template`/`expected`/`fix_on_mismatch`/`rollback`, `severity` (benign|service-affecting|data-loss-risk), `fix_type` (env-var|config-change|code-patch|pending-investigation), `root_cause`, `fix`.

Version matching is **soft**: compat mismatch downgrades confidence but never hard-excludes a case. Undefined dimensions are skipped.

### Severity gate

- `benign` → give fix directly
- `service-affecting` → give fix but flag `fix_side_effects` (e.g., requires-restart)
- `data-loss-risk` → **do not give fix**; output "halt training, preserve state, notify owner"

### Platform dispatch

A2 (910A), A3 (910B), A5 (910C) differences are **field-level** within cases, not separate cases. A single case can have multiple `diagnosis` blocks keyed by `platforms`. Platform background knowledge in `knowledge/platforms/*.md`.

Key platform facts:
- A2: No `HCCL_BUFFSIZE`, no FP8 support. HCCL behavior radically different from A3/A5.
- A3: BF16 primary. HCCL similar to A5.
- A5: FP8 precision issues are A5-only. Large-scale EP (world_size ≥64) communication bottlenecks common.

### Trace and misdiagnosis attribution

Every diagnose step writes to `diagnosis_state-<session_id>.yaml` trace array. On misdiagnosis, read the trace to determine: **case error** (fix the knowledge YAML) vs **execution error** (fix the skill body). Without trace, misdiagnosis attribution is impossible and you risk corrupting correct cases.

### Eval

Golden-case regression suite in `eval/golden/`. Public repo contains only constructed examples (no real customer data). Real fixtures go in a private repo. Run before/after skill changes: feed fixed input via replay mode, verify namespace routing + case matching + fix content against `expected`. LLM non-determinism means asserting "top-3 hit" rather than "must be first."

## Key constraints

- **Diagnose does not access customer environments.** All info (logs, versions, errors) comes from the engineer pasting it. The agent's role is to ask for what's missing when information is insufficient.
- **Agent never applies fixes to production.** Fixes are suggestions for the human to apply.
- **Cold start:** The repo is in v1 skeleton state. `knowledge/` directories exist but are mostly empty (one seeded case: `SGL-PD-HEAP-001`). The canonical sample is `examples/sample-case.yaml`.
- **Public/private separation:** `skills/`, `references/`, `examples/` are methodology (public). `knowledge/` and `postmortems/` with real content contain customer data and must stay private. `.gitignore` enforces this boundary for `diagnosis_state*.yaml` files.
- **No more than 2 consecutive failed case attempts** — fall back to human on the third (serial protection against misdiagnosis cascades).
- **Log clipping is mandatory.** Only paste failed-rank logs + error stack tails into context. Full profiler data overwhelms the ~120K token reasoning sweet spot.
