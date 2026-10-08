# case schema（`knowledge/<ns>/` 的 case 字段定义）

本文是 case 文件字段定义、取值口径与入库禁令的权威处。canonical 示例是 [examples/sample-case.yaml](../../examples/sample-case.yaml)。

读者是写或改 case 的人：`to-postmortem` 产出草稿、groom 升格与合并、诊断时读候选本体的人。新增一条 case、改一条 case 的字段、或要解释某个字段为什么这样算时读本文。读完你能知道每个字段给谁用、哪个口径只承载一种证据、哪些内容不允许进库。只跑诊断、不改 case 的人不必读：候选的加载顺序与验证方式见 [diagnosis-procedure.md](../../skills/diagnose/references/diagnosis-procedure.md)。

## 1 管什么

- `knowledge/<ns>/` 下每个 case YAML 的字段：必需字段、可选字段、取值枚举。
- 每个字段承载哪种证据：现场反馈（S1，来源 session 自己回报的解决记录）与外部对照（S2，issue 回放对照 issue resolution 得到的结论）各自记在哪个字段，为什么必须分开。
- 版本匹配强度：`compat` 只降置信度，不硬排除。
- 入库禁令：哪些内容不允许进 case。

## 2 不管什么

- 草稿怎么起草、怎么确认：见 [to-postmortem/SKILL.md](../../skills/to-postmortem/SKILL.md)。
- 索引与读侧视图怎么生成：见 `CLAUDE.md` 与 [build_index.py](../../scripts/build_index.py)。
- reference 词条的字段与生命周期：见 [references/README.md](../../references/README.md) 与 [references/_types.yaml](../../references/_types.yaml)。
- 反馈结算的算法：见 [settle_trace_feedback.py](../../scripts/settle_trace_feedback.py) 与 [settle_s2_feedback.py](../../scripts/settle_s2_feedback.py)。
- 诊断阶段怎么加载与验证 case：见 [diagnosis-procedure.md](../../skills/diagnose/references/diagnosis-procedure.md)。

## 3 条目

### 3.1 必需字段

每个 case 文件都有下表字段。`怎么判定` 一列写的是当前能执行的检查。

| 字段 | 要求 | 怎么判定 | 强度 |
|---|---|---|---|
| `id`、`title` | 稳定标识与人类可读标题 | `scripts/verify_case_draft.py --all` 校验必填 | 必须 |
| `category` | 取 `interrupt` / `precision` / `performance` | 同一个脚本校验枚举 | 必须 |
| `tags`、`platforms` | 检索标签与适用平台 | 必填 | 必须 |
| `compat` | 多维版本区间（framework / CANN / HDK），软匹配 | 必填 | 必须 |
| `confidence` | `hits` / `misdiagnoses` / `score`，由 groom 管理；只承载 S1 现场 resolve 口径 | 必填 | 必须 |
| `symptoms` | 症状描述 | 必填 | 必须 |
| `quickly_check` | primary + fallback 两条正则 | 校验正则可编译、无空分支 | 必须 |
| `diagnosis` | 步骤数组，每步含 `command_template` / `expected` / `fix_on_mismatch` / `rollback` | 必填 | 必须 |
| `severity` | 取 `benign` / `service-affecting` / `data-loss-risk` | 校验枚举 | 必须 |
| `fix_type` | 取 `env-var` / `config-change` / `code-patch` / `pending-investigation` | 校验枚举 | 必须 |
| `root_cause`、`fix` | 根因与修复结论 | 必填 | 必须 |

反例：`fix_type: upgrade` 是 schema 里没有的取值，曾在 4 个 PR 的 5 个 case 里静默存活（`.github/workflows/kb-checks.yml` 的 `case-structure` job 注释记录）。枚举与必填字段由 `python3 scripts/verify_case_draft.py --all` 拦下。

### 3.2 可选字段：`source_session`

可选字段可以缺省，缺省时各自退回的行为见以下各条。

强度：可选。

要求：填该 case 由哪个诊断 session 沉淀而来（如 `2026-09-16-12430-dsv4pro-mc2`）。

用途只有一个：反馈结算时判定「自证」——来源 session 自己回报的 resolve 记入 `confidence.self_resolved`，不计入 `hits`。缺该字段时结算退回原行为（计入 `hits`）。这是刻意的保守取舍：宁可少识别自证，不误判独立命中。

### 3.3 `confidence.self_resolved`：{count, last, examples}

要求：来源 session 自己的 resolve 累积（自证）。

强度：可选。

它与 `hits` 分开的理由：`hits` 的口径是「这条知识的消费者环境是否解决」，而来源 session 是产地；同一份证据不能数两次（[design-theory.md](design-theory.md) 的「独立性假设过强」即指此）。它与 S2 的 `validation_record.self_consistent` 同一条纪律：同一份证据只记一次。由 [settle_trace_feedback.py](../../scripts/settle_trace_feedback.py) 结算。

