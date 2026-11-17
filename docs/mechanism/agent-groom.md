# Agent Groom：知识快照、语义比对与合入前复核

groom 负责把本地草稿升格成知识条目。它在**确定的远端知识版本**上用子 agent 比较草稿与现有 case，把评估写成本地状态，并在合入前检查评估是否过期。

读者是维护知识库、会改 groom 流程或审这类 PR 的人；只跑诊断、不沉淀的人不必读。前置是 [operations.md](operations.md) 3.5（内容维护在每周流程里的位置）与 [records.md](records.md) 3.2（样本与状态字段）。

范围：`postmortems/inbox/` 到 `knowledge/` 升格之间的 intake 段，以及 PR 合入前的复核。不覆盖诊断的候选检索、先验知识层（`references/`）那一节、发布流程。

## 1 解决什么问题

多个贡献者各自在本地 inbox 里沉淀知识时，本地检查无法证明全局语义唯一：看不见别人未提交的草稿；即使抓取了 main，也可能在评估之后又有 PR 合入。原来的 groom 用当前检出里的 `knowledge/` 索引直接做预分诊，于是同一份草稿在不同机器上得到不同候选，报告里也没有字段能说明「这次比的是哪一版知识」。

本机制解决三件事：

- 把「比的是哪一版知识」变成可执行事实：抓取后解析提交，在独立 worktree 里展开，索引与提交对不上就重建；抓取失败默认不继续。
- 把「像不像」交给子 agent 做有界语义比对：候选来自脚本，判断由 agent 给出结构化结果；确定性脚本只做校验、保守聚合与写状态。
- 把「评估是否还成立」变成合入前可检查的条件：记录 `assessed_commit`，基线前进后能判过期；两个 PR 并发时，后合入的一方会被要求重跑。

明确不做：

- **不承诺全局唯一**。抓取是必要的，但不充分；平台侧不要求基线最新时，本机制不能阻止旧评估合入。
- **不自动合并、不自动升格、不删除草稿**。agent 的建议不是决定；升格仍走既有检查条件与人审。
- **不新建数据库或集中服务**。状态是本地 YAML，唯一进 git 的是 PR body 里的来源标记。
- **不恢复确定性语义指纹方案**。根因改写、缺失中间步骤、AND/OR、多物理实例这些反例说明结构规范化不能单独承担语义身份；本机制把它们当作 agent 比对的对抗输入。

## 2 最小可执行模型

一次 groom 的最小循环只有四步，全部命令都在仓库根运行：

```bash
python3 scripts/groom_snapshot.py --list-remotes          # 多个远端时先让用户选；只有一个可跳过询问
python3 scripts/groom_snapshot.py --remote <name> --require-fresh  # 只有一个时可省略 --remote
python3 scripts/groom_candidates.py --snapshot <snapshot.json> --all --out <work-orders.json>
# 每份草稿交给一个子 agent；把返回 JSON 存到 <results>/<draft_key>.result.json
python3 scripts/groom_record.py --snapshot <snapshot.json> --work-orders <work-orders.json> --results-dir <results/>
```

产物是 `postmortems/inbox/.groom/assessments/<key>.yaml` 一份本地评估状态。人用 `groom_status.py` 看一屏，用 `groom_decide.py` 写决定；提 PR 时把 `groom_record.py --pr-marker` 的输出贴进 body。终态决定写盘、PR 合入后跑 `python3 scripts/groom_close_draft.py --all --apply`，回写来源记录的沉淀状态并把草稿移出队列。没有 PR 的部署仍在评估写盘后直接收尾。

三个概念贯穿全文：

| 概念 | 含义 | 存在哪 |
|---|---|---|
| 知识快照 | 一个确定的提交及其只读展开，带 `fresh` 与 `authoritative` 标记 | 共享 inbox 下 `.groom/snapshots/`，不进 git |
| 工作单 | 一份草稿、有界候选摘录、返回格式 | 运行时 JSON，不进 git |
| 评估状态 | `assessment`（agent 建议）、`human_decision`（人决定）、来源信息 | `postmortems/inbox/.groom/assessments/`，不进 git |

## 3 完整机制

### 3.1 快照：先确定比的是哪一版

groom 只在一个**抓取后解析出的提交**上比对；不 pull、不 merge、不改源工作区。

