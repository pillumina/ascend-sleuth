# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **常驻上下文的取舍**：本文件每次会话整份注入，成本与"这次用不用得上"无关。所以这里只放**每次都要遵守的约束**与**指路**；细节放各自的权威处，让需要它的那一刻去读。新增内容前先问：这条是每次都需要的吗？不是就放到写点（见 `docs/spec/writing-norms.md` §3）。

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

三者共用一条链：前两个产生数据，演进读数据改机制，改完回落。**机制地图、权威归属（每件事由哪篇文档说了算）与周度 runbook 在 `docs/mechanism/rsi-mechanism.md`——那是自演进元机制的唯一技术入口**。

### 两套传递机制（决定内容该放哪）

| 机制 | 何时进 agent 上下文 | 放什么 |
|---|---|---|
| 常驻指令（本文件、`AGENTS.md`） | 会话开始**整份注入** | 每次都要遵守的约束 + 指路 |
| skill（`skills/<name>/SKILL.md`） | 会话开始只注入 name + `description`，正文**按需读** | 某个流程的执行规则 |
| 子目录级指令文件 | 读到该目录的文件时才加载 | 该目录的局部约定 |

判据：一条内容只在某个动作发生时才需要 → 放那个动作的写点，不放在这里。

### Three-tier knowledge loading (controls context cost)

| Tier | Content | When loaded |
|------|---------|-------------|
| Tier 1 | `triage-tree.yaml` — routing in two layers: `sides:`（合法侧 + 每侧目录面）then `natures:`（interrupt / precision / performance，性质词表**训推共用**，≤30 natures）。**聚合是生成物**：改词改 `triage-tree.d/<性质>.yaml`（一性质一文件，清单在 `00-protocol.md` 的 `sources:`）后跑 `scripts/build_triage_tree.py` 并把聚合一起提交；该目录与聚合都走 `merge=union`，两人同一天加词不冲突 | Always |
| Tier 2 | `knowledge/<ns>/*.yaml` — structured case rules | Two-phase: read the **命中 (namespace × category) 的索引分片** `knowledge/_index/<ns>__<category>.yaml` first (行已瘦身: id/title/tags/symptoms 首条摘要/category/score/file + 签名面 `sig`(quickly_check 字面量分支, ≤6) 与 `tok`(全症状 token, ≤12)；完整 symptoms/quickly_check 在 case 本体), filter candidates ≤5 by title/tag/symptom-summary（`sig`/`tok` 是判断证据；**排序仍由 agent 的相关性判断**，score 只破平——历史回放 agent 判断 top-3 19/19，优于任何机械排序键）, then load the full body to verify with quickly_check. category 未定才回退 `<ns>.yaml`；全库总表 `_index.yaml` 只在跨库比对时读。改 case 后跑 `scripts/build_index.py`（分片 + 总表一起提交；门是覆盖检查） |
| Tier 3 | `postmortems/` — raw investigation records | Keyword grep fallback when Tier 2 misses |

### Two orthogonal problem dimensions

- **Where** (training vs inference × framework) — determines which namespace directory to search. **侧不由症状词判，由工程师的事实确定**（材料里写着→直接用；没写→第 1 步问一句；给了框架名→对到库里目录；一时不答→两侧都查并记 `side: unknown`）。落在 `triage-tree.yaml` 的 `sides:`，与 trace 的 `side` / `side_source` 一起可观测。
- **What** (interrupt / precision / performance) — determines the diagnosis path and `quickly_check` shape. Interrupt uses error-signature grep, precision uses numeric threshold assertions, performance uses profiler metric comparisons. **Do not mix these.** 这三个性质就是 `triage-tree.yaml` 的 `natures:` 分支：症状匹配只判性质，词表训推共用一份，所以同一个宽词不再需要在两侧各写一遍、也不用靠分支顺序决定谁先接住。

### Skills

skill 的名单、分组与"谁用得上"**不在此处维护**：由 `docs/_manifest.yaml` 生成到 README 的「skill 名单」节（`scripts/build_docs_index.py --check` 保证一致）。每个 skill 的触发条件以其 `SKILL.md` frontmatter 的 `description` 为准——那份摘要由 agent harness 在会话开始自动注入，此处重复一遍只是双份常驻成本加漂移风险。

### Reference layer (prior knowledge)

