# Git 工作流：审核、门控与合入

目标是在不预设具体 owner 的前提下，让门控、审核、分发与合入的闭环可以运转。全部机制用 git 原生能力承载：分支保护、PR、CODEOWNERS、标签、CI，并可移植到不同平台（GitHub / GitLab / GitCode 的对应关系见文末）。

需要说明各道闸门的实际强度。git 能够硬性强制的是三件事：谁审批过、YAML 是否合法、索引是否新鲜。语义层面的闸门（脱敏是否彻底、root cause 是否正确、severity 标注是否恰当）只能依靠流程约定与人工抽查。下表对每道闸门标注强度，避免把约定误认为已被强制。

## 分支模型

- `main` 受保护、禁止直接 push：所有知识库变更（包括 groom 的周批次）都走 PR。
- 冷启动或单人阶段可以先不开分支保护，机制先行、权限后收紧；kb-checks CI 从第一天就启用，它是唯一不依赖人的硬门。

## 多 agent / 多 session 并行（worktree 约束）

多个 agent/session 并发在同一仓库工作时，**共享检出目录是冲突根源**：未提交改动会随 `git checkout` 流动到其他分支；`ingest-state.json`、`metrics/timeline.yaml`、`knowledge/_index.yaml`、`postmortems/inbox/` 等共享状态会被互相覆盖或误删。git 提供 `worktree` 做工作区级隔离，**每个 agent/session 必须使用独立 worktree**：

```bash
# 每个 session 分配独立 worktree（检出自己的 kb/* 分支），不要在共享检出目录里干活
git worktree add ../ascend-sleuth-s<session> <自己的 kb/* 分支>
# 工作合入后清理
git worktree remove ../ascend-sleuth-s<session>
```

约束（机制边界 + 协作约定）：

1. **工作区隔离**：worktree 隔离工作区文件 / index / HEAD / 未提交改动，各 session 在自己 worktree 内任意修改，不污染他人检出（`git checkout` 携带未提交改动的问题从根上消失）。
2. **共享面（worktree 不隔离）**：`.git` 对象库与 refs 全局共享，分支名 `kb/<用途>` 必须全局唯一；共享状态文件（ingest-state.json 的 processed、metrics/timeline.yaml、index 分片、postmortems/inbox/）在各 worktree 是各自分支的副本，合流时**显式解决 merge 冲突**：processed 数组合并、索引分片重跑一次生成器即可（它是生成物，不必逐行解）、inbox 清空先确认无他人草稿。
3. **未进 git 的运行时件：一律锚到主检出**（别再假设"未跟踪文件会被 git 拦住"）。实测（git 2.39）：`.gitignore` 覆盖的未跟踪件**不计入 dirty**，`git worktree remove` **不报错、也不需要 `--force`**，随 worktree **静默**一并删掉；只有"已跟踪且被修改"的文件才会被拦下并提示 `--force`。所以：
   - **跨 session 复用的记录**（`metrics/skill-exec-log.yaml`、`metrics/ev-measure-log.yaml`、`src-code/` 源码缓存、`traces/`、`postmortems/inbox/` 草稿、`proposals/{sessions,tasks,reviews,experiments}/`）路径一律解析到**主检出**——`scripts/exec_log_path.py` 是唯一事实源，agent 侧入口是 **`python3 scripts/shared_dir.py <名字>`**（打印绝对路径；`--list` 看全部）。**写侧别用相对路径**：写进 worktree 的记录，主检出那一份读者（诊断面板 / 周批指标 / `settle_trace_feedback.py` 等结算脚本）看不到，而且 worktree 一清就没了——"记录了但没人看得见"与"读不到就当成没有"会同时发生。
   - 读 `traces/` 的脚本（`trace_metrics.py` / `settle_trace_feedback.py` / `component_tally.py` / `replay_trace.py` / `metrics_snapshot.py`）默认就取主检出那一份，不必手工指定。
   - **仍是检出内、会随 worktree 静默消失的**只剩 dev 期产物：`.s2-replay/`、`.ixn-replay/`、`.flow-replay/`、`.auto-fetch/`、`eval-reports/`（不是知识记录；要留就在收工前挪出来）。
