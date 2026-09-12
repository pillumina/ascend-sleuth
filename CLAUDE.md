# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

ascend-sleuth is an Agent Skills-based diagnostic system for Huawei Ascend NPU training/inference issues. It structures support knowledge into an evolvable, multi-tier system so problem diagnosis improves over time rather than rotting.

This is a **knowledge/skills repo** — there is no build, no lint, no test suite, no application code. Everything is YAML case files, Markdown skill definitions, and Markdown postmortems.

## Architecture

### 三个闭环（读这套系统之前先分清）

系统由三个闭环构成，**混起来读是理解这套机制最大的障碍**。判断一个动作属于哪个闭环，比记住任何机制名都重要：

| 闭环 | 何时发生 | 入口 skill | 产出 |
|------|---------|-----------|------|
| **诊断闭环** | 每次问题（分钟级） | `diagnose`（被打断则 `resume-diagnosis`） | 修复建议 + `traces/<session>.yaml` |
| **沉淀闭环** | 定位结束 / 定期批量 | `to-postmortem`、`to-reference`、`issue-ingest` | `postmortems/inbox/` 草稿 → groom 升格为 case / reference |
| **演进闭环** | 内容流程收尾 / 全库体检轮 | `evolve-check`（伴随）、`self-evolve`（深度轮） | EV 卡 → 执行 → 验证 → 攒批 PR（人审） |

三者共用一条链：前两个产生数据，演进读数据改机制，改完回落。**机制地图、权威归属（每件事由哪篇文档说了算）与周度 runbook 在 `docs/evolution.md`——那是演进机制的唯一入口**，其余 `docs/mechanism/*.md` 是论证层（改机制本身时才读）。

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

