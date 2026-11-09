# Git 工作流：审核、门控与合入

目标是在不预设具体 owner 的前提下，让门控、审核、分发与合入的闭环可以运转。全部机制用 git 原生能力承载：分支保护、PR、CODEOWNERS、标签、CI，并可移植到不同平台（GitHub / GitLab / GitCode 的对应关系见「平台对应表」）。
本文覆盖分支模型、worktree 约束、生成物规则、部署形态、门控映射、评审把手与 CI。

读者是提交或评审知识库改动的人。不碰仓库改动链路的人不必读。

## 1 做完得到什么

改动合入 `main`，并且过了「门控映射表」里与它相关的门。知识库变更与 groom 的周批次都走 PR 合入。

## 2 前置条件

### 分支模型

- `main` 应开启保护、禁止直接 push；当前仓库尚未开启（冷启动可先不开，见下条）。所有知识库变更（包括 groom 的周批次）都走 PR。**开启保护后，把 `DEPLOY_KEY` 对应的 deploy key 加进 ruleset 的 bypass 列表**；`GITHUB_TOKEN` 不能直接绕过。没配好时生成物只能靠人工重建。
- 冷启动或单人阶段可先不开保护；kb-checks CI 从第一天就启用，它是唯一不依赖人的硬门。

### 多 agent 并行（worktree 约束）

多个 agent/session 并发在同一仓库工作时，共享检出目录是冲突根源：未提交改动会随 `git checkout` 流动到其他分支；`ingest-state.json`、`metrics/timeline.yaml`、`knowledge/_index.yaml`、`postmortems/inbox/` 等共享状态会被互相覆盖或误删。git 提供 `worktree` 做工作区级隔离，每个 agent/session 必须使用独立 worktree：

```bash
# 每个 session 分配独立 worktree（检出自己的 kb/* 分支），不要在共享检出目录里干活
git worktree add ../ascend-sleuth-s<session> <自己的 kb/* 分支>
# 工作合入后清理
git worktree remove ../ascend-sleuth-s<session>
```

约束（机制边界 + 协作约定）：

1. 工作区隔离：worktree 隔离工作区文件 / index / HEAD / 未提交改动，各 session 在自己 worktree 内任意修改，不污染他人检出（`git checkout` 携带未提交改动的问题从根上消失）。
2. 共享面（worktree 不隔离）：`.git` 对象库与 refs 全局共享，分支名 `kb/<用途>` 必须全局唯一；共享状态文件（ingest-state.json 的 processed、metrics/timeline.yaml、index 分片、postmortems/inbox/）在各 worktree 是各自分支的副本，合流时显式解决 merge 冲突：processed 数组合并、索引分片重跑一次生成器即可（它是生成物，不必逐行解）、inbox 清空先确认无他人草稿。
3. 未进 git 的运行时件：一律锚到主检出（别再假设"未跟踪文件会被 git 拦住"）。实测（git 2.39）：`.gitignore` 覆盖的未跟踪件不计入 dirty，`git worktree remove` 不报错、也不需要 `--force`，随 worktree 静默一并删掉；只有"已跟踪且被修改"的文件才会被拦下并提示 `--force`。所以：
   - 跨 session 复用的记录（`metrics/skill-exec-log.yaml`、`metrics/ev-measure-log.yaml`、`metrics/entry-activity.local/` 本机明细、`src-code/` 源码缓存、`traces/`、`postmortems/inbox/` 草稿、`proposals/{sessions,tasks,reviews,experiments}/`）路径一律解析到主检出——`scripts/exec_log_path.py` 是唯一事实源，agent 侧入口是 `python3 scripts/shared_dir.py <名字>`（打印绝对路径；`--list` 看全部）。写侧别用相对路径：写进 worktree 的记录，主检出那一份读者（诊断面板 / 周批指标 / `settle_trace_feedback.py` 等结算脚本）看不到，而且 worktree 一清就没了——"记录了但没人看得见"与"读不到就当成没有"会同时发生。
   - 读 `traces/` 的脚本（`trace_metrics.py` / `settle_trace_feedback.py` / `component_tally.py` / `replay_trace.py` / `metrics_snapshot.py`）默认就取主检出那一份，不必手工指定。
   - 仍是检出内、会随 worktree 静默消失的只剩 dev 期产物：`.s2-replay/`、`.ixn-replay/`、`.flow-replay/`、`.auto-fetch/`、`eval-reports/`（不是知识记录；要留就在收工前挪出来）。
4. 串行操作：涉及 ingest-state.json 的 fetch / `--mark-imported` / 游标更新必须串行（read-modify-write 无锁，并发写互相覆盖）；groom 清空 inbox 前先确认无其他 session 未提交草稿。
5. 开工纪律：`git fetch origin` 确认最新 → 确认自己在自己的 worktree 与分支 → 收工前提交或 stash 清空工作区，避免未提交改动滞留共享检出。

### 诊断读侧的同步

诊断开单时同步一次知识库：`trace_begin.py` 读 `.local/settings.json` 的 `sync` 段，fetch 远端分支（超时 10 秒）。`sync.enabled` 关掉时这一步跳过，开单不联网。落后时按四条条件试 ff-only 合并（快进合并，不产生合并提交）：

- 当前分支 = 配置 `branch`；
- HEAD 是远端祖先；
- `git status --porcelain -uno` 为空；
- 无进行中 merge / rebase / cherry-pick；
- `sync.auto_merge` 开着（关掉只检查、不合并）。

worktree 与 detached HEAD 不自动合并。worktree 里通常在做提 PR 的分支改动，合入 `main` 会把它带进提交。

续接只 fetch、不合并：诊断正在进行，合并会改当前工作区，可能换掉结论所在的那一版。要看远端有没有合入这单用过的 case，用续接里的漂移检查（`kb_drift.py`，它先让 `kb_sync.py` fetch 一次）或 `python3 scripts/kb_sync.py --show`（只读，不联网）。

同源校验比较 host 与 path：`git remote get-url <sync.remote>` 要与归属仓（`identity.remote`，默认 `origin`）一致。`--show` 打出「归属仓 <名字>（<URL>）· 解析：是 / 否 · 同源：是 / 否」。

不同源时脚本拦住合并：按提示核对 `sync.remote` 后再用。写目标（提 PR）不做这项校验。