4. **串行操作**：涉及 ingest-state.json 的 fetch / `--mark-imported` / 游标更新必须串行（read-modify-write 无锁，并发写互相覆盖）；groom 清空 inbox 前先确认无其他 session 未提交草稿。
5. **开工纪律**：`git fetch origin` 确认最新 → 确认自己在自己的 worktree 与分支 → 收工前提交或 stash 清空工作区，避免未提交改动滞留共享检出。

## 生成物与源：多人同时提交不撞的规则

判据只有一条：**这个文件的内容里有没有"会变的数字"，以及它是不是一层平铺的追加型结构**。

- 有数字（条数 / 容量 / 日期）→ 数字一进 git，两人并发合并时要么撞同一行、要么漂移成错的数。
  **所以生成物里不写数字**：要数字就现算（`python3 scripts/index_counts.py`）。
- 一层平铺的追加型结构（每条 case 一段、每个性质一段）→ 可以配 `merge=union`：两边新增的都留住。
- 嵌套结构（索引就是：namespaces → ns → category → 条目）→ **不能** union（实测会把 YAML 拼坏），
  同一个格子的两人并发仍会撞一次，解决动作是重跑生成器。

| 文件 | 谁提交 | 提交前跑什么 | 门（PR 与主干同一条） |
|---|---|---|---|
| case 本体 `knowledge/<ns>/<cat>/*.yaml` | 人（PR） | — | `verify_case_draft.py --all` |
| 索引分片 + 总表 `knowledge/_index/…` | 人（PR） | `python3 scripts/build_index.py` | `build_index.py --check`（覆盖检查：每条 case 的行都在、与内容对得上） |
| 路由性质文件 `triage-tree.d/<性质>.yaml` | 人（PR） | — | `build_triage_tree.py --check-sources`（性质 id 唯一 / category 合法 / ≤30 性质 / 一性质一文件 / `<side>` 占位在 / 源清单无遗漏） |
| 路由协议与清单 `triage-tree.d/00-protocol.md` | 人（PR） | — | 同上（`sources:` 决定拼接顺序与归属，`sides:` 是侧层的唯一写点） |
| 路由聚合 `triage-tree.yaml` | 人（PR） | `python3 scripts/build_triage_tree.py` | `build_triage_tree.py --check-coverage`（源里每条症状组、侧层每个字段都在聚合里） |

**合并完没有任何收尾动作**——不需要谁再跑一次命令。这是"生成物里不写数字 + 路由层可 union +
门改成覆盖检查"三件事一起买来的：

- 覆盖检查问的是"条目都在吗、与内容对得上吗"，不问"是否与重新生成一遍逐字节相同"。
  逐字节会把 union 合并出来的、内容正确的文件判红，于是又逼人跑一遍命令——收益就还回去了。
- 想归一化（顺序/注释回到生成器口径）随时跑一次生成器，那是可选的：
  `build_index.py --check --canonical` 与 `build_triage_tree.py --check` 是那两个自检，**不作门**。

撞车了怎么办——按文件类型处理，不需要判断"留哪份"：

| 冲突文件 | 动作 |
|---|---|
| `triage-tree.d/<性质>.yaml`、`triage-tree.d/00-protocol.md`、`triage-tree.yaml` | 通常不会冲突（配了 `merge=union`）。若真出现冲突标记：把两份都留下、删掉三行标记，再跑一次聚合。 |
| 索引分片 / 总表（嵌套结构，故意没配 union） | **不要逐行解**（实测：那些冲突段是交错在条目块内部的，删标记会拼出非法 YAML）。正确动作是三行：`git checkout --theirs -- knowledge/_index.yaml knowledge/_index` → `python3 scripts/build_index.py` → `git add` 后提交。约 5 秒、无判断——两边都不接受，重生成一份对的。 |
| case 本体 | 真正需要人判断的只剩这里（同一 case 两人改）——按内容合。 |

