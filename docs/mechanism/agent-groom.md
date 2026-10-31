# Agent Groom：同步、语义比对与合入前复核

状态：已落地

原型已在仓库内实现并测试；生产部署还依赖平台侧 required check 与 base 最新（见第 5 节）。

本文说明 groom 如何在**确定的远端知识版本**上，用子 agent 比较本地草稿与现有 case，把评估写成本地状态，并在合入前检查评估是否过期。读者是维护知识库、会改 groom 流程或审这类 PR 的人；只跑诊断、不沉淀的人不必读。

范围：`postmortems/inbox/` 到 `knowledge/` 升格之间的 intake 段，以及 PR 合入前的复核。不覆盖 diagnose 的候选检索、reference 维护段与发布流程。

## 1 解决什么问题

多个贡献者各自在本地 inbox 里沉淀知识时，**本地检查无法证明全局语义唯一**：看不见别人的未提交草稿；即使 fetch 了 main，也可能在评估之后又有 PR 合入。原来的 groom 用当前检出里的 `knowledge/` 索引直接做预分诊，于是同一份草稿在不同机器上得到不同候选，报告里也没有字段能说明"这次比的是哪一版知识"。

本机制解决三件事：

- 把"比的是哪一版知识"变成可执行事实：fetch 后解析 commit，在独立 worktree 里展开，索引与 commit 对不上就重建；fetch 失败默认不继续。
- 把"像不像"交给子 agent 做有界语义比对：候选来自脚本，判断由 agent 给出结构化结果；确定性脚本只做校验、保守聚合与落状态。
- 把"评估是否还成立"变成合入前可检查的条件：记录 `assessed_commit`，base 前进后能判过期；两个 PR 并发时，后合入的一方会被要求重跑。

明确不做：

- **不承诺全局唯一**。fetch 是必要的，但不充分；平台侧不要求 base 最新时，本机制不能阻止旧评估合入。
- **不自动合并、不自动升格、不删除草稿**。agent 的建议不是决定；升格仍走既有闸门与人审。
- **不新建数据库或集中服务**。状态是本地 YAML，唯一进 Git 的是 PR body 里的 provenance marker。
- **不恢复确定性语义指纹方案**。根因改写、缺失中间步骤、AND/OR、多物理实例这些反例说明结构规范化不能单独承担语义身份；本机制把它们当作 agent 比对的对抗输入，而不是继续调规范化规则。

## 2 最小可执行模型

一次 groom 的最小闭环只有四步，全部命令都在仓库根运行：

```bash
python3 scripts/groom_snapshot.py --list-remotes          # 多个远端时先让用户选；只有一个可跳过询问
python3 scripts/groom_snapshot.py --remote <name> --require-fresh  # 只有一个时可省略 --remote
python3 scripts/groom_candidates.py --snapshot <snapshot.json> --all --out <work-orders.json>
# 每份草稿交给一个子 agent；把返回 JSON 存到 <results>/<draft_key>.result.json
python3 scripts/groom_record.py --snapshot <snapshot.json> --work-orders <work-orders.json> --results-dir <results/>
```

产物是 `postmortems/inbox/.groom/assessments/<key>.yaml` 一份本地评估状态。人用 `groom_status.py` 看一屏，用 `groom_decide.py` 写决定；提 PR 时把 `groom_record.py --pr-marker` 的输出贴进 body。

三个概念贯穿全文：

| 概念 | 含义 | 存在哪 |
|---|---|---|
| 知识快照 | 一个确定的 commit 及其只读展开，带 `fresh` / `authoritative` 标记 | 共享 inbox 下 `.groom/snapshots/`，gitignored |
| 工作单 | 一份草稿 + 有界候选摘录 + 返回格式 | 运行时 JSON，gitignored |
| 评估状态 | `assessment`（agent 建议）+ `human_decision`（人决定）+ provenance | `postmortems/inbox/.groom/assessments/`，gitignored |

## 3 完整机制

### 3.1 快照：先确定比的是哪一版

结论：groom 只在一个**fetched 后解析出的 commit** 上比对；不 pull、不 merge、不改源工作区。