同步源由用户决定，不在流程里写死。每次同步前跑 `groom_snapshot.py --list-remotes`，它只列本机已经配置的远端名，不判断托管平台，也不输出地址。只有一个远端时直接使用，不再问用户；有多个时把名字给用户，问这次从哪个远端更新。用户要用的远端不在列表里，由用户提供名字和地址、自己 `git remote add`；agent 不猜。

`groom_snapshot.py` 的执行顺序：

1. `git fetch --no-tags <remote> <branch>`。失败时默认退出 2；只有显式 `--offline` 才退回本地已有引用。
2. `git rev-parse refs/remotes/<remote>/<branch>^{commit}` 得到提交，作为 `compared_against_commit`。
3. 建快照目录：有稀疏清单时用 `git worktree add --no-checkout --detach` 加 `git sparse-checkout` 三步展开；没有清单时退回整树 worktree。`git worktree` 或稀疏三步失败时，用 `git archive [<清单>]` 展开；archive 没有 `.git`，永远不满足复用条件，每次都会重铺。
4. 在快照里跑 `scripts/build_index.py --check`；不通过就重建，再校验一次。索引状态写进 meta：`verified`、`rebuilt`、`unavailable`。

**快照物化的是索引的输入集，不是整棵树。** 默认清单是 `knowledge`（case 本体）、`scripts`（生成器与它的 import 链）、`metrics`（`metrics/entry-activity/` 决定每行的 `score`）。三项都是实测出来的最小依赖：去掉 `metrics` 后生成器不报错，但分数退回先验值、索引与仓库那份不再逐字节相同。`references/` 当前不在清单里：生成索引不需要它，但 `build_index.py --check` 的「先验 id 唯一性」一段会因目录缺失而静默跳过。

清单里在该提交不存在的路径会被跳过；缺了哪几项记在 meta 的 `checkout.missing` 里，`knowledge` 缺失直接失败。稀疏模式有一条固有规则：仓库根目录下的文件总是被包含，快照因此仍有约 1 MB 的根文件；清单外的目录则不落盘。复用前除了比 `HEAD` 与工作区改动，还要比对检出范围，否则稀疏下「没检出」与「没改」长得一样，范围会悄悄漂移。

复用前核对三件事：`HEAD` 必须等于目标提交；检出范围必须与当前期望一致；除 `knowledge/_index*` 之外不能有任何已跟踪或未跟踪改动。源 Case 被改过的快照不复用，整棵重建。

**用完即删，但按草稿删**：PR 合入后先跑 `groom_close_draft.py`，再跑 `groom_cleanup.py --pr-body-file <body> --post-merge --base <merge>^1 --head <merge>`。清理先核对来源标记与本地评估是同一次评估（`assessment_id`、内容哈希、人决定），执行阶段持目录级清理锁；对得上的评估文件直接删除，快照只在「没有任何现存评估再引用该提交、且不是 30 分钟内刚建的那份」时才删。读不出评估视为引用未知、不删快照；非终态决定与 `approval_stale` 一律保留。单条失败只保留该项并继续；非预期异常折成 `internal-error`，退出 2。

顺带清两类可弃中间件：`.groom/runs/` 下超过 1 天的工作单目录，以及「对应评估文件已不存在且超过 7 天」的残留锁。清理不碰 `latest.json`（上一次比的是哪个提交的唯一记录），且必须放在收尾而不是开头，`groom_record` 还要用这份检出。

`sedimented` 描述知识沉淀到哪一步，清理状态描述本地产物还能不能删；两者相关但不等同。`fresh` 表示抓取成功，`authoritative` 表示 fresh 且索引可用；两者分开记录，因为「抓到了但索引坏了」和「没抓到」的处置不同。

### 3.2 候选工作单：把阅读面缩到有界

候选由词法信号从快照索引里选，最多 8 条；agent 不读全库。

`groom_candidates.py` 读快照的 `knowledge/_index.yaml`，对每份草稿：从标题、症状、根因、fix、tags、诊断命令里抽 token、缩写与中文字组；用 IDF 降低「训练」「启动」「失败」这类高频词的权重，按报错字面量、token 交集、缩写、标签、标题与症状重叠排序；同分类有词法证据的优先，`common/` 给固定席位，不足 3 条时用全库最高分补位；默认取 6 条、硬上限 8 条，池大小与省略数写进工作单。