**建议在平台上开启"合并前分支必须最新到主干"**（设置项名字各平台不同）：这样索引冲突会落在**提交者本地**——他有检出、能跑生成器；不开启的话，冲突会落到**合并者的网页冲突编辑器**上，而网页上跑不了生成器，只能先选一边落下、再去本地重生成一次（多一次往返，且主干会短暂红）。

为什么这么做（可复跑的实验在 `tests/test_concurrent_submit.py`，`python3 tests/test_concurrent_submit.py`
会打印一张对比表）：三人并发、同一个框架时，改前撞在总表 + 分片 + 路由单文件上，其中路由文件的冲突
**要人判断留哪份**（判断错就静默少一条路由词）；改后判断冲突为 0。三人各改不同框架（常见形态）时，
改后一次都不撞。同一个格子的并发仍会撞索引文件，但那一类冲突的动作是**重跑一条命令**（机械、无判断）。

## 部署形态

两种形态都支持，inbox、groom、索引与 CI 机制在两种形态下的工作方式相同：

| 模式 | 形态 | 适用场景 |
|---|---|---|
| 集中式 | 训练与推理团队共用一个仓库，`CODEOWNERS` 按命名空间划分审批权 | 团队规模小，问题域重叠多 |
| 框架式（fork） | 团队 fork 本仓库，自行积累或导入知识；方法论与机制账本随上游同步，少数共享文件两边都写 | 团队自治，知识含敏感数据 |

同步方式为 `git fetch upstream && git merge upstream/main`。对框架的改进以 PR 形式反提上游；知识内容不回流，脱敏后的构造示例除外。

### 目录归属（按"fork 会不会写"分档）

同步时要回答的问题只有一个：这个冲突按哪条规则处理。所以分档判据是 fork 会不会写它。

**只接收**（fork 不写，改进以 PR 反提上游）：`skills/ scripts/ docs/ examples/ tests/ dsh-plugins/`、`.github/workflows/ .github/PULL_REQUEST_TEMPLATE/`、根人读文档（`README.md CLAUDE.md AGENTS.md CONTEXT.md LICENSE CODEOWNERS.example diagnosis_state.yaml.example`）、机制账本（`proposals/ideas/ proposals/gates.yaml proposals/component-aliases.yaml`）、评测夹具与账本（`eval/holdout.yaml eval/flow/ eval/ixn-arena/ eval/s2/`）。
出现冲突说明 fork 改过只接收面：还原上游那份，把改动挪进反提 PR。

**只在本仓**（上游不合并）：`knowledge/ postmortems/`（含 `inbox/` 草稿）、`eval/golden/` 里的真实夹具、`traces/`。

**两边都写**（正常合并）：`triage-tree.d/`、`references/`、`metrics/gates.yaml`、`trace-status.yaml`。
这四个路径 fork 会因为自己的知识面、阈值与词表去改，上游也在改。冲突按文件类型处理：追加型（`references/` 下的家族表、`trace-status.yaml` 的词表、`triage-tree.d/` 的性质文件——后者还配了 `merge=union`，两边新增的词自动都留住）两边都保留；键控结构（性质文件与 `00-protocol.md` 里 `id` / `category` / `sources:` 这类字段）按语义合，不机械取一边。

**每部署一份**（不参与合并）：`metrics/timeline.d/`、`metrics/timeline.yaml`、`ingest-state.json`、`reference-ingest-state.json`、`eval/scorecard.yaml`、`.github/CODEOWNERS`（owner 名单各仓不同）。
冲突时保留本仓那份。同期名的指标文件也按本仓处理——两份部署的读数混进一条趋势线本身不成立。

**生成物**（重新生成，不逐行解）：`knowledge/_index.yaml` 与 `knowledge/_index/`、`triage-tree.yaml`、`references/_summary-index.yaml`、`references/_procedure-index.yaml` 与 `references/_procedure-index/`。

本节没列到的路径按只接收处理；要写它就先在本节加一行。