`references/` 放先验知识（与具体事故无关的事实 + 方法论），与 case 并列。**它不是第四层检索**——不参与候选路由与排序。它有两个消费点，都锚在流程里的缺口上：**数据缺口**（还没有测量数据 → 工具词条的采集面，在候选加载前消费）与**判断缺口**（候选已载入但缺签名/背景/修复依据 → 诊断步骤 2.5）。两处都只读 `status: active`。

- **两种组织形态**（组织单位 = 校验单位）：数据集表（error-code / fault-pattern / env-var-table，一族/一域/一模块一个文件）与独立词条（fact: platform-fact / software-fact / tool / command-side-effect；flow: methodology）。
- **生命周期**：to-reference 产出 `status: active` → PR review 即闸门 → 合入即生效；诊断只读 main 上的 active 内容，未合入的分支不进诊断上下文。修订 active 内容属 `kb/high-risk`（双签）；退化信号（低解决率、`last_verified` 过期、来源失效）由观测与 groom 报出。
- **聚类规则**：家族按来源划分；append-don't-create（新错误码进既有 family 表）；relate-don't-merge（主题聚合走 `tags` / `related_references`，不合并文件）。
- **无图存储**：关系是轻量单跳、可用词法表达；图算法（若将来做 trace 挖掘）留在离线工具里。
- 词条的字段定义与产出规则见 `references/README.md` 与 `references/_types.yaml`，产出流程见 `skills/to-reference/SKILL.md`。

### Case schema (YAML in `knowledge/<ns>/`)

字段定义、口径与"哪些内容不允许进库"见 [`docs/spec/case-schema.md`](docs/spec/case-schema.md)（canonical 示例：`examples/sample-case.yaml`）。
每次会话只需记住三条跨切面约束：

- `knowledge/` 与 `postmortems/` 含客户数据，属私有面，入库前脱敏；
- **源码不落库**：`src-code/` 是本地分析缓存（按版本平铺、锚主检出），知识库只记结论 + `source_ref` 指针；
- `compat` 版本匹配是**软**的：不匹配只降置信度，永不硬排除。

### Severity gate

诊断输出的安全语义——不是通知机制：诊断系统只输出建议，不接管通知行为。

- `benign` → 直接给 fix
- `service-affecting` → 给 fix，但标注 `fix_side_effects`（如需要重启）
- `data-loss-risk` → **不给 fix**；输出"先停训练、保留现场、通知 owner"

高危 root cause 的正确动作是**停**不是补丁：给 fix 让工程师继续跑可能加速损坏（诚实退化的延伸——不确定就承认，高危就停）。"通知 owner"是给工程师的一句话建议，不是系统对接 on-call/IM 的链路。

### Platform dispatch

平台差异是 case 内的**字段级**差异：一个 case 可有多段按 `platforms` 键控的 `diagnosis` 分支（如 `A2-910B` / `A3-910C` / `A5-950`）；无 `platforms` 字段视为跨平台。诊断 phase 2.5 注入匹配平台的背景摘要，未匹配的平台不给先验（每个 case 仍自带 `platforms` 键控的证据分支）。平台事实在先验层 `references/platform-facts/`（经 to-reference 带真实来源沉淀）。平台背景文档已废除（agent 生成、零外部来源）。

### Trace and misdiagnosis attribution

每个 diagnose 步骤往 `traces/<session_id>.yaml` 追加一条 `{role, ...}`。误诊归因靠它区分**case 错**（改知识 YAML）与**执行错**（改 skill 正文）；没有 trace 就无法归因，硬改可能弄坏本来正确的 case。

关键字段：`summary`（收尾整合的问题背景段，面板展开直接显示）、user 事件 `content` + `evidence`（`inline` / `files` / `sources` / `missing`——跨 agent 与会话自包含的关键，大文件落 `traces/evidence/<session_id>/`）、agent 事件 `output`（给用户）+ `reason`（决策依据）、`created_at` / `updated_at`（面板按后者排序）、`resume` 事件。**完整 schema、证据落盘铁律与行文口径**见 `skills/diagnose/references/diagnosis-trace.md`（与 `report-template.md`）。

### Eval

Golden-case 回归套件在 `eval/golden/`：公开仓只放构造示例，真实夹具进私有仓；LLM 非确定性 → 断言"top-3 命中"而非"必须第一"。