Ten skills in `skills/<name>/SKILL.md`, following the [Agent Skills](https://agentskills.io/) spec. **名单与数量不在此硬编码**——由 `docs/_manifest.yaml` 生成到 README 的「skill 名单」节（`scripts/build_docs_index.py --check` 保证一致）。按"谁用得上"分三组：**你要用的**（`diagnose`、`resume-diagnosis`）、**沉淀知识**（`to-postmortem`、`to-reference`、`issue-ingest`）、**维护与演进**（`knowledge-groom`、`self-evolve`、`evolve-check`、`skill-review`、`preload-panel`）。

- **`diagnose`** — Core diagnostic loop: symptom collection → (data gap? take the tool entry's collection surface) → triage-tree routing → two-phase Tier 2 loading (phase 2.5 loads active references from the prior-knowledge layer) → verify diagnosis checks → output fix or fall back to deep investigation. Writes trace to `traces/<session_id>.yaml` on every step (incl. `reference_lookup` events, `purpose: collect|signature|fix|background`). On fix delivery writes `feedback_pending`; any diagnose/resume startup nags for the outcome (degrades to `feedback_stale` after 2 unanswered attempts — polite, not coercive) and updates case confidence. `disable-model-invocation: true` (user-triggered only).
- **`to-postmortem`** — Case-knowledge injection entry. Accepts inline paste, single file, multiple files, or directory. Extracts symptoms/root cause/fix, suggests namespace, runs semantic validation + redaction, outputs YAML draft + postmortem.md into `postmortems/inbox/` (review queue; human-contributed drafts batch weekly, automation-sourced drafts may be groomed directly). Decoupled from diagnose — any investigation source can feed it.
- **`to-reference`** — Prior-knowledge injection entry. Accepts inline paste, file, URL crawl (`--ingest`), or case-set generalization (`--ingest-cases`); `--update <ref-id>` revises existing entries. Extracts facts/methodologies, classifies by `references/_types.yaml` (error-code is table form — one family per file, append-don't-create), runs a **graded** grill phase (high-confidence single confirmation, low-confidence full rounds), outputs schema-complete YAML with `status: active` directly into the formal type dir (`references/<type-dir>/`); **PR review is the review gate — merge = activation** (deep-review gate for case-derived methodology, ≥3 case refs, enforced at production time by CI). Decoupled from diagnose, parallel to to-postmortem.
- **`issue-ingest`** — Upstream issue (GitHub etc.) → case batch ingestion. Orchestrates fetch (`fetch_issues.py`, slim metadata, no body) → hard filter + heuristic sort (`issue_filter.py`: label pool / comments / title / processed-exclusion) → per-candidate evaluation (subagent reads body, judges distillability) → distill via to-postmortem (drafts into `postmortems/inbox/`) → `--mark-imported` for idempotent state. Prerequisite: gh installed + `gh auth status` (guide `gh auth login` web flow otherwise). Framework differences (repo / label system) parameterized. Promotion splits by scenario: default drafts go through owner batch review; owner-preauthorized automation source (this pipeline) may groom directly without waiting for weekly batch.
- **`knowledge-groom`** — Maintenance: batch-process the case inbox queue (pre-triage new_pattern / variant_of / covered_by, human accepts), promote postmortems to Tier 2, validate references, detect value duplication, recalculate confidence scores with time decay, soft-retire stale cases, report namespace capacity, rebuild `knowledge/_index.yaml`; parallel reference-layer maintenance (draft review, degradation signals, observability writeback, index-trigger check). Human-contributed drafts batch weekly; automation-sourced drafts may be processed immediately. `disable-model-invocation: true`.
- **`resume-diagnosis`** — Reads `traces/*.yaml` to resume an interrupted diagnosis session. `disable-model-invocation: true`.
- **`self-evolve`** — Self-evolution deep round + batch aggregator. Explicit deep review of the whole knowledge base (capacity / attribution aggregation / metrics / S2 set) when the user says "run a self-evolve round" or "what could be improved"; also aggregates evolve-check cards into one review PR. `disable-model-invocation: true` (user-triggered only).
- **`evolve-check`** — Lightweight post-content-flow evolution check (default, no separate goal round). After a content task (issue-ingest / to-postmortem / to-reference / knowledge-groom) finishes, checks for improvement signals (≥3 same-root cases → generalize, coverage gaps, repeated manual steps, component failure clusters); produces EV cards only when a signal fires, one line otherwise. Reads the round's on-site record through `scripts/tail_exec_log.py` (never inline python; a missing/empty exec-log is a normal degradation path, exit 0) and **logs its own closing record — including the no-signal case** (`log_skill_exec.py --skill evolve-check`), so "ran and found nothing" is distinguishable from "never ran" (surfaced in the ev-panel 执行现场 section).
- **`skill-review`** — Quality/UX review of a skill (default `diagnose`): five lenses — static audit (rule density, output-segment count, judgment-vs-step ratio, resident token cost), perturbation probes (ordering / information saturation / false premise / hurry-up / wording drift), blind discrimination + persona walkthrough, bad-path experience (empty KB, all-miss, no data, second failure, flow-vs-evidence conflict), attention budget. Report → `proposals/reviews/` (local), improvements → EV card. **Never a CI gate**: experience is a judgmental norm, hardening it is fake hardening. `disable-model-invocation: true` (user-triggered only).
- **`preload-panel`** — Loads DSH visualization panels (diagnose / metrics tabs) via `cordis_define` + `cordis_run`. DSH only.


### Reference layer (prior knowledge)

`references/` holds prior knowledge (facts + methodologies independent of any specific incident), parallel to cases. **Layer position: reference is NOT a fourth retrieval tier** — it never participates in candidate routing/filtering; routing and ranking see cases only. What it does have is **two consumption points, both keyed to a gap in the flow**: the **data gap** (no measurement data yet → the tool entry's collection surface, consumed at step 1, before candidates load) and the **judgment gap** (a candidate is loaded but signature/background/fix evidence is missing → phase 2.5). Both load `status: active` only. The step-1 binding (category → question → branch → ref ids) lives in data, not prose: `skills/diagnose/references/collect-gates.yaml`, whose ids are CI-checked by `verify_references.py` (a hardcoded ref-id in prose once rotted silently):

- **Two organization forms** (organization unit = verification unit): dataset tables (error-code / fault-pattern / env-var-table — one family/domain/module per file, e.g. `errors/ge.yaml` holds the E1xxxx family) vs independent entries (fact: platform-fact / software-fact / tool / command-side-effect; flow: methodology).
- **Lifecycle**: to-reference produces `status: active` → PR review is the gate → merge = activation. Diagnose phase 2.5 loads **active only** — unmerged PR branches are not on main, so unreviewed content never enters diagnostic context (no draft intermediate state; legacy drafts from before this change are groomed out). Revision of active content is `kb/high-risk` (dual sign-off); degradation signals (low resolve-rate, stale `last_verified`, dead sources) come from observability + groom.
- **Clustering rules**: family division follows source; append-don't-create (new error code goes into the existing family table); relate-don't-merge (theme aggregation via `tags`/`related_references`, not file merging).
- **No graph store** — relations are light single-hop, lexically expressible; graph algorithms (if ever needed for v2 trace mining) stay in offline tooling memory.

### Case schema (YAML in `knowledge/<ns>/`)

Each case file has: `id`, `title`, `category` (interrupt|precision|performance), `tags`, `platforms`, `compat` (multi-dimensional: framework/CANN/HDK version ranges), `confidence` (hits/misdiagnoses/score managed by groom — **只承载 S1 现场 resolve 口径**), `symptoms`, `quickly_check` (primary + fallback regex), `diagnosis` steps with `command_template`/`expected`/`fix_on_mismatch`/`rollback`, `severity` (benign|service-affecting|data-loss-risk), `fix_type` (env-var|config-change|code-patch|pending-investigation), `root_cause`, `fix`.

Optional field — `validation_record`: {consistent, inconsistent, self_consistent, last_verified} — 内容被**外部验证**的累积记录（由 `scripts/settle_s2_feedback.py` 结算，非人设定）。与 confidence 分开：S2 issue-replay 对照的是外部 ground truth（issue resolution / 维护者 fix PR / committer 确认），其结果也是 feedback——反馈对象是"case 内容正确性"而非"fix 现场有效性"。`consistent`=外部验证一致（同等 score 下排序优先）、`self_consistent`=自证命中（replay issue 即 case 来源——如实标注不虚增）、`inconsistent`=命中但结论与 resolution 不符（复审信号）。无 S2 验证不填。

Optional field — `source_ref`: {repo, ref, file, line} — 根因定位到源码时的代码位置（如 `vllm_ascend/quantization/modelslim_config.py`）。诊断时 agent 按需取该版本源码片段作为证据链。**「源码不落库」= 源码不随仓库提交、也不写进知识库**——`.gitignore` 已忽略 `src-code/<org>/<repo>/`（作为本地分析缓存，按需 `git clone`/checkout 到对应版本、同版本**复用**以免重复 clone）；知识库只记结论 + `source_ref` 代码指针（上游 repo 维护各自版本）。「不落库」≠ 分析不需要/不保留源码——深入排查**仍要 clone 源码**。ref 用触发版本对应的 commit/tag；`line` 可选。

Optional field — `ref_knowledge`: structured linkage to prior-knowledge entries in `references/`. Each entry is `ref: <reference-id>` + `role: signature-source | fix-methodology | root-cause-context`. `ref` must exist in `references/` and `role` must be legal — enforced by `scripts/verify_references.py` (dangling refs and illegal roles fail CI). The reverse view (which cases reference a given entry) is derived by that script, never stored on the reference side — one relation, stored once. Not required on existing cases; add as needed.

Version matching is **soft**: compat mismatch downgrades confidence but never hard-excludes a case. Undefined dimensions are skipped.

### Severity gate

诊断输出的安全语义——不是通知机制（通知链路已移除，见 roadmap）：诊断系统只输出建议，不接管通知行为。

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

**门禁分级（改哪里测哪里，不机械全量）**：检索/路由/候选选择面 → golden 子集 + 基线缓存；交互/追问/指引面 → ixn 对口样本（**不跑检索 golden**）；输出契约/交互形态 → 盲辨对照（主观成败只有对照能证）；纯文档 → 不跑 replay。分级表与判据强度在 `docs/eval.md`。

**封存对照集（holdout）——"无回归"是否有意义的前提**：`eval/golden/` 在改动者可写面内，且 groom 被要求跟着 case 改夹具，所以"golden 无回归"原本是**可控信号**。`eval/holdout.yaml` 把一部分夹具按内容哈希封存（`scripts/holdout.py --check`，CI `holdout-integrity` job）：改封存夹具内容或删除即红；合法改需维护者 `--reseal` 且 PR 带 `holdout-change` 标签。`--list` 报出"有 case 却无夹具"的格子。**覆盖率仍有缺口**（training / common 段无夹具）——改 skill 对那些场景没有 golden 信号，别把"CI 绿"读成"全都测过"。

**评审把手**：EV 卡的 `predicted_effect.measure` 给出"一条命令 + 期望"，`python3 scripts/ev_measure.py <卡号> --run` 打印实测并判 `符合 / 被证伪 / 无法判定` 三态。它证明**效果**，不证明价值（"命令是否真在测那件事"是约定强度）。

## Multi-agent collaboration (worktree 约束)

多 agent/session 可能并发操作同一仓库——**共享检出目录是冲突根源**（未提交改动随 checkout 流动、共享状态文件互相覆盖）。本仓库约定（机制细节见 `docs/git-workflow.md`「多 agent / 多 session 并行」节）：

- **必须在独立 worktree 中工作**：每个 agent/session 使用 `git worktree add <路径> <自己的 kb/* 分支>` 检出独立工作区，禁止直接在主检出目录修改/提交（`git worktree remove <路径>` 清理）。
- **git 强制的边界**：worktree 隔离工作区/index/未提交改动；同一分支同时只能被一个 worktree 检出（git 拒绝重复检出）。
- **worktree 不隔离的（合流时显式解决）**：refs 全局共享（分支名 `kb/<用途>` 全局唯一）；共享状态文件（`ingest-state.json` 的 processed、`metrics/timeline.yaml`、`knowledge/_index.yaml`、`postmortems/inbox/`）在各 worktree 是各自分支副本——并发修改靠 PR merge 显式合并，不靠覆盖。
- **exec-log 是"同一克隆共享"的运行时件（跨 worktree 共写共读，跨克隆不聚合）**：`metrics/skill-exec-log.yaml` 虽在 `.gitignore` 里，但路径由 `scripts/exec_log_path.py` 解析到**主检出**（`git rev-parse --git-common-dir` 的父目录）——**所有 worktree 写的是同一份**，因此代理在 worktree 里收尾落的记录，主检出（= 用户会话 cwd / 面板读处）立刻可见，且 worktree 清理不会连带丢数据。它是 read-modify-write：**写侧持 flock**（并发实测：无锁 16 次写入只剩 3 条），别用其他方式直接改写它。读法一律走 `scripts/tail_exec_log.py`（自带路径与共享范围标注）；跨克隆/跨机的口径走它的 `--summary` 聚合值进 `metrics/timeline.yaml`，流水本身不进 git。
- **串行操作**：`ingest-state.json` 的 fetch / `--mark-imported` / 游标更新是 read-modify-write 无锁，必须串行；groom 清空 inbox 前先确认无其他 session 未提交草稿。
- **开工/收工纪律**：开工 `git fetch origin` 确认最新 + 确认自己在自己的 worktree 与分支；收工前提交或 stash，不留未提交改动。

## Key constraints

- **Normative foundation:** all design/implementation/evolution changes must be traceable to `docs/design-principles.md` (the normative articles); the derivation chain lives in `docs/design-theory.md` (four axioms → formulas → principles). An untraceable rule is suspect; an unexplainable real-world choice indicts the theory.
- **Diagnose does not access customer environments.** All info (logs, versions, errors) comes from the engineer pasting it. The agent's role is to ask for what's missing when information is insufficient.
- **Agent never applies fixes to production.** Fixes are suggestions for the human to apply.
- **知识库结构性状态**：实时数字（各 namespace 条数/容量，含 soft_cap=30 容量治理信号）以 `python3 scripts/build_index.py` 生成的 `knowledge/_index.yaml` 头部注释为准，**不在 CLAUDE.md 硬编码**（具体条数/哪个格子接近上限随 KB 增长腐烂——如 verl 从空到非空、容量格子持续增长）；指标时序数据**源**在 `metrics/timeline.d/<期号>.yaml`（一期一个文件，各人各写一个不互相覆盖），**生成物** `metrics/timeline.yaml` 由 `scripts/build_timeline.py` 重建（读侧只读它；结构由 `verify_metrics.py --check`、生成物一致性由 `build_timeline.py --check` 校验），机制定义见 `docs/metrics.md`。通用原则：
  - namespace 是否有内容以 `knowledge/_index.yaml` 头注为准；空的 namespace 走 Tier 3 fallback，不假装有内容可检（与 `triage-tree.yaml` 头部注释同源）
  - canonical sample 仍是 `examples/sample-case.yaml`
- **人读面的名单与数字同样不硬编码**：skill 名单、文档目录由 `docs/_manifest.yaml` 生成到 README（`scripts/build_docs_index.py`；`--check` 进 CI `docs-index` job，**生成物不一致或 `docs/` 下有未登记文档即红**）。改文档或 skill 后跑它。手写数字会腐烂且不报错（实测：入口文档曾写"123 条 case / 7 张 EV 卡"，实际已 158 / 50）。
- **代号有生存范围**：`docs/glossary.yaml` 每条带 `scope`。记账号（roadmap 事项 A/E/M/O/P、治理缺口 G、触发信号 T、落地阶段 Phase）**只在各自的计划文档里裸用**；你写的 PR body / EV 卡 prose / 机制文档要引用就写中文含义（`scripts/render_review_summary.py --scan <文件或目录>` 会报越界）。同形冲突（`A1/A2/A3` = 公理 / roadmap 事项 / 平台前缀；`P0` = 优先级）已登记消歧，别新增同类。`docs/adr/` 与 `proposals/` 是只追加档案，豁免且不追溯。
- **Public/private separation:** `skills/`, `references/`, `examples/` are methodology (public). `knowledge/` and `postmortems/` with real content contain customer data and must stay private. `.gitignore` enforces this boundary for `traces/` files.
- **Index freshness:** `knowledge/_index.yaml` is generated by `scripts/build_index.py` and committed. After changing any case YAML, regenerate it; `--check` (run by groom and the kb-checks CI) fails on staleness. Retrieval is deliberately lexical/structural — no vector RAG (see `docs/adr/0002`).
- **Git gating:** KB changes land via PR — triage labels (`kb/new-pattern|variant|covered`), `kb/high-risk` dual sign-off, CODEOWNERS-based review (see `docs/git-workflow.md`; `CODEOWNERS.example` is a placeholder until owners are named). Deployable centralized or as a framework fork — knowledge dirs never merge from upstream.
- **Skill self-containment (CI-enforced):** skill files (`skills/**`) must not reference ADR numbers (`ADR-\d{4}`), dates (`20\d\d-\d\d`), or EV card numbers (`EV-\d{4}-\d{3}`) — ADRs get revised/absorbed; a number anchor makes skill behavior look externally defined; dates read as facts; card numbers rot when the card is superseded. Behavior rules must be inline; traceability belongs to git/PR/card history. This is a *hygiene* check (mechanical + recurrent), not a correctness check.
- **EV 卡的预测必须可复现 (CI-enforced):** `predicted_effect.measure` 要带一条命令 + 期望（`expect_exit` / `expect_stdout` 至少一项），或如实声明 `reason`（不可度量）。缺它则"评审 30 秒判定"无从执行——reviewer 只能开全文或直接批。产卡骨架的占位 `measure` 会被 CI 拦下（忘填 = 响亮失败，不带假绿过审）；判 `validated` 前先跑一遍自己的 measure。存量卡（`MEASURE_CUTOVER` 之前）豁免，缺口由 `scripts/ev_measure.py --audit` 如实报出。
- **对照集不由改动者削弱:** `eval/holdout.yaml` 封存的夹具按内容哈希钉住（CI `holdout-integrity`）——改内容或删除即红，要合法改就得维护者 `--reseal` 并带 `holdout-change` 标签。**注意强度**：哈希是硬门，但"谁有权 reseal"在 CODEOWNERS 落实前是半硬（有写权限者仍可打标签），别把它读成"已有人把关"。
- **Check-admission criterion (what deserves CI):** only rules that are ①mechanically checkable, ②have deterministic consequences, ③proven recurrent (failed ≥2×) go into CI. Judgmental norms (grill grading, asking-what's-needed, redaction thoroughness) stay as SKILL.md execution instructions + review spot-checks — never fake-hardened (principle six). Adding a check without meeting all three = over-engineering.
- **提交前必跑的 CI（`kb-checks`，九条）**：`build_index.py --check`（索引新鲜度 + 顺带解析全部 case YAML）、`verify_references.py --check`、`build_ref_summary_index.py --check`、`build_procedure_index.py --check`、`verify_metrics.py --check`、`build_timeline.py --check`（生成物与源一致）、`verify_proposals.py --check`（卡结构 + 生命周期 + 预测口径）、`holdout.py --check`（对照集未被削弱）、`build_docs_index.py --check`（名单与文档目录一致）；另有 `pr-template`（PR body 模板结构）与 `skill-self-contained`（skills/ 的 ADR/日期/卡号锚三条 grep）。本地逐条复跑（含 CI parity，断言条数以脚本输出为准，不在此写死）：`python3 scripts/rehearse_evolve_loop.py`。**`verify_exec_log.py` 不进 CI**（exec-log 是 .gitignore 运行时件）。
- **No more than 2 consecutive failed case attempts** — fall back to human on the third (serial protection against misdiagnosis cascades).
- **Log clipping is mandatory.** Only paste failed-rank logs + error stack tails into context. Full profiler data overwhelms the ~120K token reasoning sweet spot.