**仍混装两边内容的文件**（靠合并策略只能缓解，按来源拆文件才根治）：`ingest-state.json` 一个文件装所有来源的游标、`eval/scorecard.yaml` 一个账本装两边夹具的哈希、`metrics/timeline.d/` 按自然周命名。这三件属机制改动，等第二个部署真实摄取数据时再做。

### fork 侧不产 EV 卡

idea 卡（`proposals/ideas/`）是机制账本，归上游。两条原因：

- 卡号在本地递增分配（`scripts/ev_proposal.py` 只扫自己检出里的卡），两个仓库各产各的必然撞号；撞号后同一个文件路径两边内容不同，冲突无法机械解决；
- 上游 `docs/mechanism/`、`docs/plan/` 里引用的卡号会随合并落进 fork，在那里指向另一张卡——这种错不报错。

fork 侧的机制缺口写进 MR 描述或 issue，由维护者拿到上游产卡。内容产出（补 case、补词条、扩错误码家族、从 case 归纳 reference）不产卡，产卡范围见 `skills/evolve-check/SKILL.md`。fork 长期无法访问上游、又确实需要本地决策档案时，用与上游不重叠的号段或前缀，并让该目录归 fork 独占——复用 `proposals/ideas/` 的号段会让撞号问题原样保留。

### fork 侧首次同步的检查单

1. `git fetch upstream && git merge upstream/main`，合并后 `git status`：冲突应只出现在「两边都写」那四个路径上；
2. 只接收面出现冲突，说明 fork 改过它——还原上游那份，改动挪进反提 PR；
3. 「每部署一份」保留本仓那份，「生成物」重新生成，都不逐行解；
4. `python3 scripts/build_index.py --check` 与 `python3 scripts/verify_proposals.py --check` 应绿。

## inbox 条目状态机与标签集

```
draft(inbox/) ─► triaged(三分类标签) ─► reviewed(人审) ─► merged(升格/转正)
                                          └► rejected(关闭，留痕)
```

| 标签 | 打在哪 | 含义 |
|---|---|---|
| `kb/new-pattern` | inbox 条目 / PR | 预分诊：新根因，建议升格 Tier 2 |
| `kb/variant` | 同上 | 预分诊：已有 case 的变体，建议并入（扩 compat） |
| `kb/covered` | 同上 | 预分诊：已被覆盖，仅 postmortem 转正 Tier 3 |
| `kb/needs-structurer-review` | 条目 | 语义或格式可疑（校验失败） |
| `kb/needs-human-review` | 条目 | 语义不明 |
| `kb/high-risk` | PR | 高风险变更，需双签（见下） |
| `kb/groom-report` | issue | 周 groom 变更摘要（通知与留档载体） |
| `kb/stale` | issue / 条目 | inbox 停留超过两周，标红催办 |

## 门控映射表