归属仓可在知识库面板或 `python3 scripts/pr_status.py --set-identity --remote <名字>` 配置。显式配置却在本机解析不到时，同样只 fetch、不合并（reason `identity-unresolved`）。默认 `origin` 在本机不存在时不拦，避免单远端检出因此无法合并。

同步源与提 PR 目标是两件事：`sync` 决定诊断与 groom 读哪份知识，`target` 决定草稿 PR 提到哪个远端分支。groom 的新鲜度按评估记录的目标 ref 判；目标未配置时会显式提示，并按归属仓默认分支兜底（默认 `origin/main`，不再静默替换）。配置目标用 `python3 scripts/pr_status.py --set-target --remote <名字> --base <分支>`，面板的目标选择走同一条写入。

同步只补读侧，不替代提交纪律：开工与提交前仍由提交者跑 `git fetch <归属仓>`（默认 `origin`，见「多 agent 并行」第 5 条），保证分支从最新 `main` 开、提交基于最新树。

诊断侧这次 fetch 只保证候选集来自较新的知识库；它不改提交、不推送，也不处理与本地未提交改动的冲突。一次合并同时更新知识与流程：`knowledge/` 在运行时读取立即生效，`skills/` 要下一次会话才重新加载。

配置在 `.local/settings.json`（主检出那一份，`.gitignore` 已挡在 git 外），schema `ascend-sleuth-settings/1`。`sync` 段含 `remote` / `branch` / `enabled` / `auto_merge` / `check_enabled` / `check_minutes`，`identity` 段记归属仓（`{"remote": "origin"}`）。

默认 `origin`、当前分支上游（取不到用 `main`）、同步开、自动合并开；`sync.remote` 未显式配置时跟随归属仓。没有该文件时按默认值同步，groom 回到原有的选源流程（单个远端直接用，多个才问）。

查看配置与状态用 `python3 scripts/kb_sync.py --show`（只读，不联网）；改配置用 `python3 scripts/pr_status.py --set-sync`（`--remote` / `--branch` / `--disable` / `--auto-merge off` / `--check-reminders on|off` / `--check-minutes 分钟`），改归属仓用 `--set-identity --remote <名字>`，不要手改 JSON。

`sync.enabled` 只拦自动路径：开单时 `trace_begin.py` 的自动 fetch 与自动合并看它。后台提醒检查与手动同步不受它影响：提醒检查走 `python3 scripts/kb_sync.py --check`（只 fetch、不合并），手动「立即同步」走 `--merge --force`。`sync.auto_merge` 只管自动路径里的合并；groom 是显式动作，不看 `sync.enabled` 与 `sync.auto_merge`，关掉自动检查后周批仍会 fetch。要让整机不联网，用 `deployment.yaml` 的 `sync.mode: "offline"`。

`sync.check_enabled` 与 `sync.check_minutes` 管后台提醒检查。`check_enabled` 默认 true，关掉后不再检查，也不在诊断状态条提示知识库落后。`check_minutes` 是检查间隔，默认 30 分钟；读侧越界会夹到 5–720，写侧越界拒绝（`E_ARGS`）。
这两个字段不影响开单自动拉取与手动同步。后台检查每 60 秒至多读一次这份设置，按「上次检查开始时刻 + 间隔」判到期；改间隔后最多 60 秒按新值生效。

`--check` 的 fetch 被权限拒绝（DSH 的 workspace-write 受限档位写不进检出）时，脚本退回 `git ls-remote --heads` 只读探测：能判出远端有没有新提交，状态文件按成功记（`reason` 为空、`last_ok_at` 前移）。
有新提交时落后数与改动面未知；没有新提交时落后数为 0、改动面未知。
状态条对应显示「远端有新提交（落后数未知）」，仍给「去同步」「稍后」。
后台检查连续失败 3 次，或失败原因是权限拒绝时，状态条展开态显示「后台检查失败」与失败时间、一句原因，带「去同步」「重试」；成功一次即消失，单次网络失败仍静默。
原因句按失败的检查对象给。后台检查只跑 git（fetch / rev-list），超时说「知识库检查超时」。
只有诊断状态取数（会读 `traces/`）的超时才提 `traces/` 这一可能。

fetch 失败时标 `kb_sync: failed`，原因写进 `kb_sync_reason`。

失败时脚本把 git 原始输出收成一行（`fetch_error`）。取最后一条 fatal / error 行，抹掉 URL 里的账号、密码与查询串里的 token。人读输出与面板都显示这一行。

失败结果缓存在 `.local/kb-sync-state.json`：自动同步在 10 分钟内不重试，避免每次开单都等满 10 秒超时。手动同步（`--force`，面板「立即同步」走这条）跳过窗口立即重试。

离线部署在 `deployment.yaml` 声明 `sync.mode: "offline"`：`--sync` / `--check` / `--merge` 都不联网，`--show` 仍可读本地状态。

### 部署形态

两种形态都支持，inbox、groom、索引与 CI 机制在两种形态下的工作方式相同：

| 模式 | 形态 | 适用场景 |
|---|---|---|
| 集中式 | 训练与推理团队共用一个仓库，`CODEOWNERS` 按命名空间划分审批权 | 团队规模小，问题域重叠多 |
| 框架式（fork） | 团队 fork 本仓库，自行积累或导入知识；方法论与机制账本随上游同步，少数共享文件两边都写 | 团队自治，知识含敏感数据 |

同步方式为 `git fetch upstream && git merge upstream/main`。对框架的改进以 PR 形式反提上游；知识内容不回流，脱敏后的构造示例除外。

### 目录归属（按"fork 会不会写"分档）

同步时要回答的问题只有一个：这个冲突按哪条规则处理。所以分档判据是 fork 会不会写它。

只接收（fork 不写，改进以 PR 反提上游）：`skills/ scripts/ docs/ examples/ tests/ dsh-plugins/`、`.github/workflows/ .github/PULL_REQUEST_TEMPLATE/`、根人读文档（`README.md CLAUDE.md AGENTS.md CONTEXT.md LICENSE CODEOWNERS.example diagnosis_state.yaml.example`）、机制账本（`proposals/ideas/ proposals/gates.yaml proposals/component-aliases.yaml`）、评测夹具与账本（`eval/holdout.yaml eval/flow/ eval/ixn-arena/ eval/s2/`）。
出现冲突说明 fork 改过只接收面：还原上游那份，把改动挪进反提 PR。

只在本仓（上游不合并）：`knowledge/ postmortems/`（含 `inbox/` 草稿）、`eval/golden/` 里的真实夹具、`traces/`。

