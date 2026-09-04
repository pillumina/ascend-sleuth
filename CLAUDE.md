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
| Tier 2 | `knowledge/<ns>/*.yaml` — structured case rules | Two-phase: read **命中 namespace 的索引分片** `knowledge/_index/<ns>.yaml` first (瘦身行 F2: id/title/symptoms 首条摘要/category/score + file；完整 symptoms/quickly_check 在 case 本体), filter candidates ≤5 by title/symptom-summary/score, then load full body (with quickly_check) to verify. Rebuild index (master + shards) after any case change via `scripts/build_index.py` |
| Tier 3 | `postmortems/` — raw investigation records | Keyword grep fallback when Tier 2 misses |

### Two orthogonal problem dimensions

- **Where** (training vs inference × framework) — determines which namespace directory to search. Encoded in `triage-tree.yaml`'s `search_namespaces`.
- **What** (interrupt / precision / performance) — determines the diagnosis path and `quickly_check` shape. Interrupt uses error-signature grep, precision uses numeric threshold assertions, performance uses profiler metric comparisons. **Do not mix these.**

### Skills

Nine skills in `skills/<name>/SKILL.md`, following the [Agent Skills](https://agentskills.io/) spec:

- **`diagnose`** — Core diagnostic loop: symptom collection → triage-tree routing → two-phase Tier 2 loading (phase 2.5 loads active references from the prior-knowledge layer) → verify diagnosis checks → output fix or fall back to deep investigation. Writes trace to `traces/<session_id>.yaml` on every step (incl. `reference_lookup` events). On fix delivery writes `feedback_pending`; any diagnose/resume startup nags for the outcome (degrades to `feedback_stale` after 2 unanswered attempts — polite, not coercive) and updates case confidence. `disable-model-invocation: true` (user-triggered only).
- **`to-postmortem`** — Case-knowledge injection entry. Accepts inline paste, single file, multiple files, or directory. Extracts symptoms/root cause/fix, suggests namespace, runs semantic validation + redaction, outputs YAML draft + postmortem.md into `postmortems/inbox/` (review queue; human-contributed drafts batch weekly, automation-sourced drafts may be groomed directly). Decoupled from diagnose — any investigation source can feed it.
- **`to-reference`** — Prior-knowledge injection entry. Accepts inline paste, file, URL crawl (`--ingest`), or case-set generalization (`--ingest-cases`); `--update <ref-id>` revises existing entries. Extracts facts/methodologies, classifies by `references/_types.yaml` (error-code is table form — one family per file, append-don't-create), runs a **graded** grill phase (high-confidence single confirmation, low-confidence full rounds), outputs schema-complete YAML with `status: active` directly into the formal type dir (`references/<type-dir>/`); **PR review is the review gate — merge = activation** (deep-review gate for case-derived methodology, ≥3 case refs, enforced at production time by CI). Decoupled from diagnose, parallel to to-postmortem.
- **`issue-ingest`** — Upstream issue (GitHub etc.) → case batch ingestion. Orchestrates fetch (`fetch_issues.py`, slim metadata, no body) → hard filter + heuristic sort (`issue_filter.py`: label pool / comments / title / processed-exclusion) → per-candidate evaluation (subagent reads body, judges distillability) → distill via to-postmortem (drafts into `postmortems/inbox/`) → `--mark-imported` for idempotent state. Prerequisite: gh installed + `gh auth status` (guide `gh auth login` web flow otherwise). Framework differences (repo / label system) parameterized. Promotion splits by scenario: default drafts go through owner batch review; owner-preauthorized automation source (this pipeline) may groom directly without waiting for weekly batch.
- **`knowledge-groom`** — Maintenance: batch-process the case inbox queue (pre-triage new_pattern / variant_of / covered_by, human accepts), promote postmortems to Tier 2, validate references, detect value duplication, recalculate confidence scores with time decay, soft-retire stale cases, report namespace capacity, rebuild `knowledge/_index.yaml`; parallel reference-layer maintenance (draft review, degradation signals, observability writeback, index-trigger check). Human-contributed drafts batch weekly; automation-sourced drafts may be processed immediately. `disable-model-invocation: true`.
- **`resume-diagnosis`** — Reads `traces/*.yaml` to resume an interrupted diagnosis session. `disable-model-invocation: true`.
- **`self-evolve`** — Self-evolution deep round + batch aggregator. Explicit deep review of the whole knowledge base (capacity / attribution aggregation / metrics / S2 set) when the user says "run a self-evolve round" or "what could be improved"; also aggregates evolve-check cards into one review PR. `disable-model-invocation: true` (user-triggered only).
- **`evolve-check`** — Lightweight post-content-flow evolution check (default, no separate goal round). After a content task (issue-ingest / to-postmortem / to-reference / knowledge-groom) finishes, checks for improvement signals (≥3 same-root cases → generalize, coverage gaps, repeated manual steps, component failure clusters); produces EV cards only when a signal fires, one line otherwise.
- **`preload-panel`** — Loads DSH visualization panels (diagnose / metrics tabs) via `cordis_define` + `cordis_run`. DSH only.


### Reference layer (prior knowledge)

`references/` holds prior knowledge (facts + methodologies independent of any specific incident), parallel to cases. **Layer position: reference is the 2.5-th layer — auxiliary lookup after a case candidate hits, NOT a fourth retrieval tier** (never participates in candidate routing/filtering; diagnose phase 2.5 loads it on demand):

- **Two organization forms** (organization unit = verification unit): dataset tables (error-code / fault-pattern / env-var-table — one family/domain/module per file, e.g. `errors/ge.yaml` holds the E1xxxx family) vs independent entries (fact: platform-fact / software-fact / tool / command-side-effect; flow: methodology).
- **Lifecycle**: to-reference produces `status: active` → PR review is the gate → merge = activation. Diagnose phase 2.5 loads **active only** — unmerged PR branches are not on main, so unreviewed content never enters diagnostic context (no draft intermediate state; legacy drafts from before this change are groomed out). Revision of active content is `kb/high-risk` (dual sign-off); degradation signals (low resolve-rate, stale `last_verified`, dead sources) come from observability + groom.
- **Clustering rules**: family division follows source; append-don't-create (new error code goes into the existing family table); relate-don't-merge (theme aggregation via `tags`/`related_references`, not file merging).
- **No graph store** — relations are light single-hop, lexically expressible; graph algorithms (if ever needed for v2 trace mining) stay in offline tooling memory.

### Case schema (YAML in `knowledge/<ns>/`)

Each case file has: `id`, `title`, `category` (interrupt|precision|performance), `tags`, `platforms`, `compat` (multi-dimensional: framework/CANN/HDK version ranges), `confidence` (hits/misdiagnoses/score managed by groom — **只承载 S1 现场 resolve 口径**), `symptoms`, `quickly_check` (primary + fallback regex), `diagnosis` steps with `command_template`/`expected`/`fix_on_mismatch`/`rollback`, `severity` (benign|service-affecting|data-loss-risk), `fix_type` (env-var|config-change|code-patch|pending-investigation), `root_cause`, `fix`.

Optional field — `validation_record`: {consistent, inconsistent, self_consistent, last_verified} — 内容被**外部验证**的累积记录（由 `scripts/settle_s2_feedback.py` 结算，非人设定）。与 confidence 分开：S2 issue-replay 对照的是外部 ground truth（issue resolution / 维护者 fix PR / committer 确认），其结果也是 feedback——反馈对象是"case 内容正确性"而非"fix 现场有效性"。`consistent`=外部验证一致（同等 score 下排序优先）、`self_consistent`=自证命中（replay issue 即 case 来源——如实标注不虚增）、`inconsistent`=命中但结论与 resolution 不符（复审信号）。无 S2 验证不填。

Optional field — `source_ref`: {repo, ref, file, line} — 根因定位到源码时的代码位置（如 `vllm_ascend/quantization/modelslim_config.py`）。诊断时 agent 按需取该版本源码片段作为证据链，**源码不落库**（上游 repo 维护各自版本，知识库只记结论 + 代码指针）。ref 用触发版本对应的 commit/tag；`line` 可选。

Optional field — `ref_knowledge`: structured linkage to prior-knowledge entries in `references/`. Each entry is `ref: <reference-id>` + `role: signature-source | fix-methodology | root-cause-context`. `ref` must exist in `references/` and `role` must be legal — enforced by `scripts/verify_references.py` (dangling refs and illegal roles fail CI). The reverse view (which cases reference a given entry) is derived by that script, never stored on the reference side — one relation, stored once. Not required on existing cases; add as needed.

Version matching is **soft**: compat mismatch downgrades confidence but never hard-excludes a case. Undefined dimensions are skipped.

### Severity gate

诊断输出的安全语义——不是通知机制（P1 已移除，见 roadmap）：诊断系统只输出建议，不接管通知行为。

- `benign` → give fix directly
- `service-affecting` → give fix but flag `fix_side_effects` (e.g., requires-restart)
- `data-loss-risk` → **do not give fix**; output "halt training, preserve state, notify owner"

**为什么需要 data-loss-risk 档**：诊断输出是给工程师的执行建议。若根因是"checkpoint 可能被污染"（数据损坏风险），给 fix 让工程师继续跑 = 可能加速损坏——高危场景的正确动作是**停**不是**补丁**（诚实退化的延伸：不确定就承认、高危就停）。"通知 owner"是给工程师的一句话建议，不是系统对接 on-call/IM 的链路。

### Platform dispatch

Platform differences are **field-level** within cases, not separate cases. A single case can have multiple `diagnosis` blocks keyed by `platforms` (e.g. `A2-910B`, `A3-910C`, `A5-950`); a case with no `platforms` field is treated as cross-platform. Platform background docs were abolished (agent-generated, zero external sources) — platform facts live in the reference layer (`references/platform-facts/`, populated via to-reference with real sources). Diagnose phase 2.5 injects platform background summary (summary layer) for matched platforms; unmatched platforms get no platform prior (each case still carries its own platform evidence in its `platforms`-keyed diagnosis branches).

### Trace and misdiagnosis attribution

Every diagnose step writes to `traces/<session_id>.yaml` trace array (trajectory: `{role, ...}` events). On misdiagnosis, read the trace to determine: **case error** (fix the knowledge YAML) vs **execution error** (fix the skill body). Without trace, misdiagnosis attribution is impossible and you risk corrupting correct cases.

**Trace schema 关键字段**（诊断面板 + 跨 agent/session resume 的数据源）：
- `summary`：agent 诊断收尾整合的问题背景段（什么问题/环境/关键报错/定位结果）——面板展开直接显示，人不必逐个打开证据
- user 事件 `content`（摘要）+ `evidence`（完整证据：`inline` 原文 / `files` 相对路径 / `sources` URL / `missing` 缺口）——**跨 agent/session 自包含的关键**（平台 memory 不可跨，新 agent 靠 trace 证据重建）；大文件落 `traces/evidence/<session_id>/`
- agent 事件 `output`（给用户）+ `reason`（决策依据，关键决策必写）——回放/归因/沉淀的证据
- `created_at`/`updated_at`：诊断面板按 `updated_at` 排序（resume 续接刷新 → 置顶）
- `resume` action：续接事件（resume skill 必写 + 刷新 updated_at）

**诊断面板**（DSH 插件）展示：会话列表（状态/时间/计数徽章）→ 展开轨迹（summary/evidence/reason/reference 参与标注）→ 证据文件可点击打开。

### Eval

Golden-case regression suite in `eval/golden/`. Public repo contains only constructed examples (no real customer data). Real fixtures go in a private repo. Run before/after skill changes: feed fixed input via replay mode, verify namespace routing + case matching + fix content against `expected`. LLM non-determinism means asserting "top-3 hit" rather than "must be first."

## Multi-agent collaboration (worktree 约束)

多 agent/session 可能并发操作同一仓库——**共享检出目录是冲突根源**（未提交改动随 checkout 流动、共享状态文件互相覆盖）。本仓库约定（机制细节见 `docs/git-workflow.md`「多 agent / 多 session 并行」节）：

- **必须在独立 worktree 中工作**：每个 agent/session 使用 `git worktree add <路径> <自己的 kb/* 分支>` 检出独立工作区，禁止直接在主检出目录修改/提交（`git worktree remove <路径>` 清理）。
- **git 强制的边界**：worktree 隔离工作区/index/未提交改动；同一分支同时只能被一个 worktree 检出（git 拒绝重复检出）。
- **worktree 不隔离的（合流时显式解决）**：refs 全局共享（分支名 `kb/<用途>` 全局唯一）；共享状态文件（`ingest-state.json` 的 processed、`metrics/timeline.yaml`、`knowledge/_index.yaml`、`postmortems/inbox/`）在各 worktree 是各自分支副本——并发修改靠 PR merge 显式合并，不靠覆盖。
- **串行操作**：`ingest-state.json` 的 fetch / `--mark-imported` / 游标更新是 read-modify-write 无锁，必须串行；groom 清空 inbox 前先确认无其他 session 未提交草稿。
- **开工/收工纪律**：开工 `git fetch origin` 确认最新 + 确认自己在自己的 worktree 与分支；收工前提交或 stash，不留未提交改动。

## Key constraints

- **Normative foundation:** all design/implementation/evolution changes must be traceable to `docs/design-principles.md` (the normative articles); the derivation chain lives in `docs/design-theory.md` (four axioms → formulas → principles). An untraceable rule is suspect; an unexplainable real-world choice indicts the theory.
- **Diagnose does not access customer environments.** All info (logs, versions, errors) comes from the engineer pasting it. The agent's role is to ask for what's missing when information is insufficient.
- **Agent never applies fixes to production.** Fixes are suggestions for the human to apply.
- **知识库结构性状态**：实时数字（各 namespace 条数/容量，含 soft_cap=30 容量治理信号）以 `python3 scripts/build_index.py` 生成的 `knowledge/_index.yaml` 头部注释为准，**不在 CLAUDE.md 硬编码**（具体条数/哪个格子接近上限随 KB 增长腐烂——如 verl 从空到非空、容量格子持续增长）；按周 append 的指标时序数据在 `metrics/timeline.yaml`（结构由 `verify_metrics.py --check` 校验），机制定义见 `docs/metrics.md`。通用原则：
  - namespace 是否有内容以 `knowledge/_index.yaml` 头注为准；空的 namespace 走 Tier 3 fallback，不假装有内容可检（与 `triage-tree.yaml` 头部注释同源）
  - canonical sample 仍是 `examples/sample-case.yaml`
- **Public/private separation:** `skills/`, `references/`, `examples/` are methodology (public). `knowledge/` and `postmortems/` with real content contain customer data and must stay private. `.gitignore` enforces this boundary for `traces/` files.
- **Index freshness:** `knowledge/_index.yaml` is generated by `scripts/build_index.py` and committed. After changing any case YAML, regenerate it; `--check` (run by groom and the kb-checks CI) fails on staleness. Retrieval is deliberately lexical/structural — no vector RAG (see `docs/adr/0002`).
- **Git gating:** KB changes land via PR — triage labels (`kb/new-pattern|variant|covered`), `kb/high-risk` dual sign-off, CODEOWNERS-based review (see `docs/git-workflow.md`; `CODEOWNERS.example` is a placeholder until owners are named). Deployable centralized or as a framework fork — knowledge dirs never merge from upstream.
- **Skill self-containment (CI-enforced):** skill files (`skills/**`) must not reference ADR numbers (`ADR-\d{4}`) — ADRs get revised/absorbed, a number anchor makes skill behavior look externally defined. Behavior rules must be inline; traceability belongs to git/PR/ADR history. This is a *hygiene* check (mechanical + recurrent), not a correctness check.
- **Check-admission criterion (what deserves CI):** only rules that are ①mechanically checkable, ②have deterministic consequences, ③proven recurrent (failed ≥2×) go into CI. Judgmental norms (grill grading, asking-what's-needed, redaction thoroughness) stay as SKILL.md execution instructions + review spot-checks — never fake-hardened (principle six). Adding a check without meeting all three = over-engineering.
- **No more than 2 consecutive failed case attempts** — fall back to human on the third (serial protection against misdiagnosis cascades).
- **Log clipping is mandatory.** Only paste failed-rank logs + error stack tails into context. Full profiler data overwhelms the ~120K token reasoning sweet spot.