| 闸门 | 机制 | 强度 |
|---|---|---|
| YAML 语法 + 索引新鲜度 | CI：`scripts/build_index.py --check`（顺带解析全部 case YAML） | 硬（红即挡 merge） |
| 命名空间变更审批 | `CODEOWNERS` + 分支保护 required review | 硬 |
| 高风险双签 | `kb/high-risk` 标签 + CODEOWNERS 双组路径（每组至少一人批） | 半硬（"恰好两个 approval"需人核验，见下） |
| 脱敏 / severity 纪律 | to-postmortem 流程 + groom 周批审抽查 | 约定 |
| eval 回归（改 skill 时） | 按 [eval.md](eval.md) 分级手动 replay；**触及输出契约/交互形态时另出盲辨对照**（同问题新旧输出各一份、交不知情者判）；replay 脚本化后并入 CI（属 roadmap 里「fixture replay 半自动化」一项） | 约定 → 半硬 |
| eval 观测不陈旧 | CI：`scripts/eval_scorecard.py --check`（`eval/scorecard.yaml` 记"上次回放观测到什么"；夹具字节哈希变了而账本没重建即红） | 硬（夹具哈希）/ 软（目标 case 内容变了只进「待复核」，不挡 merge）；**不判准确率**——命中率仍要 agent 跑回放 |
| 口径脚本算得对 | CI：`python3 -m unittest discover tests`（`build_index` / `trace_metrics` / `settle_trace_feedback` / `build_timeline` 的口径与边界） | 硬（红即挡 merge）；"断言是否真打在口径上"仍是约定 |
| EV 卡预测可复现 | CI：`scripts/verify_proposals.py --check`（`predicted_effect.measure` 必须有命令 + 期望，或如实声明不可度量） | 硬（结构）/ 约定（命令是否有意义） |
| 面板契约（渲染 / 文案 / 数据口径） | CI：`panel-checks` job 跑 `scripts/check_panel_tokens.py` + `scripts/panel_render_check.js`（触发路径含 `dsh-plugins/**`） | 硬（红即挡 merge）；"判据是否真在测那件事"仍是约定 |
| 对照集不被改动者削弱 | CI：`scripts/holdout.py --check`（封存夹具按哈希钉住）+ `holdout-change` 标签闸门；CODEOWNERS 保护 `eval/holdout.yaml` | 硬（哈希）/ 半硬（谁有权 reseal——CODEOWNERS 落实前不是人把关） |
| 回放量尺的按侧覆盖 | CI：`scripts/eval_side_coverage.py --check --require-side training --require-side inference`（路由分侧后，侧是量尺单位；训练侧曾在 22 条 case 上 0 条夹具） | 硬，但**只保单侧量尺不归零**（某一侧一条真实夹具都不剩即红）。**格级缺口（某个 (侧 × 性质) 格子有 case 没夹具）是报告不是门**——把 `--check` 去掉 `--require-side` 就能变成格级门，代价是"新 case 落到尚无夹具的格子会被拦下"，与"补夹具需要真实来源、凭空造不出来"的政策冲突，故不做。**它钉的是覆盖不是保护强度**：实测 26 条夹具里 16 条的输入对性质正则零命中（靠语义兜底），改坏词表它们照样过；哪几条真钉着词表用 `--nature-evidence` 现算现看 |

## 评审把手（reviewer 怎么判"该不该合"）

判据的独立性只有一条标准：**改动者不能靠"写文字"通过它**。PR 里的命题（success_criteria 达成、无回归、断言全过）多由制造改动的同一过程写成，而 CI 检查的是内部自洽（索引新鲜度、YAML 合法性、模板结构齐全）——因此"CI 绿 + 测试过"对"该不该合"的信息量接近于零，reviewer 会被逼在"开全文"与"直接批"之间二选一（`mechanism/execution.md` §7 把这一失效形态命名为"橡皮图章"）。

改动侧义务：EV 卡带 `predicted_effect.measure`。reviewer 侧动作：

```
python3 scripts/ev_measure.py <card-id> --run    # 打印判据命令 + 期望，执行并比对
python3 scripts/ev_measure.py --audit            # 全库盘点：可复现 / 声明不可度量 / 缺口 / 存量豁免
```

退出码三态：`0` 符合预测 / `1` 预测被证伪 / `2` 无法判定（存量卡无口径、声明不可度量、卡不存在）——刻意分开，避免"判不了"被读成"验证失败"。

**强度如实标注（原则十）**：本把手证明**效果**（改动是否产生了它声称的变化），不证明**价值**（该变化是否值得做）；"命令是否真在测那件事"机器判不了，属**约定**强度，靠人审抽查。存量卡（`verify_proposals.py` 的 `MEASURE_CUTOVER` 之前创建）豁免强制要求——补写不恢复当时的判断，只造事后叙述；缺口由 `--audit` 如实报出。

### 独立预核（提交前，由另一次会话做）

PR body 里的「Agent 预核意见」由**与作者不同的会话**产出：另起一个 session，或派一个 subagent。
本仓常见的 subagent 与作者同父会话，它看不到作者的推理，但这不是外部第三方独立，别读成担保。
作者自评不算：PR #282 的预核段由作者填写，独立预核在同一分支上又抓到 3 条（1 条阻断级）。
差别不在模型，在两件事：**另一次会话**，以及**被要求构造反例并跑出来**。