两边都写（正常合并）：`triage-tree.d/`、`references/`、`metrics/gates.yaml`、`trace-status.yaml`。
这四个路径 fork 会因为自己的知识面、阈值与词表去改，上游也在改。冲突按文件类型处理：追加型（`references/` 下的家族表、`trace-status.yaml` 的词表、`triage-tree.d/` 的性质文件——后者还配了 `merge=union`，两边新增的词自动都留住）两边都保留；键控结构（性质文件与 `00-protocol.md` 里 `id` / `category` / `sources:` 这类字段）按语义合，不机械取一边。

追加型共享源（两边都写，且同一仓内多人同周并发追加）：`metrics/entry-activity.d/`。
它与「两边都写」的差别在追加的粒度：一周一个文件、一行一条自包含记录（每行带 `deployment`），配了 `merge=union`——同周并发时各人各写各的行、两侧都留住，行序不影响结果（前提是「一行一条」，见 `.gitattributes` 的注释）。读端按 `deployment` 分组，一个部署出一份生成物 `metrics/entry-activity/<部署>.yaml`，不跨部署合并：合并两侧的行只解决同部署的并发，两份部署的计数不会被加成一条排行。它与 `metrics/timeline.d/` 一样按自然周命名，一个文件里可能装两个部署的行。

追加型（一信号一文件，跨部署不冲突）：`proposals/signals/`。
文件名是内容哈希，不是序号——两个部署各写各的文件，不会撞号；同名文件表示同一条信号，只追加 `occurrences` 与 `last_seen`。`record-only` 部署用它交接收尾信号，`full` 部署不写这个目录。产卡在上游进行，本目录只放信号、证据与出处。

每部署一份（不参与合并）：`deployment.yaml`、`metrics/timeline.d/`、`metrics/timeline.yaml`、`ingest-state.json`、`reference-ingest-state.json`、`eval/scorecard.yaml`、`.github/CODEOWNERS`（owner 名单各仓不同）。
冲突时保留本仓那份。同期名的指标文件也按本仓处理——两份部署的读数混进一条趋势线本身不成立。
`deployment.yaml` 声明这个部署的演进模式（`evolution.mode`：`full` / `record-only` / `off`），
读端只有 `scripts/evolve_mode.py`；fork 与上游的取值不同，改它属于本仓的部署配置，不是机制改动。

生成物（重新生成，不逐行解）：`knowledge/_index.yaml` 与 `knowledge/_index/`、`triage-tree.yaml`、`references/_summary-index.yaml`、`references/_procedure-index.yaml` 与 `references/_procedure-index/`、`metrics/entry-activity/`（一个部署一份，由 `scripts/build_entry_activity.py` 从源重建）。

本节没列到的路径按只接收处理；要写它就先在本节加一行。`metrics/entry-activity.d/` 属上面新增的「追加型共享源」一档，不适用只接收。

仍混装两边内容的文件（靠合并策略只能缓解，按来源拆文件才根治）：`ingest-state.json` 一个文件装所有来源的游标、`eval/scorecard.yaml` 一个账本装两边夹具的哈希、`metrics/timeline.d/` 按自然周命名。这三件属机制改动，等第二个部署真实摄取数据时再做。

### fork 侧不产 EV 卡

idea 卡（`proposals/ideas/`）是机制账本，归上游。两条原因：

- 卡号在本地递增分配（`scripts/ev_proposal.py` 只扫自己检出里的卡），两个仓库各产各的必然重号；重号后同一个文件路径两边内容不同，冲突无法机械解决；
- 上游 `docs/mechanism/`、`docs/plan/` 里引用的卡号会随合并落进 fork，在那里指向另一张卡——这种错不报错。

fork 负载类型的机制缺口写进 MR 描述或 issue，由维护者拿到上游产卡。内容产出（补 case、补词条、扩错误码家族、从 case 归纳 reference）不产卡，产卡范围见 `skills/evolve-check/SKILL.md`。fork 长期无法访问上游、又确实需要本地决策档案时，用与上游不重叠的号段或前缀，并让该目录归 fork 独占——复用 `proposals/ideas/` 的号段会让重号问题原样保留。

**这条规则由声明承载，不靠记性**：fork 在自己的 `deployment.yaml` 里写 `evolution.mode: record-only`，evolve-check 收尾与深度轮都先读它（`scripts/evolve_mode.py`）。不设时缺省 `full`，也就是上游行为——所以 fork 要做一次显式声明，否则收尾照常产卡。`record-only` 下信号照记、执行记录照落，只把"该产卡"的结论改成写进 MR 描述或 issue。

### Skill 自包含边界（SKILL.md 与 docs/ 的引用关系）

`skills/<name>/SKILL.md` 必须自包含到"没有 docs/ 也能正确执行"：执行必需的决策参数（阈值、cap、映射、检查单）直接内联进 SKILL.md 或其 `references/`；`docs/` 是可选论证层，只承载"为什么这样设计"的推导，引用时标注"可选论证层"（如"论证见 docs/adr/0004，可选论证层，上述数值为执行值"）。原因：`docs/` 是仓库根级目录，依赖安装方式（`-g` 模式带全仓库，独立 skill 分发不带）；执行参数若只放在 docs 里，未装 docs 的 agent 无法正确执行。引用三分类：运行时参数 → 内联；背景论证 → docs + 可选标注；指标/产物数据源 → 保留为知识索引（如 metrics.md）。新写 skill 或修改时，不得新增"执行必需的 docs 依赖"。

### 平台对应表

| 机制 | GitHub | GitLab | GitCode |
|---|---|---|---|
| 分支保护 | branch protection rule | protected branches | 保护分支 |
| 属主审批 | CODEOWNERS + require review | approval rules / CODEOWNERS | 评审规则 |
| 标签 | labels | labels | 标签 |
| CI | Actions | GitLab CI | 流水线 |

## 3 步骤

### 1 开分支与进 worktree

1. 从 `main` 开自己的 `kb/*` 分支。分支名全局唯一，同一分支同时只能被一个 worktree 检出。
2. `git fetch origin` 确认最新。
3. 按「多 agent 并行（worktree 约束）」建独立 worktree，确认自己在自己的 worktree 与分支。
4. 收工前提交或 stash，清空工作区，不留未提交改动。

### 2 生成物与源：谁写、什么时候写

生成物（索引、路由聚合、reference 索引、timeline、条目使用记录）由脚本写，不由人写。分两种部署形态：