- **门禁分级（改哪里测哪里，不机械全量）**与判据强度：`docs/guide/eval.md`。
- **封存对照集** `eval/holdout.yaml` 按内容哈希钉住（`scripts/holdout.py --check`，CI `holdout-integrity`）：改内容或删除即红，合法改需维护者 `--reseal` 且 PR 带 `holdout-change` 标签。**强度注意**：哈希是硬门，但"谁有权 reseal"在 CODEOWNERS 落实前是半硬（有写权限者仍可打标签），别读成"已有人把关"。
- **评审把手**：EV 卡的 `predicted_effect.measure` 给"一条命令 + 期望"，`python3 scripts/ev_measure.py <卡号> --run` 打印实测并判三态。它证明**效果**，不证明价值。

## Multi-agent collaboration (worktree 约束)

多 agent/session 可能并发操作同一仓库，共享检出目录是冲突根源。四条每次都要遵守的规则：

1. **改 tracked 文件的活进 worktree**：`git worktree add <路径> <自己的 kb/* 分支>`，禁止在主检出目录修改或提交；同一分支同时只能被一个 worktree 检出。
2. **未进 git 的运行时件一律锚到主检出**，且**用绝对路径读写**：`python3 scripts/shared_dir.py <名字>` 是唯一入口（exec-log、`src-code/`、`traces/`、`postmortems/inbox/` 草稿、`proposals/{sessions,tasks,reviews,experiments}/`）。
3. **别写相对路径**：worktree 清理对 gitignore 件无提示、不报错（不是"会被 git 拦住"），而面板/周批/结算脚本读的是主检出那一份——"记录了但没人看得见"与"读不到就当成没有"会同时发生。
4. **串行与收工**：`ingest-state.json` 的游标更新无锁，必须串行；开工先 `git fetch origin`，收工前提交或 stash，不留未提交改动。

完整约定（不隔离的面如何在合流时解决、锁原语、worktree 清理）见 [`docs/guide/git-workflow.md`](docs/guide/git-workflow.md)。

## Key constraints