**不重复跑 CI 已经跑的**：PR 上的门以 `.github/workflows/` 下两个工作流为准（`kb-checks.yml` 与
`pr-template.yml`），本文不抄命令清单，理由同 `CLAUDE.md`（抄了会腐烂且不报错）。
预核只做这两类门判不了的事。

| 改动类型 | 预核查什么 | 要跑反例吗 | 耗时 |
|---|---|---|---|
| 文档与措辞（`skills/**`、`docs/**`、`README`、`CLAUDE.md`） | ① 对照 `docs/spec/writing-norms.md` §1 的共用条目逐条过改动段落，报命中项与行号；② 文中每个**可验证声明**（路径、命令、字段名、代号、数字）逐个核对与实现是否一致；③ 改 skill 正文的另查 `docs/spec/writing-norms.md` §6 的内联要求；④ 新增代号是否登记 `docs/glossary.yaml`、`scope` 是否对 | 不用 | 2 到 3 分钟 |
| 内容（case、reference、路由词） | ① 路由：`python3 scripts/route_check.py <case 文件>` 报出会被哪个分支接住、宽词是否跨分支重复；② `quickly_check.expected` 在输入里的真实报错上跑一次（CI 只查可编译）；③ 事实自洽与查重（与相邻 case 是否同一根因）；④ 脱敏 | 不用，但要真抽查 | 5 分钟 |
| 脚本、机制、生成物、门语义 | ① 对改动的判定逻辑构造反例并跑出来（给命令与结果）；② 检查门本身有没有洞；③ 前几轮的临时件有没有残留；④ 受影响的文档承诺扫一遍 | 必须 | 15 到 30 分钟 |

两条通用要求：

1. 没查出问题也要给覆盖清单（查了什么、跑了什么命令、结果如何）。否则没查与没问题在 PR 上长得一样。
2. 每条结论带 `文件:行`、一条可复跑命令、实测结果。严重度写中文分级（阻断级、重要级、建议级），
   不要用 `P0`/`P1`：那两个在 `docs/glossary.yaml` 里已是优先级与流程事项族的代号，撞了会歧义。
   结论行给 `MERGE_READY: yes/no`。

**为什么不进 CI**：预核是判断性工作（非确定性、无机械判据），一旦成门就会变成「CI 能过的仪式」；它也不替代双签。
CI 侧只有机械切片：模板结构（`pr-template.yml`）、docs 名单与未登记文档（`docs-index`）、skill 自包含（`skill-self-contained`）。
代号未登记与越界的 `python3 scripts/render_review_summary.py --scan` 是手工命令，同样不进 CI（`writing-norms.md` §8）。

**抽审纪律（约定，同"渐进审序"的用意）**：reviewer 每轮**自行随机点一处**核对，**不从改动者列的 spot-check 清单里挑**。不指望抓全，目的是让"如实标注"成为改动侧的占优策略。

## PR 模板

`.github/PULL_REQUEST_TEMPLATE/` 下按变更对象分五类（创建 PR 时选择，或 `?template=` 直链）：**knowledge_intake**（新知识升格：预分诊+证据+脱敏自查）、**knowledge_modification**（改 expected/fix/compat 等高风险字段：触发条款+依据+双签）、**reference**（references/ 词条：导入/转正/修订，含聚类检查与 verification 声明）、**methodology**（skill/脚本/文档：原则追溯+golden 回归对照）、**structure**（triage-tree/namespace：数据依据+迁移完整性检查单）。模板目录属上游方法论，随 fork 同步。

**模板选择与结构约束**：agent 提交 PR 时模板选择由产出流程决定（to-postmortem/groom/to-reference 产出物自带对应模板类型），不靠提交时自觉选。`pr-template` CI（每次 PR 都跑）校验"用了正确模板 + 关键结构区块在"，缺失即红（如 knowledge 类缺脱敏自查、高风险类缺双签）。**Agent 预核意见区块是可选增值，CI 不校验是否填写**，agent 提交链路未打通的内网/手动提交者可留空，不被硬卡；有则给 reviewer 提供基于事实的独立意见供对齐判断（不替代人审）。模板里的"机器可填"字段当前部分自动生成（fixture 候选的 agent_review、预分诊结论），完整自动生成在 roadmap 待定池（PR 描述机器层生成）。