- **有合入后重建 job 的部署（下称自动部署）**：合入 main 后由 `rebuild-generated` job 跑 `python3 scripts/rebuild_generated.py --check`，有 diff 就提交。PR 只交源文件；GitHub 上的 `generated-guard`（生成物守卫）挡住手改生成物，其他平台的流水线可以调用同一条 `scripts/check_generated_untouched.py --base <基线>`。门是覆盖检查（能从源产出齐全生成物），不是逐字节相同。
- **没有这个 job 的部署（下称手工部署）**：没有这个 job 就不会自动重建。两条路选一条，并写进该部署的说明：
  - **保留旧纪律**：PR 带生成物，提交前跑 `python3 scripts/rebuild_generated.py --check`，评审看生成物 diff；
  - **合入后人工重建**：在 main 上跑 `python3 scripts/rebuild_generated.py --sync`——一条命令完成拉取、重建、校验、提交、推送。main 受保护或没有权限时加 `--pr-branch chore/rebuild-generated`，改成推分支后开 PR（只用于没有生成物守卫的部署）。命令会拒绝非生成物的未提交改动与生成物目录里的未跟踪文件，只丢弃已跟踪生成物的本地改动；推送前只探远端可达与快进，分支保护要等真实推送才暴露，失败时提交已在本地，按打印的恢复命令挪到分支。必须有人负责；忘记的后果是新 case 不进索引、新路由词不生效，不是只慢一步。

有生成物守卫的部署不要用 `--pr-branch`：那会开一个只含生成物的 PR，被守卫判红。GitHub 上 main 受保护时，正解是把 `DEPLOY_KEY` 对应的 deploy key 加进 ruleset bypass；否则没有自动或半自动路径，只能由有绕过权限的人跑 `--sync`。

生成物里不写数字（条数 / 容量 / 日期现算）仍是前提：数字一进 git，两人并发合并时要么落在同一行、要么漂移成错的数。路由性质文件走 `merge=union`，两人同一天加词两边都留；索引是嵌套结构，不配 union——自动部署由主干 job 整体重建；手工部署冲突了重跑生成器。

| 文件 | 谁提交 | 提交前跑什么 | 门 |
|---|---|---|---|
| case 本体 `knowledge/<ns>/<cat>/*.yaml` | 人（PR） | — | `verify_case_draft.py --all` |
| 读侧视图 + 总表 `knowledge/_index/…` | 主干 job（自动部署）/ 人（手工部署） | `rebuild_generated.py` | `build_index.py --check`（覆盖检查：每条 case 的读侧行与总表条目都在、与内容对得上） |
| 路由性质文件 `triage-tree.d/<性质>.yaml` | 人（PR） | — | `build_triage_tree.py --check-sources`（性质 id 唯一 / category 合法 / ≤30 性质 / 一性质一文件 / `<side>` 占位在 / 源清单无遗漏） |
| 路由协议与清单 `triage-tree.d/00-protocol.md` | 人（PR） | — | 同上（`sources:` 决定拼接顺序与归属，`workload_types:` 是负载类型层的唯一写点） |
| 路由聚合 `triage-tree.yaml` | 主干 job（自动部署）/ 人（手工部署） | `build_triage_tree.py` | `build_triage_tree.py --check-coverage`（源里每条症状组、负载类型层每个字段都在聚合里） |
| reference 索引 / timeline / 条目使用记录 | 主干 job（自动部署）/ 人（手工部署） | `rebuild_generated.py` | 各自 `--check` |

自动部署合并不需要任何人再跑命令；手工部署必须有人跑 `rebuild_generated.py --sync`，或者保留“PR 带生成物”的旧纪律。两种纪律不要混用：混用时生成物守卫会把带生成物的 PR 判红，而人工重建又没人负责。

#### 手动同步（没有合入后 job）

在 main 上一条命令：

```bash
python3 scripts/rebuild_generated.py --sync
```

它会拒绝非生成物的未提交改动、拉取最新 main（只允许快进）、重建并校验、只提交生成物、推送。main 受保护或没有权限时：

```bash
python3 scripts/rebuild_generated.py --sync --pr-branch chore/rebuild-generated
```

改成推一个只含生成物的分支，再由人在平台上开 PR（只用于没有生成物守卫的部署）。只想看会改什么、不提交：

```bash
python3 scripts/rebuild_generated.py --sync --dry-run
```

失败时按命令打印的下一步做；不要在旧生成物上 rebase。

覆盖检查问的是“条目都在吗、与内容对得上吗”，不问“是否与重新生成一遍逐字节相同”。想归一化（顺序/注释回到生成器口径）随时跑一次生成器，那是可选的：`build_index.py --check --canonical` 与 `build_triage_tree.py --check` 是那两个自检，不作门。

### 3 人读性与代号约定（审读面 / 存储面分离）

仓库产物（docs、EV 卡、SKILL.md、case、PR body）混用多套设计层代号（L/S/A/E/M/O/P/G/T/EV/Phase 等系列）。机器读得动，人不该靠记忆读——本约定把"人读视图"与"词法存储"分开，代号体系本身保持词法（供脚本/CI/面板直读），人读时走解码。

规则：