同步源由用户决定，不在流程里写死。每次同步前，agent 跑 `groom_snapshot.py --list-remotes`；它只列本机
已经配置的远端名，不判断托管平台，也不输出地址。**只有一个远端时直接使用，不再问用户**；有多个时把名字给用户，
问“这次从哪个远端更新”，再用用户选定的 `--remote` 跑。用户要用的远端不在列表里，就由用户提供名字和地址、
自己 `git remote add`；agent 不猜。快照 meta 只记录实际使用的 `remote`，不记录平台类型或端点地址。

`groom_snapshot.py` 执行顺序：

1. `git fetch --no-tags <remote> <branch>`。失败时默认退出 2；只有显式 `--offline` 才退回本地已有引用。
2. `git rev-parse refs/remotes/<remote>/<branch>^{commit}` 得到 commit，作为 `compared_against_commit`。
3. `git worktree add --detach <快照路径> <commit>`。路径在共享 inbox 下，与源工作区分离；源工作区的未提交改动与未跟踪草稿都不动。`git worktree` 失败时，从指定 commit 用 `git archive` 展开。只有 worktree 路径会校验 `HEAD`；archive 没有 Git 元数据。
4. 在快照里跑 `scripts/build_index.py --check`；不通过就重建，再校验一次。索引状态写进 meta：`verified` / `rebuilt` / `unavailable`。

`fresh` 表示 fetch 成功；`authoritative` 表示 fresh 且索引可用。两者分开记录，因为"抓到了但索引坏了"和"没抓到"的处置不同：前者不能做候选检索，后者整轮不能升格。

快照目录在复用前会核对：HEAD 必须等于目标 commit，且除 `knowledge/_index*`（快照内重建索引的预期产物）外不能有任何 tracked/untracked 改动。源 Case 被改过的快照不复用，整棵重建；重建失败就报错，不把被改过的树当成该 commit 的权威表示。

### 3.2 候选工作单：把阅读面缩到有界

结论：候选由词法信号从快照索引里选，最多 8 条；agent 不读全库。

`groom_candidates.py` 读快照的 `knowledge/_index.yaml`，对每份草稿：

- 从标题、症状、root cause、fix、tags、diagnosis 命令里抽 token、缩写与中文字组；
- 用 IDF 降低"训练/启动/失败"这类高频词的权重，按报错字面量、token 交集、缩写、标签、标题/症状重叠排序；
- 同分类有词法证据的优先；`common/` 给固定席位；不足 3 条时用全库最高分补位；
- 默认取 6 条、硬上限 8 条；池大小与省略数写进工作单。

每条候选只带判重需要的摘录（root cause、fix、症状、compat、诊断前几步），不附全文。工作单里还写入返回格式与保守规则。

这一步只负责**召回**：它不判断两条知识是否等价，也不把"没有词法重叠"当成"无关"——语义判断留给子 agent。

### 3.3 子 agent 比对：有界、只读、逐条覆盖

结论：每份草稿一个子 agent，同时最多 3 个（硬上限 4 个）；子 agent 只返回 JSON。

分工：

| 角色 | 输入 | 输出 | 不做什么 |
|---|---|---|---|
| 比较 agent | 一份工作单 | 每条候选的分类、置信度、证据轴、理由 | 不写文件、不升格、不跨草稿 |
| 复核 agent（可选） | 工作单 + 第一份结论 | `confirm` / `challenge` / `insufficient`、误合并风险 | 不重新找候选，不能把 ambiguous 改成合并 |

分类限定为 `duplicate` / `covered` / `variant` / `new_pattern` / `ambiguous`。提示词要求逐条覆盖工作单里的每个候选；漏一条会让整份评估被记录阶段判为无效。

没有子 agent 机制的 Harness 按同一提示顺序执行，返回同一 schema；不允许退回"按本地旧索引直接判"。

### 3.4 校验与聚合：agent 的建议不是结论

结论：记录阶段用确定性规则把不一致、证据不足与高置信度误合并拦下来。

`groom_record.py` 先校验：候选必须来自工作单、逐条覆盖、枚举合法、理由非空。任一不满足，整份草稿记为 `ambiguous` 并进人工复核。