**frontmatter 与 body 起点**：GitHub 不解析 PR 模板的 YAML frontmatter（name/about/labels 是 issue 模板语法），原样带入会渲染成正文顶部粗体块。模板文件内的元数据因此放在 HTML 注释里（供人读与平台迁移适配）；创建 PR（`?template=` 或 agent `--body-file`）时正文从首个 `## ` 区块开始，注释块可留可删（渲染不可见，CI 只查 `## ` 区块）。`labels` 不随模板自动应用，需 `gh pr create --label` 显式打（如 `kb/high-risk`）。

## 人读性与代号约定（审读面 / 存储面分离）

仓库产物（docs、EV 卡、SKILL.md、case、PR body）混用多套设计层代号（L/S/A/E/M/O/P/G/T/EV/Phase 等系列）。机器读得动，**人不该靠记忆读**——本约定把"人读视图"与"词法存储"分开，代号体系本身保持词法（供脚本/CI/面板直读），人读时走解码。

规则：

1. **机器字段保持词法**：YAML 枚举字段（`layer`/`status`/`method`/`authorization` 等）不做中文替换——它们是脚本与 CI 的契约；
2. **人读 prose 首次出现即解码**：docs 论证文字、EV 卡 prose 字段、PR body、批审摘要、报告里，代号第一次出现写"含义（代号）"或"代号〔含义〕"，之后才允许裸用；高危字母（E/T/G/EV/Phase，及 A/M/O/P+数字）与落地 Phase 系列**裸用即歧义**，首次出现必解码；
3. **审读面优先**：批量审 / PR 审读用解码渲染（`scripts/render_review_summary.py --card/--diff/--scan`，词表 `docs/glossary.yaml`），**源文件不变**——人审读渲染视图，不裸读 diff；渲染出的未登记代号告警即"先登记再使用"的自我约束；
4. **新增代号先登记，并同时定它的生存范围**：`docs/glossary.yaml`（机器数据，唯一权威）里每条带 `scope` 字段——`["*"]` 只给领域语汇（分层 L1–L3、反馈通道 S1–S3、平台与 skill 名）；**记账号（roadmap 事项 A/E/M/O/P、治理缺口 G、触发信号 T、落地阶段 Phase）只在各自的计划文档里裸用**，机制文档 / PR body / EV 卡 prose 要引用就写中文含义。旧做法要求"在 docs/evolution.md 顶部指代速查表补一行"——那张表已删（它把术语表变成了代号登记处，且把"起新代号"从**需要理由**变成**需要登记**）；
5. **越界用途可查**：`python3 scripts/render_review_summary.py --scan docs/ README.md CONTEXT.md`（可传目录）会报三类——未登记代号、越界用途（新人可见面单列并优先清理，其余按文件计数可增量清理）、以及词表冲突。`docs/adr/` 与 `proposals/` 是只追加的档案，豁免越界检查（不追溯改历史）；
6. **同形冲突登记而不改名**：`A1/A2/A3` 同时是设计公理、roadmap 事项与平台代号前缀，`P0` 同时是优先级与（易混的）流程事项族——这类冲突在词表里各自登记、用 `scope` 消歧，**不靠改历史编号**（改编号会打烂只追加档案里的引用）。新增代号前先查是否已有同形；
7. **跨文档引用不写裸小节号**：引用别处的小节写 `文件名 §N` 或直接写小节标题，**不写裸 `§N`**（读者不知道是哪篇；且小节号会随文档重排失效——仓库里现存约 100 处这类引用，属历史欠账，见 EV-2026-052 残留）。**不硬门化**：无"复发 ≥2 次"的证据，不满足检查准入三条件；
8. **不进 CI**：prose 可读性是判断性规范（检查准入三条件不满足），由 PR 人读性自查（methodology 模板试点）+ review spot-check 保证，不硬门化。**唯一例外是机械可判的部分**——名单/数字是否与 `docs/_manifest.yaml` 一致、`docs/` 有无未登记文档，由 `build_docs_index.py --check` 硬门（那是"生成物与清单一致性"，不是可读性判断）。

