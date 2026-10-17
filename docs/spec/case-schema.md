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
- 反馈结算与算分的算法：见 [settle_trace_feedback.py](../../scripts/settle_trace_feedback.py)、[settle_s2_feedback.py](../../scripts/settle_s2_feedback.py) 与 [score_entries.py](../../scripts/score_entries.py)（三者写哪里、谁读，见 [diagnosis-observability.md](../mechanism/diagnosis-observability.md)）。
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
| `investigation_quality` | 取 `high` / `medium` / `low`；**人的调查质量判断**，与来源验证强度（`verification.source`）一起决定这条 case 的冷启动先验分 | 必填 | 必须 |
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

用途只有一个：反馈结算时判定「自证」——来源 session 自己回报的 resolve 记入使用记录的 `self_resolved` 计数，不计入 `resolved`。缺该字段时结算退回原行为（计入 `resolved`）。这是刻意的保守取舍：宁可少识别自证，不误判独立命中。

### 3.3 观测计数不进 case：`resolved` / `misdiagnosed` / `self_resolved`

现场解决、误诊与自证三种计数**不住在 case 文件里**，它们写在 `metrics/entry-activity.d/<周>.yaml`
的使用记录里（由 [settle_trace_feedback.py](../../scripts/settle_trace_feedback.py) 追加），
按 id 聚合后进生成物 `metrics/entry-activity/<部署>.yaml`；排序分数由这份记录与冷启动先验算出、
只落在索引生成物里。口径与三个计数的定义见
[diagnosis-observability.md](../mechanism/diagnosis-observability.md) 的 3.1 与 3.4。

为什么不住在 case 里：同一个量写两处，迟早对不上，而对不上时没有判据说该信哪一处；计数一进
case 文件，结算就变成每次改知识条目，观测与知识本体也就分不开了。case 文件因此只为内容层的
决定而改（复审、合并、退休、补样例），不因观测而改。

它与 S2 的 `validation_record.self_consistent` 同一条纪律：同一份证据只记一次。

### 3.4 `validation_record`：{consistent, inconsistent, self_consistent, last_verified}

要求：内容被外部验证的累积记录，由 [settle_s2_feedback.py](../../scripts/settle_s2_feedback.py) 结算，非人设定。

强度：可选。

与现场解决计数分开：S2 issue-replay 对照的是外部 ground truth（issue resolution / 维护者 fix PR / committer 确认），它证明的是「内容对不对」，不证明「现场解决了没有」——后者只由现场回报写入使用记录。

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

### 3.7 `score_override`：{score, reason, by}

要求：人工覆盖这条 case 的排序分数。三个子字段都必填——`score` 在 `[0, 1]`、`reason` 写清为什么覆盖、`by` 写谁覆盖的。

强度：可选，罕见。

覆盖优先于算分：第 4 步（[score_entries.py](../../scripts/score_entries.py)）算完之后用覆盖值替换该条目的分数，复审与退休的判断也用替换后的值。走高风险改动（两人复核）。条目退休或改 id 时覆盖随条目失效，重新启用要重写。

判据由 `python3 scripts/score_entries.py --check-overrides` 拦下：不带 `reason` 的覆盖在半年后无法判断该不该撤，所以那一项是必填而不是建议。

### 3.8 `upstream`：[{repo, issue|pr, url}]

要求：这条 case 对应的上游锚点。`repo` 写 `owner/name`；`issue` 与 `pr` 二选一（写 `pr` 表示关联的是修复 PR）；`url` 是给人点开的原址。

强度：可选。

用途：外部对照自动查证的分母——有锚点的 case 才能靠上游状态自动确认「内容对不对」，没有锚点的（客户侧现网问题）只能等现场回报。查证由 `scripts/verify_upstream_outcomes.py` 做，结局写进 `validation_record`。**它判断不了「现场是否解决」**，那只有现场能给。

### 3.9 版本匹配是软的

`compat` 不匹配只降置信度，永不硬排除一条 case；未定义的维度跳过。

## 4 有意保留的例外

- 字段名与枚举值照原样写：`quickly_check`、`service-affecting`、`pending-investigation`、`signature-source` 等。它们是脚本与 case 文件里的真实取值，翻译成中文读者对不上原文。
- 使用记录里的现场解决计数与 `validation_record` 都在记「确认」，但不能合并：一个记消费者现场（S1），一个记外部对照（S2），合并等于一份证据数两次。两者也刻意分居两处：一个在 `metrics/` 的记录里，一个在 case 本体（它是这条内容的属性，跟着 case 走）。
- `symptoms` 里的报错原文、算子名、版本号原样保留；它们是检索与 grep 的判据。
- 「软匹配」是内容，不是措辞问题：不匹配只降置信度这一条不得为了行文好看改成硬排除。

## 5 哪几条能机检

已进 CI（`.github/workflows/kb-checks.yml`）：

- `case-structure` job 跑 `python3 scripts/verify_case_draft.py --all`：必需字段、三个枚举（`category` / `severity` / `fix_type`）、`ref_knowledge` 的悬挂与 active 校验、`expected` 的正则可编译且无空分支。
- `index-freshness` job 跑 `python3 scripts/build_index.py --check`：每条 case 都有读侧索引行（覆盖检查），且全库条目 id 唯一、案例文件名与 id 一致。
- `case-structure` job 跑 `python3 scripts/score_entries.py --check-overrides`：`score_override` 若填则必带 `reason` 与 `by`、`score` 在 `[0, 1]`。
- `metrics-validation` job 跑 `python3 scripts/verify_entry_activity.py` 与 `python3 scripts/build_entry_activity.py --check`：使用记录的行形状、`(run, kind, id)` 唯一、条目的计数键都对应真实存在的条目，生成物与源一致。
- `reference-validation` job 跑 `python3 scripts/verify_references.py --check`：解析全部 case YAML 算派生计数。

只能人审：

- 一条 case 的口径是否只承载一种证据（来源会话的自证不计入独立确认的解决计数）。
- `investigation_quality` 的高低是否与现场排查实际做到的程度相符（它只是先验，人给的值没有机械判据）。
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