每条候选只带判重需要的摘录（根因、fix、症状、compat、诊断前几步），不附全文。工作单里还写入返回格式与保守规则。这一步只负责召回：它不判断两条知识是否等价，也不把「没有词法重叠」当成「无关」。

### 3.3 子 agent 比对：有界、只读、逐条覆盖

每份草稿一个子 agent，同时最多 3 个（硬上限 4 个）；子 agent 只返回 JSON。

| 角色 | 输入 | 输出 | 不做什么 |
|---|---|---|---|
| 比较 agent | 一份工作单 | 每条候选的分类、置信度、证据维、理由 | 不写文件、不升格、不跨草稿 |
| 复核 agent（可选） | 工作单加第一份结论 | `confirm`、`challenge`、`insufficient`、误合并风险 | 不重新找候选，不能把 ambiguous 改成合并 |

分类限定为 `duplicate`、`covered`、`variant`、`new_pattern`、`ambiguous`。提示词要求逐条覆盖工作单里的每个候选；漏一条会让整份评估被记录阶段判为无效。没有子 agent 机制的 harness 按同一提示顺序执行、返回同一 schema；不允许退回「按本地旧索引直接判」。

### 3.4 校验、聚合与证据绑定

记录阶段用确定性规则把不一致、证据不足与高置信度误合并拦下来，并把一次评估的身份绑死。

`groom_record.py` 先校验：候选必须来自工作单、逐条覆盖、枚举合法、理由非空。任一不满足，整份草稿记为 `ambiguous` 并进人工复核。校验通过后按保守规则聚合：

- 只有 `high` 置信度的 `duplicate` 或 `covered` 才可能成为建议；中、低置信度降为 `ambiguous`。
- 两个候选同时被高置信度判重复，降为 `ambiguous`，不自动选一个。
- 复核 agent 判 `challenge` 或标 `false_merge_risk`，降为 `ambiguous`。
- 证据一致性校验：分类是 `duplicate` 或 `covered`，但 agent 自己写的根因或机制不是 `same`，降为 `ambiguous`；根因与机制相同但 fix 明确不同，降为 `variant`；分类是 `variant` 但根因与机制都明确不同，降为 `ambiguous`。

最后一条不是第二个语义比较器，它只读 agent 已经写下的证据维，拦「分类与证据自相矛盾」的结论。代价是更保守：正确但置信度中等的重复会被推到人工复核，而不是自动标 covered。

`assessment_id` 是以下输入的哈希：快照提交、草稿 key、草稿内容指纹、每个候选的规范化内容指纹、结果文件的字节哈希、复核文件的字节哈希。结果 JSON 必须回显 `work_order_id`、`snapshot_commit`、`draft_sha256`、`candidate_ids`；`groom_record.py` 重新计算并对照当前草稿与快照。任一不符即 `promotion_gate.blocked_reason = binding-mismatch`，不采用结果。

规范化内容只保留与判断和安全有关的字段：category、tags、symptoms、root_cause、fix、compat、platforms、severity、fix_side_effects、fix_type、quickly_check、diagnosis、verification。字符串逐字保留，包括首尾空白、命令引号内空格、正则与换行；`tags`、`platforms`、`fix_side_effects` 这类集合列表排序，其余列表保序——尤其 `diagnosis` 的步骤顺序、每步的 `fix_on_mismatch` 与 `rollback` 变了会导致 `content-mismatch`。升格时改 id、文件名、title 不会误伤。

人的批准也绑定到 `assessment_id` 与 `content_binding.sha256`。评估重跑后身份变化，旧批准保留在 `human_decision_history`，但 `human_decision_valid` 变为 false，`promotion_gate` 标 `approval-stale`；`--pr-marker` 不会把它写成有效授权。

### 3.5 本地状态：评估、人决定、身份分开

agent 建议、人的决定、永久 Case 身份是三样东西，分别存。人审时跑 `groom_status.py --decision-prompt`，它把每份未决草稿整理成「评估、候选、理由、编号选项」的问答块；人回复编号和候选后再执行 `groom_decide.py`。`groom_recheck.py` 是确定性检查，直接执行，不需要问人。

评估状态文件结构：