## Skill 自包含边界（SKILL.md 与 docs/ 的引用关系）

`skills/<name>/SKILL.md` 必须**自包含到"没有 docs/ 也能正确执行"**：执行必需的决策参数（阈值、cap、映射、检查单）直接内联进 SKILL.md 或其 `references/`；`docs/` 是**可选论证层**，只承载"为什么这样设计"的推导，引用时标注"可选论证层"（如"论证见 docs/adr/0004，可选论证层，上述数值为执行值"）。原因：`docs/` 是仓库根级目录，依赖安装方式（`-g` 模式带全仓库，独立 skill 分发不带）；执行参数若只放在 docs 里，未装 docs 的 agent 无法正确执行。引用三分类：运行时参数 → 内联；背景论证 → docs + 可选标注；指标/产物数据源 → 保留为知识索引（如 metrics.md）。新写 skill 或修改时，不得新增"执行必需的 docs 依赖"。

## 高风险双签

高风险清单与 `skills/knowledge-groom/SKILL.md` 保持一致：新建 `common/` 权威记录、修改 `expected`、修改 `fix_on_mismatch`、修改 `compat` 区间、手动覆盖 `confidence.score`。

落地步骤：

1. groom 在变更 PR 上打 `kb/high-risk` 标签，PR 描述列出触发的条款；
2. `CODEOWNERS` 将 `knowledge/common/` 与 `triage-tree.d/` 指向两组评审人（领域 owner 组与体系维护人组），配合分支保护的 required review，使两组各至少一人批准；
3. 平台限制：GitHub 与 GitLab 原生不强制"批准者来自不同小组"。CODEOWNERS 的多组配置可以逼近这一要求，最终的数量核验写入 groom-report 检查单，由开 PR 的人自查勾选。

owner 尚未确定时，`CODEOWNERS.example` 保留 TODO 占位，CI 与标签流程照常运转；owner 落实后将占位文件复制为 `.github/CODEOWNERS` 并填入真实账号，硬门随即生效。

## 通知机制

- 周 groom 摘要：写入变更 PR 的描述（@ 对应 owner，即时触达），同时开一个打 `kb/groom-report` 标签的 issue 留档，避免重复打扰；
- inbox 积压：groom 摘要中标红；停留超过两周的条目可以开 `kb/stale` issue 催办；
- `feedback_pending` 不走 git：它记录在 `traces/*.yaml` 中，可能包含客户信息，已被 `.gitignore` 挡在仓库之外，通知依靠**续接启动时的扫描与面板待办面**。这是刻意设计，不要把它搬进 issue。注意**新诊断的开屏不追历史债**——第一屏只服务新问题，逐单追问积压的 pending 是审讯不是诊断（口径见 `skills/resume-diagnosis`）。

## CI

`.github/workflows/kb-checks.yml` 已提供，**job 清单以该文件为准**（数量与名字随机制增长而变，
不在本文抄一份——抄了就会腐烂且不报错）。本地等价复跑的唯一可靠方式是逐条读那里的 `run:`；
更重的端到端演练见 `python3 scripts/rehearse_evolve_loop.py`（它会把 kb-checks 的每条命令逐条复跑，
但**不走 pr-template 那条**）。至少要跑的一条起手式：

```bash
pip install pyyaml
python3 scripts/build_index.py --check
```

两条命令在任何平台都能等价配置（GitLab CI 的 `.gitlab-ci.yml`、GitCode 流水线同理）。索引过期意味着变更不完整，比如修改了 case 却忘记重建索引，CI 直接置红。

## 平台对应表

| 机制 | GitHub | GitLab | GitCode |
|---|---|---|---|
| 分支保护 | branch protection rule | protected branches | 保护分支 |
| 属主审批 | CODEOWNERS + require review | approval rules / CODEOWNERS | 评审规则 |
| 标签 | labels | labels | 标签 |
| CI | Actions | GitLab CI | 流水线 |