1. 机器字段保持词法：YAML 枚举字段（`layer`/`status`/`method`/`authorization` 等）不做中文替换——它们是脚本与 CI 的契约；
2. 人读 prose 首次出现即解码：docs 论证文字、EV 卡 prose 字段、PR body、批审摘要、报告里，代号第一次出现写"含义（代号）"或"代号〔含义〕"，之后才允许裸用；高危字母（E/T/G/EV/Phase，及 A/M/O/P+数字）与落地 Phase 系列裸用即歧义，首次出现必解码；
3. 审读面优先：批量审 / PR 审读用解码渲染（`scripts/render_review_summary.py --card/--diff/--scan`，词表 `docs/glossary.yaml`），源文件不变——人审读渲染视图，不裸读 diff；渲染出的未登记代号告警即"先登记再使用"的自我约束；
4. 新增代号先登记，并同时定它的生存范围：`docs/glossary.yaml`（机器数据，唯一权威）里每条带 `scope` 字段——`["*"]` 只给领域语汇（分层 L1–L3、反馈通道 S1–S3、平台与 skill 名）；记账号（roadmap 事项 A/E/M/O/P、治理缺口 G、触发信号 T、落地阶段 Phase）只在各自的计划文档里裸用，机制文档 / PR body / EV 卡 prose 要引用就写中文含义。旧做法要求"在 docs/evolution.md 顶部指代速查表补一行"——那张表已删（它把术语表变成了代号登记处，且把"起新代号"从需要理由变成需要登记）；
5. 越界用途可查：`python3 scripts/render_review_summary.py --scan docs/ README.md CONTEXT.md`（可传目录）会报三类——未登记代号、越界用途（新人可见面单列并优先清理，其余按文件计数可增量清理）、以及词表冲突。`docs/adr/` 与 `proposals/` 是只追加的档案，豁免越界检查（不追溯改历史）；
6. 同形冲突登记而不改名：`A1/A2/A3` 同时是设计公理、roadmap 事项与平台代号前缀，`P0` 同时是优先级与（易混的）流程事项族——这类冲突在词表里各自登记、用 `scope` 消歧，不靠改历史编号（改编号会打烂只追加档案里的引用）。新增代号前先查是否已有同形；
7. 跨文档引用不写裸小节号：引用别处的小节写 `文件名 §N` 或直接写小节标题，不写裸 `§N`（读者不知道是哪篇；且小节号会随文档重排失效——仓库里现存约 100 处这类引用，属历史欠账，见 EV-2026-052 残留）。不硬门化：无"复发 ≥2 次"的证据，不满足检查准入三条件；
8. 不进 CI：prose 可读性是判断性规范（检查准入三条件不满足），由独立预核的黑话判定（见本文件「独立预核」节第 1 档）+ reviewer 抽审保证，不硬门化。唯一例外是机械可判的部分——名单/数字是否与 `docs/_manifest.yaml` 一致、`docs/` 有无未登记文档，由 `build_docs_index.py --check` 硬门（那是"生成物与清单一致性"，不是可读性判断）。

### 4 开 PR 与选模板

`.github/PULL_REQUEST_TEMPLATE/` 下按变更对象分五类（创建 PR 时选择，或 `?template=` 直链）：五类模板的首节都是「背景与动机」（触发 / 不做的代价 / 做完的变化），缺失由 `pr-template` CI 判红。knowledge_intake（新知识升格：背景与动机+预分诊+证据+脱敏自查）、knowledge_modification（改 expected/fix/compat 等高风险字段：背景与动机+触发条款+依据+双签）、reference（references/ 词条：导入/转正/修订，含背景与动机、聚类检查与 verification 声明）、methodology（skill/脚本/文档：背景与动机+原则追溯+golden 回归对照）、structure（triage-tree/namespace：背景与动机+数据依据+迁移完整性检查单）。模板目录属上游方法论，随 fork 同步。

模板选择与结构约束：agent 提交 PR 时模板选择由产出流程决定（to-postmortem/groom/to-reference 产出物自带对应模板类型），不靠提交时自觉选。`pr-template` CI（每次 PR 都跑）校验"用了正确模板 + 关键结构区块在"，缺失即红（如缺首节「背景与动机」，或 knowledge 类缺脱敏自查、高风险类缺双签）。Agent 预核意见区块是可选增值，CI 不校验是否填写，agent 提交链路未打通的内网/手动提交者可留空，不被硬卡；有则给 reviewer 提供基于事实的独立意见供对齐判断（不替代人审）。模板里的"机器可填"字段当前部分自动生成（fixture 候选的 agent_review、预分诊结论），完整自动生成在 roadmap 待定池（PR 描述机器层生成）。

frontmatter 与 body 起点：GitHub 不解析 PR 模板的 YAML frontmatter（name/about/labels 是 issue 模板语法），原样带入会渲染成正文顶部粗体块。模板文件内的元数据因此放在 HTML 注释里（供人读与平台迁移适配）；创建 PR（`?template=` 或 agent `--body-file`）时正文从首个 `## ` 区块开始，注释块可留可删（渲染不可见，CI 只查 `## ` 区块）。`labels` 不随模板自动应用，需 `gh pr create --label` 显式打（如 `kb/high-risk`）。

### 5 走审批：标签与高风险双签

标签集：

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

高风险双签：

高风险清单与 `skills/knowledge-groom/SKILL.md` 保持一致：新建 `common/` 权威记录、修改 `expected`、修改 `fix_on_mismatch`、修改 `compat` 区间、条目的排序分数被 `score_override` 手动覆盖。

落地步骤：

1. groom 在变更 PR 上打 `kb/high-risk` 标签，PR 描述列出触发的条款；
2. `CODEOWNERS` 将 `knowledge/common/` 与 `triage-tree.d/` 指向两组评审人（领域 owner 组与体系维护人组），配合分支保护的 required review，使两组各至少一人批准；
3. 平台限制：GitHub 与 GitLab 原生不强制"批准者来自不同小组"。CODEOWNERS 的多组配置可以逼近这一要求，最终的数量核验写入 groom-report 检查单，由开 PR 的人自查勾选。

owner 尚未确定时，`CODEOWNERS.example` 保留 TODO 占位，CI 与标签流程照常运转；owner 落实后将占位文件复制为 `.github/CODEOWNERS` 并填入真实账号，硬门随即生效。

### 6 合入

PR 经 required review 批准后合入 `main`。自动部署合并完没有任何收尾动作；手工部署见步骤 2 的两条纪律。

通知机制：

- 周 groom 摘要：写入变更 PR 的描述（@ 对应 owner，即时触达），同时开一个打 `kb/groom-report` 标签的 issue 留档，避免重复打扰；
- inbox 积压：groom 摘要中标红；停留超过两周的条目可以开 `kb/stale` issue 催办；
- `feedback_pending` 不走 git：它记录在 `traces/*.yaml` 中，可能包含客户信息，已被 `.gitignore` 挡在仓库之外，通知依靠续接启动时的扫描与面板待办面。这是设计约定，不要把它搬进 issue。注意新诊断的开屏不追问积压的旧 pending——第一屏只服务新问题，逐单追问积压的 pending 不属于诊断动作（口径见 `skills/resume-diagnosis`）。

### 7 fork 侧首次同步的检查单

1. `git fetch upstream && git merge upstream/main`，合并后 `git status`：冲突应只出现在「两边都写」那四个路径上；
2. 只接收面出现冲突，说明 fork 改过它——还原上游那份，改动挪进反提 PR；
3. 「每部署一份」保留本仓那份，「生成物」重新生成，都不逐行解；
4. `python3 scripts/rebuild_generated.py --check` 与 `python3 scripts/verify_proposals.py --check` 应绿（本地生成只作预览；自动部署由主干 job 提交生成物）。