```yaml
schema: groom-assessment/v1
draft: <draft key>
assessment_id: <一次评估的哈希>
content_binding: {sha256: <规范化语义内容的哈希>, fields: [...]}
assessment: {proposed_novelty: duplicate | covered | variant | new_pattern | ambiguous,
             candidate_case: <case id 或 null>, confidence: high | medium | low,
             review_required: true, rationale: <一句话>, review_reasons: [...]}
human_decision: {decision: new_pattern | variant | covered | defer | reject,
                 assessment_id: <批准针对的那次评估>, content_sha256: <批准针对的那份内容>}
human_decision_valid: true | false
human_decision_history: [...]
provenance: {compared_against_commit: <sha>, target_ref: refs/remotes/<remote>/<branch>,
             snapshot_fresh: true | false, snapshot_authoritative: true | false, binding_ok: true | false}
history: [...]
```

几个行为：

- **原子写**：同目录临时文件加 `fsync` 加 `os.replace`；半份写入不会被读到，中断留下的临时文件不参与读取。
- **幂等**：同一份结果重跑，内容不变就不重写（时间戳与 `history` 不参与比较）。
- **不覆盖人决定**：重跑只更新 `assessment`；`human_decision` 原样保留，但只有 `assessment_id` 与 `content_binding.sha256` 都对得上时 `human_decision_valid` 才为 true；对不上时标 `approval-stale` 并阻塞升格，旧批准进 `human_decision_history`。
- **草稿字节不变**：评估写本地状态文件，不写回 `case.yaml`；永久 Case ID 只在升格时由人确认。
- **过期检测**：`groom_status.py` 按每份评估的 `target_ref` 解析当前目标提交，再检查 `knowledge/` 是否前进、草稿指纹是否变化。评估是目标祖先且知识确有前进时，报「知识库在评估后前进了 N 个文件」。
- **目标问题也标 STALE，但原因分开**：ref 不可用、评估 ref 与当前配置目标不一致、目标落后于评估基准、两边无法比较，都会阻塞升格，报告分别写原因。目标未配置或 ref 不可用时显式说明，不用 `origin/main` 静默替换。

### 3.6 PR 来源标记与合入前复核

评估必须跟着 PR 走到 CI，合入前检查它是否还对着当前基线。`groom_record.py --pr-marker` 生成一段 HTML 注释，含 `assessed_commit`、`assessment_id`、`assessed_content_sha256`、`proposed_novelty`、`candidate_case`、`human_decision` 与 `approval_stale`。

`groom_recheck.py` 在 PR 上做五类确定性检查：

1. 标记字段齐全、枚举合法、重复字段拒绝；`assessment_id` 与内容哈希是 64 位十六进制，人的两项必须与本次评估一致。`reject`、`defer` 不授权任何内容提交。
2. `assessed_commit` 在本仓库、是基线的祖先。
3. 从 `assessed_commit` 到基线，相关 `knowledge/` 是否变了（按草稿 category、`common/`、候选文件过滤）。变了就是过期，退出 2。
4. 每个被新增或修改的 Case 都要有标记；提交 Case 的规范化内容哈希必须等于标记的 `assessed_content_sha256`，否则 `content-mismatch`。`new_pattern` 只能授权新增文件；`variant` 只能授权修改已有 Case，且提交内容必须是草稿的完整最终内容；`covered` 不授权新增或修改。
5. PR 新增 case 与基线前进期间新增 case 是否有共同字面量；有就报 `possible-duplicate-after-merge`，要求人复核。它不判重复，只拦「看都没看」。

退出码：0 通过；2 需要重跑或复核；3 参数或 git 不可用。`--advisory` 只报告、不改变退出码。`--base` 省略时读主检出 `.local/settings.json` 的 `target`，与提 PR 目标一致；没有配置目标时退回 `origin/main` 并说明。

### 3.7 收尾、撤销与合入后

终态决定之后还有两件事必须落地，由 `groom_close_draft.py` 一次做完；它是本地收尾动作，不进 CI。有 PR 的草稿，这两件事放在 PR 合入之后：合入前跑收尾会把「待合入」提前写成「已升格」，PR 被拒时人的决定与评估证据也已经被清理。脚本读 PR 台账，同 key 的 PR 不是 merged 时拒绝执行；确实要提前收尾时用 `--allow-open-pr`。没有 PR 的部署仍在评估写盘后直接收尾。