校验通过后按保守规则聚合：

- 只有 `high` 置信度的 `duplicate` / `covered` 才可能成为建议；中/低置信度降为 `ambiguous`。
- 两个候选同时被高置信度判重复 → `ambiguous`，不自动选一个。
- 复核 agent 判 `challenge` 或标 `false_merge_risk` → `ambiguous`。
- 证据一致性校验（`apply_evidence_guard`）：分类是 `duplicate` / `covered`，但 agent 自己写的 `root_cause` 或 `mechanism` 不是 `same` → 降为 `ambiguous`；根因与机制相同但 `fix` 明确不同 → 降为 `variant`；分类是 `variant` 但根因与机制都明确不同 → 降为 `ambiguous`。

最后一条不是第二个语义比较器，它只读 agent 已经写下的证据轴，拦"分类与证据自相矛盾"的结论。它的代价是更保守：正确但置信度中等的重复会被推到人工复核，而不是自动标 covered。

### 3.4b 证据绑定：授权只对同一次评估有效

结论：一次评估的身份由 `assessment_id` 固定；旧结果、旧工作单、旧批准都不能授权新内容。

`assessment_id` 是以下输入的哈希：快照 commit、草稿 key、草稿内容指纹、每个候选的规范化内容指纹、
结果文件的字节哈希、复核文件的字节哈希。结果 JSON 必须回显 `work_order_id`、`snapshot_commit`、
`draft_sha256`、`candidate_ids`；`groom_record.py` 重新计算并对照当前草稿与快照。任一不符 →
`promotion_gate.blocked_reason = binding-mismatch`，不采用结果。

规范化内容（`canonical_case_content`）只保留与判断和安全有关的字段：category、tags、symptoms、root_cause、
fix、compat、platforms、severity、fix_side_effects、fix_type、quickly_check、diagnosis、verification。
字符串逐字保留，包括首尾空白、命令引号内空格、正则与换行；`tags` / `platforms` / `fix_side_effects` 这类集合列表排序，
其余列表保序——尤其 `diagnosis` 的步骤顺序、每步的 `fix_on_mismatch` / `rollback` 变了会导致
`content-mismatch`。升格时改 id、文件名、title 不会误伤，但改根因、修复、适用条件、严重度或诊断步骤会。

人的批准也绑定到 `assessment_id` 与 `content_binding.sha256`。评估重跑后身份变化，旧批准保留在
`human_decision_history`，但 `human_decision_valid` 变为 false，`promotion_gate` 标 `approval-stale`；
`--pr-marker` 不会把它写成有效授权（输出 `human_decision: pending`）。

### 3.5 本地状态：评估、人决定、身份分开

结论：agent 建议、人的决定、永久 Case 身份是三样东西，分别存。

评估状态文件结构（`postmortems/inbox/.groom/assessments/<key>.yaml`）：

```yaml
schema: groom-assessment/v1
draft: <draft key>
draft_case_id: <草稿建议的 id>
draft_sha256: <草稿内容指纹>
assessment_id: <一次评估的哈希>
content_binding:
  sha256: <规范化语义内容的哈希>
  fields: [category, tags, symptoms, root_cause, fix, ...]
  candidate_bindings: [{id, content_sha256}, ...]
assessment:
  proposed_novelty: duplicate | covered | variant | new_pattern | ambiguous
  candidate_case: <case id 或 null>
  confidence: high | medium | low
  review_required: true
  rationale: <一句话>
  review_reasons: [...]
  alternatives: [...]
human_decision:              # 只由 groom_decide.py 写
  decision: new_pattern | variant | covered | defer | reject
  candidate_case: <case id 或 null>
  by: <owner>
  applies_to_commit: <决定时看到的知识 commit>
  assessment_id: <批准针对的那次评估>
  content_sha256: <批准针对的那份内容>
  overrides_agent: true | false
human_decision_valid: true | false
human_decision_history: [...]
provenance:
  compared_against_commit: <sha>
  snapshot_fresh: true | false
  snapshot_authoritative: true | false
  work_order_id: <工作单哈希>
  binding_ok: true | false
  binding_errors: [...]
  result_sha256: [...]
  candidates: [...]
  agents: [...]
history: [...]
```