### 3.4 `validation_record`：{consistent, inconsistent, self_consistent, last_verified}

要求：内容被外部验证的累积记录，由 [settle_s2_feedback.py](../../scripts/settle_s2_feedback.py) 结算，非人设定。

强度：可选。

与 confidence 分开：S2 issue-replay 对照的是外部 ground truth（issue resolution / 维护者 fix PR / committer 确认）。

- `consistent`：外部验证一致（同等 score 下排序优先）。语义是「该 issue 既不是它的来源、也未在正文被引用」，不是「信息独立」——case 与样本出自同一族判词或同一 fix PR 的关联无法机械识别，这点是半硬的。
- `self_consistent`：非独立命中，两种：replay issue 即 case 来源（自证），或 replay issue 在 case 正文里被引用（是该 case 的撰写依据——命中结论就是写 case 时从它那儿读来的，记 consistent 等于一份证据数两次）。
- `inconsistent`：命中但结论与 resolution 不符（复审信号）。

无 S2 验证不填。

### 3.5 `source_ref`：{repo, ref, file, line}

要求：根因定位到源码时记代码位置。

强度：可选。

「源码不落库」= 源码不随仓库提交、也不写进知识库：`.gitignore` 已忽略 `src-code/`（本地分析缓存，按版本平铺为 `src-code/<org>/<repo>/<tag>/`：版本目录自包含、互不干扰，多 agent 并发可各读各版本；缓存根锚到主检出，同一克隆的所有 worktree 共读共写，worktree 清理不丢）。统一走 `scripts/src_fetch.py <repo> --ref <tag>` 按需拉取、同版本复用。

知识库只记结论 + `source_ref` 指针。「不落库」不等于分析不需要源码，深入排查仍要 clone。`ref` 用触发版本对应的 commit / tag（与版本目录名同 token）。

### 3.6 `ref_knowledge`

要求：指向前验层词条的结构化关联，每条是 `ref: <reference-id>` + `role: signature-source | fix-methodology | root-cause-context`。

强度：可选。

怎么判定：`ref` 必须存在、`role` 必须合法，由 [verify_references.py](../../scripts/verify_references.py) 校验。反向视图（哪些 case 引用了某词条）由该脚本派生，绝不存到词条侧——一条关系只存一次。

### 3.7 版本匹配是软的

`compat` 不匹配只降置信度，永不硬排除一条 case；未定义的维度跳过。

## 4 有意保留的例外

- 字段名与枚举值照原样写：`quickly_check`、`service-affecting`、`pending-investigation`、`signature-source` 等。它们是脚本与 case 文件里的真实取值，翻译成中文读者对不上原文。
- `confidence` 与 `validation_record` 都在记「确认」，但不能合并：一个记消费者现场（S1），一个记外部对照（S2），合并等于一份证据数两次。
- `symptoms` 里的报错原文、算子名、版本号原样保留；它们是检索与 grep 的判据。
- 「软匹配」是内容，不是措辞问题：不匹配只降置信度这一条不得为了行文好看改成硬排除。

## 5 哪几条能机检

已进 CI（`.github/workflows/kb-checks.yml`）：

- `case-structure` job 跑 `python3 scripts/verify_case_draft.py --all`：必需字段、三个枚举（`category` / `severity` / `fix_type`）、`ref_knowledge` 的悬挂与 active 校验、`expected` 的正则可编译且无空分支。
- `index-freshness` job 跑 `python3 scripts/build_index.py --check`：每条 case 都有读侧索引行（覆盖检查）。
- `reference-validation` job 跑 `python3 scripts/verify_references.py --check`：解析全部 case YAML 算派生计数。

只能人审：

- 一条 case 的口径是否只承载一种证据（自证不计入 `hits`）。
- 脱敏是否彻底。
- `root_cause` / `fix` 是否只写结论与依据，不写推理过程。

## 6 与相邻规范的关系

- 本文是 case 字段口径的权威处；`CLAUDE.md` 只保留三条跨切面约束（脱敏、源码不落库、compat 软），字段细节以本文为准。
- `self_resolved` 与 `validation_record` 分开的理论依据在 [design-theory.md](design-theory.md)，本文只写字段口径。
- 词句层的原值保留见 [writing-norms.md](writing-norms.md) §2；本文不重复那份清单。
- 草稿产出、索引生成、反馈结算各有自己的权威处，见第 2 节。

## 7 引用

规范性引用：[examples/sample-case.yaml](../../examples/sample-case.yaml)（canonical 示例）、`scripts/verify_case_draft.py`、`scripts/settle_trace_feedback.py`、`scripts/settle_s2_feedback.py`、`scripts/verify_references.py`、[references/_types.yaml](../../references/_types.yaml)。

资料性引用：[design-theory.md](design-theory.md)、[to-postmortem/SKILL.md](../../skills/to-postmortem/SKILL.md)、[diagnosis-procedure.md](../../skills/diagnose/references/diagnosis-procedure.md)。
