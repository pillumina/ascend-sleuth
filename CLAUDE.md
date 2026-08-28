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
| Tier 2 | `knowledge/<ns>/*.yaml` — structured case rules | Two-phase: read generated index `knowledge/_index.yaml` first (one read; id/symptoms/quickly_check ~70 tok each), then full body for candidates ≤5. Rebuild index after any case change via `scripts/build_index.py` |
| Tier 3 | `postmortems/` — raw investigation records | Keyword grep fallback when Tier 2 misses |

### Two orthogonal problem dimensions

- **Where** (training vs inference × framework) — determines which namespace directory to search. Encoded in `triage-tree.yaml`'s `search_namespaces`.
- **What** (interrupt / precision / performance) — determines the diagnosis path and `quickly_check` shape. Interrupt uses error-signature grep, precision uses numeric threshold assertions, performance uses profiler metric comparisons. **Do not mix these.**

### Skills

Five skills in `skills/<name>/SKILL.md`, following the [Agent Skills](https://agentskills.io/) spec:

- **`diagnose`** — Core diagnostic loop: symptom collection → triage-tree routing → two-phase Tier 2 loading → verify diagnosis checks → output fix or fall back to deep investigation. Writes trace to `diagnosis_state-<session_id>.yaml` on every step. On fix delivery writes `feedback_pending`; any diagnose/resume startup nags for the outcome and updates case confidence. `disable-model-invocation: true` (user-triggered only).
- **`to-postmortem`** — Case-knowledge injection entry. Accepts inline paste, single file, multiple files, or directory. Extracts symptoms/root cause/fix, suggests namespace, runs semantic validation + redaction, outputs YAML draft + postmortem.md into `postmortems/inbox/` (weekly review queue). Decoupled from diagnose — any investigation source can feed it.
- **`to-reference`** — Prior-knowledge injection entry. Accepts inline paste, file, URL crawl (`--ingest`), or case-set generalization (`--ingest-cases`). Extracts facts/methodologies, classifies by `references/_types.yaml`, runs a grill phase (repeated intent confirmation for engineer-input and case-derived), outputs schema-complete YAML draft into `references/_inbox/` (maintainer-reviewed queue). Never produces `status: active` — drafts only. Decoupled from diagnose, parallel to to-postmortem.
- **`knowledge-groom`** — Weekly maintenance: batch-process the inbox queue (pre-triage new_pattern / variant_of / covered_by, human accepts), promote postmortems to Tier 2, validate references, detect value duplication, recalculate confidence scores with time decay, soft-retire stale cases, report namespace capacity, rebuild `knowledge/_index.yaml`. `disable-model-invocation: true`.
- **`resume-diagnosis`** — Reads `diagnosis_state-*.yaml` to resume an interrupted diagnosis session. `disable-model-invocation: true`.

### Case schema (YAML in `knowledge/<ns>/`)

Each case file has: `id`, `title`, `category` (interrupt|precision|performance), `tags`, `platforms`, `compat` (multi-dimensional: framework/CANN/HDK version ranges), `confidence` (hits/misdiagnoses/score managed by groom), `symptoms`, `quickly_check` (primary + fallback regex), `diagnosis` steps with `command_template`/`expected`/`fix_on_mismatch`/`rollback`, `severity` (benign|service-affecting|data-loss-risk), `fix_type` (env-var|config-change|code-patch|pending-investigation), `root_cause`, `fix`.

Optional field — `ref_knowledge`: structured linkage to prior-knowledge entries in `references/`. Each entry is `ref: <reference-id>` + `role: signature-source | fix-methodology | root-cause-context`. `ref` must exist in `references/` and `role` must be legal — enforced by `scripts/verify_references.py` (dangling refs and illegal roles fail CI). The reverse view (which cases reference a given entry) is derived by that script, never stored on the reference side — one relation, stored once. Not required on existing cases; add as needed.

Version matching is **soft**: compat mismatch downgrades confidence but never hard-excludes a case. Undefined dimensions are skipped.

### Severity gate

- `benign` → give fix directly
- `service-affecting` → give fix but flag `fix_side_effects` (e.g., requires-restart)
- `data-loss-risk` → **do not give fix**; output "halt training, preserve state, notify owner"

### Platform dispatch

Platform differences are **field-level** within cases, not separate cases. A single case can have multiple `diagnosis` blocks keyed by `platforms` (e.g. `A2-910B`, `A3-910C`, `A5-950`); a case with no `platforms` field is treated as cross-platform. Platform background docs were abolished (agent-generated, zero external sources) — platform facts belong in the reference layer (`references/platform-facts/`, populated via to-reference with real sources). Until that layer has content, **no platform prior is injected into diagnostic context**: each case carries its own platform evidence in its `platforms`-keyed diagnosis branches.

### Trace and misdiagnosis attribution

Every diagnose step writes to `diagnosis_state-<session_id>.yaml` trace array. On misdiagnosis, read the trace to determine: **case error** (fix the knowledge YAML) vs **execution error** (fix the skill body). Without trace, misdiagnosis attribution is impossible and you risk corrupting correct cases.

### Eval

Golden-case regression suite in `eval/golden/`. Public repo contains only constructed examples (no real customer data). Real fixtures go in a private repo. Run before/after skill changes: feed fixed input via replay mode, verify namespace routing + case matching + fix content against `expected`. LLM non-determinism means asserting "top-3 hit" rather than "must be first."

## Key constraints

- **Normative foundation:** all design/implementation/evolution changes must be traceable to `docs/design-principles.md` (the normative articles); the derivation chain lives in `docs/design-theory.md` (four axioms → formulas → principles). An untraceable rule is suspect; an unexplainable real-world choice indicts the theory.
- **Diagnose does not access customer environments.** All info (logs, versions, errors) comes from the engineer pasting it. The agent's role is to ask for what's missing when information is insufficient.
- **Agent never applies fixes to production.** Fixes are suggestions for the human to apply.
- **知识库当前结构性状态**：实时数字用 `python3 scripts/build_index.py`（生成 `knowledge/_index.yaml` 头部注释）；按周 append 的指标快照见 `docs/metrics.md` 末尾节。CLAUDE.md 只保留**结构性信号**（不随每周批量腐烂）：
  - `training/{mindspeed-llm,mindspeed-mm,verl}/` 与 `common/` 当前为空——agent 路由到这些 namespace 应直接走 Tier 3 fallback，不假装有内容可检（与 `triage-tree.yaml` 头部注释同源）
  - `inference/vllm-ascend/interrupt` 格子历史上接近 soft_cap=30（容量治理上限），触发过容量治理评估；agent 加载阶段一索引后若候选 ≥5，应留意 soft_cap 信号
  - canonical sample 仍是 `examples/sample-case.yaml`
- **Public/private separation:** `skills/`, `references/`, `examples/` are methodology (public). `knowledge/` and `postmortems/` with real content contain customer data and must stay private. `.gitignore` enforces this boundary for `diagnosis_state*.yaml` files.
- **Index freshness:** `knowledge/_index.yaml` is generated by `scripts/build_index.py` and committed. After changing any case YAML, regenerate it; `--check` (run by groom and the kb-checks CI) fails on staleness. Retrieval is deliberately lexical/structural — no vector RAG (see `docs/adr/0002`).
- **Git gating:** KB changes land via PR — triage labels (`kb/new-pattern|variant|covered`), `kb/high-risk` dual sign-off, CODEOWNERS-based review (see `docs/git-workflow.md`; `CODEOWNERS.example` is a placeholder until owners are named). Deployable centralized or as a framework fork — knowledge dirs never merge from upstream.
- **Skill self-containment (CI-enforced):** skill files (`skills/**`) must not reference ADR numbers (`ADR-\d{4}`) — ADRs get revised/absorbed, a number anchor makes skill behavior look externally defined. Behavior rules must be inline; traceability belongs to git/PR/ADR history. This is a *hygiene* check (mechanical + recurrent), not a correctness check.
- **Check-admission criterion (what deserves CI):** only rules that are ①mechanically checkable, ②have deterministic consequences, ③proven recurrent (failed ≥2×) go into CI. Judgmental norms (grill grading, asking-what's-needed, redaction thoroughness) stay as SKILL.md execution instructions + review spot-checks — never fake-hardened (principle six). Adding a check without meeting all three = over-engineering.
- **No more than 2 consecutive failed case attempts** — fall back to human on the third (serial protection against misdiagnosis cascades).
- **Log clipping is mandatory.** Only paste failed-rank logs + error stack tails into context. Full profiler data overwhelms the ~120K token reasoning sweet spot.