几个行为：

- **原子写**：同目录临时文件 + `fsync` + `os.replace`；半份写入不会被读到。中断留下的 `.tmp` 不参与读取。
- **幂等**：同一份结果重跑，内容不变就不重写（`assessed_at` / `history` 不参与比较）。
- **不覆盖人决定**：重跑只更新 `assessment`；`human_decision` 原样保留，但只有
  `assessment_id` 与 `content_binding.sha256` 都对得上时 `human_decision_valid` 才为 true。对不上时
  标 `approval-stale` 并阻塞升格，等人重新确认；旧批准进 `human_decision_history`。
- **草稿字节不变**：评估写本地评估状态文件（sidecar），不写回 `case.yaml`；永久 Case ID 只在升格时由人确认。
- **过期检测**：`groom_status.py` 比较 `compared_against_commit` 与当前目标 commit，并检查 `knowledge/` 是否变化、草稿指纹是否变化；任一变化标 `STALE`。

### 3.6 PR provenance 与合入前复核

结论：评估必须跟着 PR 走到 CI，合入前检查它是否还对着当前 base。

`groom_record.py --pr-marker` 生成一段 HTML 注释：

```text
<!-- groom-assessment
schema: groom-pr/v2
draft: draft-a
case_id: DRAFT-A
submitted_case_id: CASE-001
category: interrupt
assessed_commit: <sha>
assessment_id: <sha>
assessed_content_sha256: <sha>
proposed_novelty: covered
candidate_case: CASE-001
human_decision: covered
human_decision_assessment_id: <sha>
human_decision_content_sha256: <sha>
review_required: true
approval_stale: false
-->
```

`groom_recheck.py` 在 PR 上做五类确定性检查：

1. marker 字段齐全、枚举合法、重复字段拒绝；`assessment_id` / content hash 是 64 位十六进制；
   人的 `assessment_id` / content hash 必须与本次评估一致。`reject` / `defer` 不授权任何内容提交。
2. `assessed_commit` 在本仓库、是 base 的祖先。
3. 从 `assessed_commit` 到 base，相关 `knowledge/` 是否变了（按草稿 category、`common/`、候选文件过滤）。变了就是过期，退出 2。
4. 每个被新增/修改的 Case 都要有 marker；提交 Case 的规范化内容哈希必须等于 marker 的
   `assessed_content_sha256`，否则 `content-mismatch`。`new_pattern` 只能授权新增文件；`variant`
   只能授权修改已有 Case；`covered` 不授权新增/修改。
5. PR 新增 case 与 base 前进期间新增 case 是否有共同字面量；有就报 `possible-duplicate-after-merge`，要求人复核。它不判重复，只拦"看都没看"。

退出码：0 通过；2 需要重跑/复核；3 参数或 git 不可用。`--advisory` 只报告、不改变退出码，供人工试跑。

### 3.7 合入后

合入后由主干 job 重建索引（`build_index.py` 的覆盖检查必须通过）；没有该 job 的部署按既有纪律在 main 上重建。`groom_recheck.py --post-merge` 可以在本地跑同一道覆盖检查。

## 4 边界与失败模式

| 情形 | 行为 | 是否静默 |
|---|---|---|
| fetch 失败 | 默认退出 2，不建快照；`--offline` 才继续 | 否：meta 与报告都标 stale / 非权威 |
| 索引与 commit 不一致 | 在快照内重建；重建失败标 `unavailable` | 否 |
| 子 agent 无结果 / 非 JSON / 漏候选 | 整份 `ambiguous` + 人工复核 | 否：review_reasons 写明 |
| 结果与工作单/快照/草稿指纹不一致 | `binding-mismatch`，不采用结果，retcode 2 | 否 |
| 两个候选结论冲突 | `ambiguous`，不自动选 | 否 |
| 评估后知识前进 | `STALE`；recheck 退出 2 | 否 |
| 草稿在评估后被改 | `STALE`；草稿字节不被覆盖 | 否 |
| PR 提交内容与评估内容不一致 | `content-mismatch` | 否 |
| PR 的 Case 没有 marker | `case-without-provenance` | 否 |
| 人的批准绑定的是旧评估 | `approval-stale`；marker 输出 pending | 否 |
| 人的决定是 reject/defer/covered 但 PR 提交内容 | `decision-does-not-authorize` | 否 |
| 写入中断 | 旧文件仍完整；`.tmp` 被忽略 | 否 |
| 两个 PR 并发 | 后合入方 base 前进 → recheck 报过期；新 case 撞字面量 → 报可能重复 | 不保证语义判重 |
| 离线 | 非权威快照；`promotion_gate` 阻塞 `stale-snapshot` | 否 |
| 旧状态文件损坏 | 备份成 `.corrupt-<时间>` 后重写 | 否：报告里提示 |