## 4 怎么确认做对了

需要说明各道闸门的实际强度。平台与 CI 能硬性强制的是三件事：谁审批过、YAML 是否合法、自动部署时生成物是否新鲜（手工部署降为约定）。语义层面的闸门（脱敏是否彻底、root cause 是否正确、severity 标注是否恰当）只能依靠流程约定与人工抽查。下表对每道闸门标注强度，避免把约定误认为已被强制。

### 门控映射表

| 闸门 | 机制 | 强度 |
|---|---|---|
| YAML 语法 + 生成物新鲜度 | CI：PR 先跑 `rebuild_generated.py` 再跑各 `--check`；main 由 `rebuild-generated` job 重建并提交 | 硬（自动部署）；手工部署降为约定，靠人工重建 |
| 命名空间变更审批 | `CODEOWNERS` + 分支保护 required review | 硬（开启保护后） |
| 高风险双签 | `kb/high-risk` 标签 + CODEOWNERS 双组路径（每组至少一人批） | 半硬（两个 approval 是否来自两组需人核验，见下） |
| 脱敏 / severity 纪律 | to-postmortem 流程 + groom 周批审抽查 | 约定 |
| eval 回归（改 skill 时） | 按 [eval.md](eval.md) 分级手动 replay；触及输出契约/交互形态时另出盲辨对照（同问题新旧输出各一份、交不知情者判）；replay 脚本化后并入 CI（属 roadmap 里「fixture replay 半自动化」一项） | 约定 → 半硬 |
| eval 观测不陈旧 | CI：`scripts/eval_scorecard.py --check`（`eval/scorecard.yaml` 记"上次回放观测到什么"；夹具字节哈希变了而账本没重建即红） | 硬（夹具哈希）/ 软（目标 case 内容变了只进「待复核」，不挡 merge）；不判准确率——命中率仍要 agent 跑回放 |
| 口径脚本算得对 | CI：`unit-tests` job 按改动选测试后跑（`scripts/select_unit_tests.py` 从 tests 的 import 与脚本名引用、scripts 间的 import 反向闭包算对应测试；`.github/**`、tests 的共享助手/夹具、基线不可比、脚本解析失败时回退全量——`build_index` / `trace_metrics` / `settle_trace_feedback` / `build_timeline` 的口径与边界）；触发面＝改 `scripts/**` 或 `tests/**`（只改 case / 文档的 PR 不跑这道） | 硬（红即挡 merge）；"断言是否真打在口径上"仍是约定；"选中的测试覆盖了改动"也是约定——测试用动态表达式拼脚本路径时静态扫描会漏，残余与修法见脚本头注 |
| EV 卡预测可复现 | CI：`scripts/verify_proposals.py --check`（`predicted_effect.measure` 必须有命令 + 期望，或声明不可度量） | 硬（结构）/ 约定（命令是否有意义） |
| 面板契约（渲染 / 文案 / 数据口径） | CI：`panel-checks` job 跑 `scripts/check_panel_tokens.py` + `scripts/panel_render_check.js`（触发面＝改 `dsh-plugins/**`、`scripts/**`、`metrics/**`、`skills/**`、`docs/**`、`trace-status.yaml`——后两者是它实际读的：文案规范的唯一权威处与状态词表） | 硬（红即挡 merge）；"判据是否真在测那件事"仍是约定 |
| 对照集不被改动者削弱 | CI：`scripts/holdout.py --check`（封存夹具按哈希钉住）+ `holdout-change` 标签闸门；CODEOWNERS 保护 `eval/holdout.yaml` | 硬（哈希）/ 半硬（谁有权 reseal——CODEOWNERS 落实前不是人把关） |
| 回放量尺的按负载类型覆盖 | CI：`scripts/eval_workload_type_coverage.py --check --require-workload-type training --require-workload-type inference`（路由分负载类型后，负载类型是量尺单位；训练侧曾在 22 条 case 上 0 条夹具） | 硬，但只保单一负载类型量尺不归零（负载类型层由 `--check` 判；某一种负载类型一条真实夹具都不剩即红）。格级缺口（某个 (负载类型 × 性质) 格子有 case 没夹具）默认只在报告里出现，不拦——格层门是另一个开关 `--check-cells`（审计轮用），默认不开的代价是"某格缺夹具"与"某格的非最后一条夹具被删"不会自动喊；开了的代价是"新 case 落到尚无夹具的格子会被拦下"。两代价择一，本仓选前者（同 `holdout.py --list` 的空缺格子：报出缺口而不算作覆盖）。它钉的是覆盖不是保护强度：实测 26 条夹具里 16 条的输入对性质正则零命中（靠语义兜底），改坏词表它们照样过；哪几条真钉着词表用 `--nature-evidence` 现算现看 |

### CI

`.github/workflows/kb-checks.yml` 已提供，job 清单以该文件为准（数量与名字随机制增长而变，
不在本文抄一份——抄了就会腐烂且不报错）。本地等价复跑的唯一可靠方式是逐条读那里的 `run:`；
更重的端到端演练见 `python3 scripts/rehearse_evolve_loop.py`（它会把 kb-checks 的每条命令逐条复跑，
但不走 pr-template 那条）。至少要跑的一条起手式：

```bash
pip install pyyaml
python3 scripts/rebuild_generated.py --check
```

这条命令在任何平台都能等价配置：有合入后重建 job 就放在该 job（GitHub 的写法见 `.github/workflows/rebuild-generated.yml`，GitLab 等平台的流水线调用同一个脚本即可）；没有这个 job 就在 main 上跑 `python3 scripts/rebuild_generated.py --sync`（拉取、重建、提交、推送一条命令）。`--check` 会先重建再校验，不只是检查。合入后流水线最少两步：在最新 main 的检出上跑这条命令；`git status --porcelain` 有输出就提交并 push。失败时从最新 main 重来，不要在旧生成物上 rebase。没有这个 job 又没人跑时，新 case 不会进索引、诊断看不见——这个失败形态不报错，比 CI 报错更难发现。

### 触发分两层（改 CI 时两者都要照顾）