这两件事以前只写在 skill 的一句中文指令里：把来源记录的 `sedimented` 从 `submitted` 改成 `knowledge` 或 `archived`，把已处理的草稿移出 inbox。漏做都不报错——面板的沉淀漏斗停在「已提交待升格」，草稿下一轮又按「没有评估文件先补跑比对」被评一遍。脚本先取写盘证据（case 或 postmortem 文件是否已就位）、再写状态：

| 决定 | 写盘证据（不满足就拦下） | `sedimented` | `case_id` |
|---|---|---|---|
| `covered`（含 agent 判 `duplicate`） | postmortem 已在 `postmortems/<季>/`（Tier 3） | `archived` | 覆盖它的 case |
| `new_pattern` | 对应 case 已在 `knowledge/` | `knowledge` | 升格后的 case（改过 id 用 `--case-id`） |
| `variant` | 合并后的 case 已在 `knowledge/` | `knowledge` | 被并入的 case |

几条边界：写状态走 `trace_transition.py`（按 `trace-status.yaml` 校验状态词表）；草稿移进 `postmortems/inbox/.done/`，移动不删除、移回即复活；外部来源没有记录时只出队、不回写；记录文件不存在时只出队并记 `trace-missing`；`reject` 与 `defer` 不是终态，不动记录、不出队。`reject` 没有对应的 `sedimented` 状态——草稿确实提交过、没有转正，改回 `none` 等于抹掉事实。

为什么不做成 PR 检查：`traces/` 与 `postmortems/inbox/` 是不进 git 的运行时件，PR 与 CI 的检出里没有它们，标记也不带会话号。塞进 `groom_recheck.py` 只能读到空目录，检查会退化成永远通过。这道检查只能落在本地，靠收尾顺序保证：先 `groom_recheck`，开 PR，合入后跑本步，最后 `groom_cleanup --post-merge`。`--post-merge` 跳过过期判定，合入后无法再对旧基线重跑 groom。

撤销一次不成立的沉淀用 `scripts/sediment_undo.py --draft-key <key> [--apply]`，默认只打印计划。它做四件事：把还在 inbox、PR 记录不存在或已关闭的草稿移进 `postmortems/inbox/.undone/`；删掉它的评估状态文件；把来源记录的 `sedimented` 改回 `none`（记录缺失或外部来源时跳过）；清掉台账里那条已关闭的 PR 记录。诊断状态不动：撤销还原 case 的沉淀状态，已收尾的单仍是收尾状态。它和 `reject`、`defer` 不是一回事：那两个是「认真看过但不采纳」，草稿与评估状态留在队列里；撤销是这份草稿本身被撤回，重新沉淀会从头开始。

合入后由主干 job 重建索引（`build_index.py` 的覆盖检查必须通过）；没有该 job 的部署按既有纪律在 main 上重建。`groom_recheck.py --post-merge` 可以在本地跑同一道覆盖检查。收尾与清理也在这一步：先 `groom_close_draft.py` 出队并回写记录，再对每份 PR 用合入提交与它的第一个父提交跑 `groom_cleanup.py --post-merge`。

## 4 边界与失败模式

| 情形 | 行为 | 是否静默 |
|---|---|---|
| 抓取失败 | 默认退出 2，不建快照；`--offline` 才继续 | 否：meta 与报告都标 stale 或非权威 |
| 索引与提交不一致 | 在快照内重建；重建失败标 `unavailable` | 否 |
| 子 agent 无结果、非 JSON、漏候选，或结果与工作单、快照、草稿指纹不一致 | 前者整份 `ambiguous` 加人工复核；后者 `binding-mismatch`，不采用结果，退出 2 | 否：写明原因 |
| 评估后知识前进、或草稿在评估后被改 | `STALE`；复核退出 2，草稿字节不被覆盖 | 否 |
| PR 提交内容与评估内容不一致 | `content-mismatch` | 否 |
| PR 的 Case 没有来源标记 | `case-without-provenance` | 否 |
| 人的批准绑定旧评估，或决定是 reject、defer、covered 但 PR 提交了内容 | `approval-stale`（标记输出 pending）；`decision-does-not-authorize` | 否 |
| 写入中断 | 旧文件仍完整；临时文件被忽略 | 否 |
| 两个 PR 并发 | 后合入方基线前进导致复核报过期；新 case 撞字面量报可能重复 | 不保证语义判重 |
| 离线 | 非权威快照；`promotion_gate` 阻塞 `stale-snapshot` | 否 |
| 旧状态文件损坏 | 备份成 `.corrupt-<时间>` 后重写 | 否：报告里提示 |
| covered 的 postmortem 还没转正 | 收尾脚本拦下，不写 `archived`、不出队，退出 2 | 否 |
| 来源记录文件不在本机 | 收尾脚本只出队、不写状态，记 `trace-missing` | 否：报告与日志写明 |