不能保证的事：语义等价的召回率、不同措辞/缺失证据下的判断正确率、所有并发草稿都被看见、agent 结论等同于事实。`assessment_id` 是内容与来源的声明，不是签名——有写权限的人可以复制一份真实评估的 id；它防的是"内容/证据与声明不一致"，不是伪造声明。子 agent 的"只读"是提示词与流程约束，不是沙箱；真正的写权限由 Harness/平台控制，本流程只读取它返回的 JSON。合成夹具上的数字不是生产准确率。

## 5 现状

### 已落地

- 快照、候选、记录、决定、状态、合入前复核六个脚本。
- 确定性测试：快照/离线/索引重建、候选有界、记录校验与聚合、幂等、损坏恢复、人决定保留、过期检测、并发 PR、两个独立 inbox、端到端 A 先合入 B 过期再重跑。
- 验证命令：`python3 -m unittest tests.test_groom_snapshot tests.test_groom_candidates tests.test_groom_record tests.test_groom_status tests.test_groom_recheck tests.test_groom_workflow tests.test_groom_binding`。

### 蓝图

- 平台侧若要把复核变成强制：在 ruleset 里增加一个跑 `groom_recheck.py` 的检查并设为必需，同时要求 base 最新；本 PR 不新增 CI job。
- 打开 PR 候选（`pr_radar` 类能力）：当前只比 main；在途 PR 的 case 仍可能互相撞车。
- 在真实（已脱敏）case 上做离线验证，再决定阈值与是否需要独立复核 agent。
- 合并队列：作为吞吐优化，不作为正确性前提；引入前要验证 `merge_group` 的 base/head 语义。

### 已否决

- 用内容指纹/规范化结构作为永久 Case ID：研究记录里的误拆分与误合并反例说明它不能单独承担语义身份。
- 自动合并、自动升格、自动删草稿：与"agent 建议不是事实"冲突。
- 把 agent 的 `covered` 直接写成人决定：人机分家是这条流程的安全阀。

## 6 代码与文档入口

| 入口 | 作用 |
|---|---|
| `scripts/groom_snapshot.py:64` | 列出本机远端名，供用户确认同步源 |
| `scripts/groom_snapshot.py:209` | 建快照、fetch、worktree、索引校验 |
| `scripts/groom_candidates.py:233` | 候选打分与有界工作单 |
| `scripts/groom_record.py:312` | 证据一致性校验 |
| `scripts/groom_record.py:393` | 保守聚合 |
| `scripts/groom_decide.py:30` | 写人决定 |
| `scripts/groom_status.py:56` | 状态与新鲜度 |
| `scripts/groom_recheck.py:449` | PR 合入前复核 |
| `scripts/groom_common.py` | 草稿发现、状态读写、git 工具 |
| `skills/knowledge-groom/SKILL.md` | 流程与判断规则 |
| `skills/knowledge-groom/references/subagent-prompts.md` | 子 agent 提示词与返回格式 |

## 7 外部参考

- GitHub 的 required status checks 与 "Require branches to be up to date before merging" 是这里说的平台侧前提；本仓只提供检查脚本，不提供平台强制。
- 语义去重的替代做法（向量检索、结构指纹、规则规范化）各有代价；本仓的检索仍走词法/结构，不做向量 RAG（见 `docs/adr/0002`）。本机制把语义判断放在 agent 侧，是为了在证据不足时能弃权，而不是用相似度阈值冒充等价。