- 粗网：`kb-checks.yml` 顶部的 workflow 级 `paths:`，决定这次 push/PR 要不要起这个 workflow。
  它是一串目录 glob（`scripts/**`、`knowledge/**` …）加五个非 glob 的具体路径：仓根的 `README.md`、
  `.gitattributes`、`triage-tree.yaml`、`trace-status.yaml`，以及 `kb-checks.yml` 自身（它一改就全量复验）。
  不是逐文件清单——新增脚本不必回来补名字。
  旧清单逐个列了 35 个 `scripts/*`，实测漏掉 37 个（改那些脚本 CI 不跑）。漏一条 `paths:` 的
  代价是整条流水线静默不跑，所以它宁可宽，细活交给下面那层。
  另有一层事件边界：`push` 只在 `main` 上起，`pull_request` 只在改了上述路径的 PR 上起。开发分支
  的推送不起这个 workflow——`pull_request` 那次以主干为基线算出的文件清单才是准的。改前这些推送
  会另起一轮：新建分支首次推送退化成全量，其后每次推送只是把 PR 那轮的大部分 job 重跑一遍。
  `main` 的 push 保留：PR 验的是当次合并预演（`refs/pull/N/merge`），主干前进后最终合入的树
  没有别处验。代价是未开 PR 时推送零 CI 反馈；已有 PR 的分支再推送，会以 `synchronize` 重跑
  `pull_request`。
- 细网：`changes` job 算出这次改了哪一面（`docs` / `knowledge` / `references` / `metrics` /
  `proposals` / `eval` / `skills` / `code` / `panels` 九个布尔量），各 job 用
  `if: needs.changes.outputs.<组> == 'true'` 自取所需。新增 job 时按"它的命令真正读了哪些目录"挑组
  （看脚本里的路径字面量），不要按直觉——触发面取"读了就触发"，不按"断言强不强"取。
- 它会退化成全量（九个布尔量全 true 并打印原因）的几种情形：本地复跑、无 `.git` 的副本
  （端到端演练场就是这个形态）。另有三条兜底判断留在代码里，收窄 `push` 后都基本不可达：
  `before` 为全 0（拿不到父提交）、与基线比不了（无 merge base 的推送）、`origin/<基线>`
  解析不到（checkout 没带下该分支）。比对取不到内容时必须按全量，不能吞成"零改动"。
- 8 个 verification job（`index-freshness` / `case-structure` / `reference-validation` /
  `metrics-validation` / `proposal-audit` / `docs-index` / `holdout-integrity` / `eval-scorecard`）
  的 `if` 都带 `code`：它们的判定就是"跑一遍 `scripts/<x>.py`"，改了脚本本身而不跑那道门，等于改坏了
  验证脚本没人验（同一个洞的第二面：改 `scripts/verify_references.py` 只有 `unit-tests` 会跑，而
  `tests/` 里没有一条覆盖它）。代价是改 `scripts/` 的 PR 仍会跑多数 job（与改前只差
  `skill-self-contained`——它只读 `skills/`，不吃 `code`），换来只改 `docs` / `knowledge` / `skills` 的 PR 免付。
- `changes` 自己失败时的上报形态：其余 job 全部只上报 `skipped`（GitHub 眼里等于通过）。所以
  将来开分支保护时必须把 `changes` 也列进 required，否则一条坏 diff 会静默放行全部门。
- 为什么不拆成多个 workflow 文件：被 `paths:` 过滤掉的 workflow 不上报 check，将来开分支保护
  会让 PR 永远等一个不会出现的 Expected。单文件 + job 级 `if:` 下，跳过的 job 照常上报 skipped。

### 评审把手（reviewer 怎么判"该不该合"）

判据的独立性只有一条标准：改动者不能靠"写文字"通过它。PR 里的命题（success_criteria 达成、无回归、断言全过）多由制造改动的同一过程写成，而 CI 检查的是内部自洽（索引新鲜度、YAML 合法性、模板结构齐全）——因此"CI 绿 + 测试过"对"该不该合"的信息量接近于零，reviewer 会被逼在"开全文"与"直接批"之间二选一（`mechanism/execution.md` §7 把这一失效形态命名为"橡皮图章"）。

改动侧义务：EV 卡带 `predicted_effect.measure`。reviewer 侧动作：

```
python3 scripts/ev_measure.py <card-id> --run    # 打印判据命令 + 期望，执行并比对
python3 scripts/ev_measure.py --audit            # 全库盘点：可复现 / 声明不可度量 / 缺口 / 存量豁免
```

退出码三态：`0` 符合预测 / `1` 预测被证伪 / `2` 无法判定（存量卡无口径、声明不可度量、卡不存在）——分开，避免"判不了"被读成"验证失败"。

强度标注（原则十）：本把手证明效果（改动是否产生了它声称的变化），不证明价值（该变化是否值得做）；"命令是否真在测那件事"机器判不了，属约定强度，靠人审抽查。存量卡（`verify_proposals.py` 的 `MEASURE_CUTOVER` 之前创建）豁免强制要求——补写不恢复当时的判断，只造事后叙述；缺口由 `--audit` 报出。

### 独立预核（提交前，由另一次会话做）

PR body 里的「Agent 预核意见」由与作者不同的会话产出：另起一个 session，或派一个 subagent。
本仓常见的 subagent 与作者同父会话，它看不到作者的推理，但这不是外部第三方独立，别读成担保。
作者自评不算：PR #282 的预核段由作者填写，独立预核在同一分支上又抓到 3 条（1 条阻断级）。
差别不在模型，在两件事：另一次会话，以及被要求构造反例并跑出来。

不重复跑 CI 已经跑的：PR 上的门以 `.github/workflows/` 下两个工作流为准（`kb-checks.yml` 与
`pr-template.yml`），本文不抄命令清单，理由同 `CLAUDE.md`（抄了会腐烂且不报错）。
预核只做这两类门判不了的事。