不能保证的事：语义等价的召回率、不同措辞或缺失证据下的判断正确率、所有并发草稿都被看见、agent 结论等同于事实。`assessment_id` 是内容与来源的声明，不是签名：有写权限的人可以复制一份真实评估的 id，它防的是「内容或证据与声明不一致」，不是伪造声明。子 agent 的「只读」是提示词与流程约束，不是沙箱；真正的写权限由 harness 与平台控制。合成样例上的数字不是生产准确率。

## 5 现状

### 5.1 已落地

原型已在仓库内实现并测试；生产部署还依赖平台侧的必需检查与基线最新（见本节 5.2）。

- 快照、候选、记录、决定、状态、合入前复核、收尾、清理八个脚本；确定性测试覆盖快照与离线、索引重建、候选有界、记录校验与聚合、幂等、损坏恢复、人决定保留、过期检测、并发 PR、两个独立 inbox、端到端「A 先合入、B 过期再重跑」、收尾的证据前置与出队。
- 验证命令：`python3 -m unittest tests.test_groom_snapshot tests.test_groom_candidates tests.test_groom_record tests.test_groom_status tests.test_groom_recheck tests.test_groom_workflow tests.test_groom_binding tests.test_groom_close_draft`。

### 5.2 蓝图

- 平台侧若要把复核变成强制：在 ruleset 里增加一个跑 `groom_recheck.py` 的检查并设为必需，同时要求基线最新；本仓不新增 CI job。
- 打开 PR 候选（`pr_radar` 类能力）：当前只比 main，在途 PR 的 case 仍可能互相撞车。
- 在真实（已脱敏）case 上做离线验证，再决定阈值与是否需要独立复核 agent；合并队列作为吞吐优化，不作为正确性前提。

### 5.3 已否决

- 用内容指纹或规范化结构作为永久 Case ID：研究记录里的误拆分与误合并反例说明它不能单独承担语义身份。
- 自动合并、自动升格、自动删草稿：与「agent 建议不是事实」冲突。
- 把 agent 的 `covered` 直接写成人决定：人机分家是这条流程的安全阀。

## 6 代码与文档入口

| 入口 | 作用 |
|---|---|
| `scripts/groom_snapshot.py` | 列出远端名、建快照、抓取、worktree、索引校验 |
| `scripts/groom_candidates.py` | 候选打分与有界工作单 |
| `scripts/groom_record.py` | 证据一致性校验、保守聚合、来源标记 |
| `scripts/groom_decide.py` | 写人决定 |
| `scripts/groom_status.py` | 状态与新鲜度 |
| `scripts/groom_recheck.py` | PR 合入前复核 |
| `scripts/groom_close_draft.py` | 终态决定的收尾：记录回写加草稿出队 |
| `scripts/groom_cleanup.py` | 合入后的快照与评估文件清理 |
| `scripts/sediment_undo.py` | 撤销一次不成立的沉淀（支持批量） |
| `scripts/groom_common.py` | 草稿发现、状态读写、git 工具 |
| `skills/knowledge-groom/SKILL.md` | 流程与判断规则 |
| `skills/knowledge-groom/references/subagent-prompts.md` | 子 agent 提示词与返回格式 |

## 7 外部参考

- GitHub 的 required status checks 与「Require branches to be up to date before merging」是这里说的平台侧前提；本仓只提供检查脚本，不提供平台强制。
- 语义去重的替代做法（向量检索、结构指纹、规则规范化）各有代价；本仓的检索仍走词法或结构，不做向量检索（见 [ADR-0002](../adr/0002-retrieval-no-rag-lightweight-index.md)）。本机制把语义判断放在 agent 侧，是为了在证据不足时能弃权，而不是用相似度阈值冒充等价。