- **Normative foundation:** all design/implementation/evolution changes must be traceable to `docs/spec/design-principles.md` (the normative articles); the derivation chain lives in `docs/spec/design-theory.md` (four axioms → formulas → principles). An untraceable rule is suspect; an unexplainable real-world choice indicts the theory.
- **Diagnose does not access customer environments.** All info (logs, versions, errors) comes from the engineer pasting it. The agent's role is to ask for what's missing when information is insufficient.
- **Agent never applies fixes to production.** Fixes are suggestions for the human to apply.
- **知识库结构性状态**：实时数字（各 namespace 条数/容量，含 soft_cap 容量治理信号）**现算**：`python3 scripts/index_counts.py`（生成物里不写数字——数字进 git 就会在并发合并时撞行或漂移；面板与体检脚本走同一条现算路径），**不在此硬编码**（条数随 KB 增长腐烂）；指标时序数据的**源**在 `metrics/timeline.d/<期号>.yaml`、**生成物** `metrics/timeline.yaml` 由 `scripts/build_timeline.py` 重建（读侧只读它），口径见 `docs/guide/metrics.md`。
- **人读面的名单与数字同样不硬编码**：skill 名单、文档目录由 `docs/_manifest.yaml` 生成到 README（`scripts/build_docs_index.py`；`--check` 进 CI `docs-index`，**生成物不一致或 `docs/` 下有未登记文档即红**）。手写数字会腐烂且不报错。
- **人读文本的行文规范**：写任何给人看或给人审的文本——定位报告、trace 的 `summary`/`output`/`reason`、面板文案、EV 卡、case/reference 词条、postmortem、诊断对话输出、PR body、`docs/` 与 skill 正文——按 `docs/spec/writing-norms.md`：共用条目、必须保留的原值、每一面"共用还是定制"的判定都在那一篇，各面的写点见其 §3。行文是判断性规范，**不进 CI**；由 PR 人读性自查 + review spot-check 保证。机械可判的切片已有门：`build_docs_index.py --check` 与 `render_review_summary.py --scan`（代号未登记与越界）。
- **代号有生存范围**：`docs/glossary.yaml` 每条带 `scope`。记账号（roadmap 事项、治理缺口、触发信号、落地阶段）**只在各自的计划文档里裸用**；PR body / EV 卡 prose / 机制文档要引用就写中文含义（`scripts/render_review_summary.py --scan <文件或目录>` 会报越界）。`docs/adr/` 与 `proposals/` 是只追加档案，豁免且不追溯。
- **对话回复写人话**：回复用户时先写中文含义，内部代号放括号里。要展开的有两类：①短代号，即卡号、事项号、机制名、分组名这类简称；②本仓内部术语，即只有读过 `docs/` 才这么说的词（说"数怎么算"不说「口径」，说"看什么"不说「判据」，说"同一批题上逐题比"不说「配对检验」）。必须照抄的原值不在此列：原始字段值与枚举、仓库内路径与命令、报错原文、`文件:行号`、编号与数字、算子名、已成术语的比喻（如「体检」），改掉就无法核对。标准是读者只看这段回复就能懂，不必先去读 `docs/`。
- **Public/private separation:** `skills/`, `references/`, `examples/` are methodology (public). `knowledge/` and `postmortems/` with real content contain customer data and must stay private. `.gitignore` enforces this boundary for `traces/` files.
- **并发提交为什么不再冲突（生成物随 PR 走）**：生成物里**不写数字**（条数/容量/日期一律现算，见上一条）——这是前提；路由层（`triage-tree.d/` + 聚合 `triage-tree.yaml`）是一层平铺的追加型结构，配 `merge=union`，两人同一天加词两边都留住；门因此是**覆盖检查**（每条 case 的索引行都在、每个路由词都在），不是逐字节相同——逐字节会把 union 出来的、内容正确的文件判红。索引是嵌套结构，行级 union 会把 YAML 拼坏，所以**故意没配 union**：同一个格子（框架 × 性质）的两人并发仍会撞索引文件，解决动作是重跑 `python3 scripts/build_index.py`（机械、无判断）；不同格子不碰同一个文件。提交面：改 case 提交 case + 分片 + 总表；改路由词提交族文件 + 聚合。**合并不需要任何人再跑收尾命令**。Retrieval is deliberately lexical/structural — no vector RAG (see `docs/adr/0002`).
- **Git gating:** KB changes land via PR — triage labels (`kb/new-pattern|variant|covered`), `kb/high-risk` dual sign-off, CODEOWNERS-based review (see `docs/guide/git-workflow.md`; `CODEOWNERS.example` is a placeholder until owners are named). Deployable centralized or as a framework fork — knowledge dirs never merge from upstream.
- **Skill self-containment (CI-enforced):** skill files (`skills/**`) must not reference ADR numbers (`ADR-\d{4}`), dates (`20\d\d-\d\d`), or EV card numbers (`EV-\d{4}-\d{3}`) — ADRs get revised/absorbed; a number anchor makes skill behavior look externally defined; dates read as facts; card numbers rot. Behavior rules must be inline; traceability belongs to git/PR/card history.
- **EV 卡的预测必须可复现 (CI-enforced):** `predicted_effect.measure` 要带一条命令 + 期望（`expect_exit` / `expect_stdout` 至少一项），或如实声明 `reason`（不可度量）。缺它则"评审 30 秒判定"无从执行；产卡骨架的占位 `measure` 会被 CI 拦下。判 `validated` 前先跑一遍自己的 measure。
- **Check-admission criterion (what deserves CI):** only rules that are ①mechanically checkable, ②have deterministic consequences, ③proven recurrent (failed ≥2×) go into CI. Judgmental norms stay as execution instructions + review spot-checks — never fake-hardened (原则六).
- **提交前必跑**：逐条命令以 `.github/workflows/kb-checks.yml` 与 `pr-template.yml` 为准（**不在本文件抄一份**——抄了会腐烂且不报错）。另有更重的端到端演练 `python3 scripts/rehearse_evolve_loop.py`：它在临时副本里真跑一遍闭环、并逐条复跑 CI 命令；**但它自己不进 CI，也不能替代上面逐条 `--check`**。`verify_exec_log.py` 不进 CI（exec-log 是运行时件）。
- **No more than 2 consecutive failed case attempts** — fall back to human on the third (serial protection against misdiagnosis cascades).
- **Log clipping is mandatory.** Only paste failed-rank logs + error stack tails into context. Full profiler data overwhelms the ~120K token reasoning sweet spot.