| 改动类型 | 预核查什么 | 要跑反例吗 | 耗时 |
|---|---|---|---|
| 文档与措辞（`skills/**`、`docs/**`、`README`、`CLAUDE.md`） | ① 三项判定各给一行结论：可读性（只读这一段的人能不能懂——简称与术语有没有就地定义、句子有没有明确主语、指代有没有歧义；对 `docs/spec/writing-norms.md` §1 第 1 到 3 条与第 10 条）、逻辑性（主张与依据对不对得上、有没有前后矛盾、结论有没有超出来源）、黑话（自造词、把内部标识符当正文用、未定义的简称）；② 对照 `docs/spec/writing-norms.md` §1 的共用条目逐条过改动段落，报命中项与行号；③ 文中每个可验证声明（路径、命令、字段名、代号、数字）逐个核对与实现是否一致；④ 改 skill 正文的另查 `docs/spec/writing-norms.md` §6 的内联要求；⑤ 新增代号是否登记 `docs/glossary.yaml`、`scope` 是否对；⑥ 作者提交前自查漏掉的项（自查动作与五类高频项见 `CLAUDE.md` 的「人读文本的行文规范」条） | 不用 | 5 分钟（只改几段时 2 到 3 分钟） |
| 内容（case、reference、路由词） | ① 路由：`python3 scripts/route_check.py <case 文件>` 报出会被哪个分支接住、宽词是否跨分支重复；② `quickly_check.expected` 在输入里的真实报错上跑一次（CI 只查可编译）；③ 事实自洽与查重（与相邻 case 是否同一根因）；④ 脱敏 | 不用，但要真抽查 | 5 分钟 |
| 脚本、机制、生成物、门语义 | ① 对改动的判定逻辑构造反例并跑出来（给命令与结果）；② 检查门本身有没有洞；③ 前几轮的临时件有没有残留；④ 受影响的文档承诺扫一遍 | 必须 | 15 到 30 分钟 |

三条通用要求：

1. 没查出问题也要给覆盖清单（查了什么、跑了什么命令、结果如何）。否则没查与没问题在 PR 上长得一样。
2. 每条结论带 `文件:行`、一条可复跑命令、实测结果。严重度写中文分级（阻断级、重要级、建议级），
   不要用 `P0`/`P1`：那两个在 `docs/glossary.yaml` 里已是优先级与流程事项族的代号，撞了会歧义。
   结论行给 `MERGE_READY: yes/no`。
3. 第 1 档（文档与措辞）的三项判定逐项写结论，没发现就写「可读性：无发现」。合并成一句
   「已对照规范检查」等于没查：三项各自可以被推翻，合并之后无法核对是哪一项没做。

PR body 上写多少：读 body 的人是 reviewer，要先看到结论与需要自己复核的点，所以 body 只写模板该区块
列的那几项——共同的是结论行（`MERGE_READY`）、核对的版本、按严重度排的问题、覆盖清单、反例与可复跑
命令、第 1 档的三项判定、预核报告指针；其中四类模板另有一条随变更对象定的判定项（knowledge_intake 的「期望正确性」、knowledge_modification 的「归因判定」、reference 的「来源可信度」、structure 的「影响方向」）。
命令输出、逐条证据、核对过程留在预核报告里，body 末行给报告链接（或 `文件:行`）即可。字段的准确清单以
`.github/PULL_REQUEST_TEMPLATE/` 的「Agent 预核意见」区块为准。理由：body 会被逐行读，
报告只在复核某条结论时才展开；把过程复制进 body 会让结论不突出，reviewer 定位要复核的点更慢。
正文用工程师口吻：短句、动词开头、给具体读数；证据节只列 reviewer 要核的 3 到 5 条，不写过程叙述、自我评价与比喻
（全量门清单与其余命令输出留在 CI 或报告）。

为什么不进 CI：预核是判断性工作（非确定性、无机械判据），一旦成门就会变成「CI 能过的仪式」；它也不替代双签。
CI 侧只有机械切片：模板结构（`pr-template.yml`）、docs 名单与未登记文档（`docs-index`）、skill 自包含（`skill-self-contained`）。
代号未登记与越界的 `python3 scripts/render_review_summary.py --scan` 是手工命令，同样不进 CI（`writing-norms.md` §5）。

抽审纪律（约定，同"渐进审序"的用意）：reviewer 每轮自行随机点一处核对，不从改动者列的 spot-check 清单里挑。不指望抓全，目的是让改动侧按实际强度标注成为占优策略。

## 5 出错了怎么办

### 合并冲突：生成物与源

按文件类型处理，不需要判断“留哪份”：

| 冲突文件 | 动作 |
|---|---|
| `triage-tree.d/<性质>.yaml`、`triage-tree.d/00-protocol.md` | 通常不会冲突（配了 `merge=union`）。若真出现冲突标记：把两份都留下、删掉三行标记。聚合由主干 job 重建，不在 PR 里解。 |
| 生成物（总表 / 读侧视图 / 路由聚合 / reference 索引） | 正常不会冲突：生成物不进 PR。旧分支若还带着生成物，把它还原到基线（`git checkout origin/main -- knowledge/_index.yaml knowledge/_index triage-tree.yaml …`），不要逐行解；自动部署由主干 job 重建；手工部署本地跑 `python3 scripts/rebuild_generated.py --check` 后提交。 |
| case 本体 | 真正需要人判断的只剩这里（同一 case 两人改）——按内容合。 |

自动部署建议开启“合并前分支必须最新到主干”：它不会再把索引冲突丢给提交者（生成物已不在 PR 里），只会让内容冲突在合入前暴露。

为什么这么做（可复跑的实验在 `tests/test_concurrent_submit.py`，`python3 tests/test_concurrent_submit.py`
会打印一张对比表）：三人并发、同一个框架时，改前冲突在总表 + 分片 + 路由单文件上，其中路由文件的冲突
要人判断留哪份（判断错就静默少一条路由词）；改后判断冲突为 0。三人各改不同框架（常见形态）时，
改后一次都不冲突。生成物改由主干 job 重建后，同一个格子的并发也不再需要提交者重建。

### CI 静默不上报

- `changes` 自己失败时的上报形态：其余 job 全部只上报 `skipped`（GitHub 眼里等于通过）。所以
  将来开分支保护时必须把 `changes` 也列进 required，否则一条坏 diff 会静默放行全部门。
- 为什么不拆成多个 workflow 文件：被 `paths:` 过滤掉的 workflow 不上报 check，将来开分支保护
  会让 PR 永远等一个不会出现的 Expected。单文件 + job 级 `if:` 下，跳过的 job 照常上报 skipped。

## 6 怎么退回去

- 未合入的改动：`git worktree remove ../ascend-sleuth-s<session>` 清理 worktree；收工前提交或 stash，不留未提交改动。
- fork 首次同步冲突：只接收面还原上游那份，把改动挪进反提 PR；「每部署一份」保留本仓那份；「生成物」重新生成。
- 生成物冲突：先还原到基线；自动部署由主干 job 重建；手工部署跑 `python3 scripts/rebuild_generated.py --check` 后提交。
- 已合入改动的回滚不在本文范围。
