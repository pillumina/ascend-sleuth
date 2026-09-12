# ascend-sleuth Metrics

> 本文是 **metrics 机制的文档化解释**（人读理解用），不是数据存储。指标**数据**在 [`metrics/timeline.yaml`](../metrics/timeline.yaml)（机器可读、CI 校验、append-only）；本文只在机制变化时更新（指标定义、口径、流程），不随每期数据变动。

## 角色分工

| 载体 | 内容 | 变更频率 |
|---|---|---|
| `metrics/timeline.yaml` | 指标时序数据：每期一条快照（period / kind / metrics / sources / notes） | 每期（groom 周批 append） |
| `docs/metrics.md`（本文） | 机制文档：指标定义、口径、汇总流程、示例 | 机制变化时 |
| `metrics/gates.yaml` | **阈值与可解读性下限（数据）**：新鲜度上限、格子 soft/hard cap、反馈下限、哪些指标分母为 0 即"不可解读" | 判据变化时 |
| `scripts/metrics_snapshot.py` | **一期快照的单一产出命令**：组装诊断侧 + 结构侧 + 内容流程侧（逐块标 `sources`）；评测侧按需 | 随机制 |
| `scripts/metrics_health.py` | **闭环检测器**：读 timeline + gates，判新鲜度 / 越界 / 可解读性；`--check` 三态（0 判据全评过且无越界 / 1 有违反 / 2 有判据未被评估）；`--json` 是诊断面板的数据契约 | 随机制 |
| `scripts/trace_metrics.py` | 诊断侧指标（markdown 概览 + `--emit-yaml` 骨架 + `--emit-yaml-only` 供组装） | 随机制 |
| `scripts/verify_metrics.py` | 校验 timeline.yaml 结构（period 唯一 / kind 合法 / 比例字段合法 / live 字段白名单），CI 强制 | 随机制 |

**为什么数据不进 docs**：docs 是给人看的稳定文档，指标数据是随使用增长的结构化记录——两者变更节奏不同，混在一起会让文档随数据漂移（曾发生 W28/W35 字段格式完全不同、跨期不可比的教训）。数据进 `metrics/timeline.yaml` 后，结构由 CI 校验兜底（原则二：不变量写进结构）。

## 指标定义

指标来自**四类来源**——不是"单一脚本"：本行原写作"所有指标由 `trace_metrics.py` 计算（单一数据源）"，
而实际 timeline 里还有结构侧与评测侧指标。这个错误表述让周批只跑 trace_metrics、其余靠人手工搬运，
实测导致结构指标 **10 天**没进快照（快照 `case_total 52` vs 现实 **158**，某格已 `85/30` 而快照里还是 `36/30`）。

| 来源 | 谁产出 | 指标 |
|---|---|---|
| 诊断侧 | `trace_metrics.py`（读 `traces/*.yaml`） | 命中率、误诊率、路由准确率、归因比、按类命中、置信度分布、trace 完整性、Tier 3、反馈捕获、reference 引用/消费点、流程加载与跟随 |
| 结构侧 | `build_index.py` 头注 + `verify_references.py` | `case_total`、`reference_total`、`capacity_by_ns`（每格 `count/cap`） |
| 内容流程侧 | `log_skill_exec.py` → `tail_exec_log.py --summary` | `content_flow_runs`、`evolve_check_runs`、`evolve_check_no_signal` |
| 评测侧 | ixn / golden / S2 等按需 | `ixn_*`、`golden_suite`、S2 内容验证（口径见下） |

`metrics_snapshot.py` 把 ①②③ 拼成一期骨架（④ 按需；拿不到的块**如实不写，不写 0 冒充**）。
比例类指标务必连同分母解读，样本量小（分母不足 10）时波动很大。

**traces 是各检出各一份的运行时件**：在 worktree 里跑周批读不到主检出的 trace
（实测会静默产出空诊断指标）。`metrics_snapshot.py` 会自动解析该读哪一份（优先主检出）
并在 `sources.diagnose_side` 里标明；手工跑 `trace_metrics.py` 时需显式 `--root <主检出>`。

| 指标 | 含义 | 数据来源 |
|---|---|---|
| 命中率 | Tier 2 直接匹配并解决的比例 | trace `hit` 事件 + session 最终 status |
| 误诊率 | 命中了但 fix 没有解决问题的比例 | hit + feedback `not_resolved`/`partial` |
| 路由准确率 | 最终 root cause 所在 namespace 是否在被加载集合内 | triage `routed` / triage_semantic `namespace` vs hit case 实际 namespace |
| 执行-误诊归因比 | 误诊中 case 错与执行错的比例 | trace `attribution` 事件 verdict（diagnose 反馈 not_resolved 后自动归因） |
| 按类命中 | interrupt / precision / performance 各自的命中率 | trace triage/triage_semantic 的 category vs hit |
| 置信度分布 | 低置信（score<0.5）case 占比 | `knowledge/_index.yaml` score 统计 |
| 自起草采纳率 | groom 验证通过的草案 / agent 起草总数 | **暂无数据源**（E1 agent 自起草未落地，E1 落地后补） |
| trace 完整性 | 有 trace 记录的 step / 实际执行 step | proxy：含 triage + 过滤步 |
| Tier 3 挽救率 | 走 Tier 3 兜底检索且最终 resolved 的比例 | trace `tier3` action |
| 反馈捕获率 | 回报 fix 结果的 session / 给出 fix 的 session | trace `feedback` action |
| reference 引用 | 引用次数 / 引用后 resolve 率 / 平台分布 / 消费点分布（collect / signature / fix / background） | trace `reference_lookup` 事件（引用后 outcome 从 session 最终 status 派生；消费点看 `purpose`——`collect` 是数据缺口的采集面，此前无该值可记，等于零观测） |
| 流程加载与跟随 | 流程加载率（`purpose: procedure` 的会话占比）/ 每条流程的加载次数与跟随深度（`procedure_follow` 的 `steps_executed` 长度 / `branch_taken` 分布）/ 跟随后 resolve 率 | trace `reference_lookup`（purpose=procedure）+ `procedure_follow` 事件。**这是流程层唯一的可观测面**——没有它就无法判断某条流程该留、该改、该摘（EV-2026-038）。注意：加载率是**活动**度量不是**价值**度量（加了触发点必然接近 100%），必须与"跟随后 resolve 率"配对读。注意 `purpose: procedure` 也会计入上表的"reference 引用次数"——该口径自此混装四个消费点，看消费点构成请用 `purpose` 分布，不要只看总数。**强度如实标注（原则十）**：加载率是**确定性**的（来自 `reference_lookup` 事件）；
跟随深度（`steps_executed` / `branch_taken` / `conflict`）是**agent 自报**——属弱观测，只可作趋势与异常信号，
不可当验收证据；跟随后 resolve 率来自工程师反馈闭环（S1），是本行唯一较强的效果信号 |
| S2 内容验证（口径，数据积累后进 timeline） | case 被 S2 replay 验证的分布：consistent（内容与外部 resolution 一致）/ self_consistent（自证）/ inconsistent（复审） | `.s2-replay/*.result.yaml` → `settle_s2_feedback.py` 结算 → case `validation_record`。**口径纪律**：consistent ≠ 现场 resolve——S1 现场解决率看 confidence（上表命中率/误诊率），S2 内容验证是独立通道，进 timeline 时标注 `source: issue-replay`，不与 S1 混算。按检查准入三条件，待 S2 结算有真实数据（≥2 期）后再扩展 verify_metrics 白名单 |

## 快照 schema（metrics/timeline.yaml）

每个 period 条目结构固定（由 `trace_metrics.py --emit-yaml` 生成骨架，人复核后 append）：

```yaml
periods:
  - period: "2026-W36"              # 趋势锚点，必须全局唯一
    kind: live                      # live（活诊断周期快照）| replay（回放评估）| example（示例）
    title: "本期诊断指标"
    recorded_at: "2026-08-29"       # 人复核日期（不可自动戳）
    source: "metrics_snapshot.py 组装（诊断侧+结构侧+内容流程侧）"
    sources:                        # 逐块出处（组装命令写入；手写快照可省）
      diagnose_side: "trace_metrics.py（traces/*.yaml ← 主检出，12 个 session）"
      structural_side: "build_index.py 头注 + verify_references.py"
      content_flow_side: "log_skill_exec.py → tail_exec_log.py"
    metrics:
      sessions_total: 12
      tier2_hit: 3
      routed_accuracy: {ok: 2, total: 3}
      misdiagnosis_rate: {ok: 1, total: 3}
      by_category_hit: {interrupt: {hit: 1, total: 1}}
      attribution_ratio: {case_error: 1, execution_error: 0}
      confidence_distribution: {low: 19, total: 42}
      feedback_capture: {resolved: 1, not_resolved: 1, partial: 0}
      trace_completeness: {ok: 2, total: 3}
      vocab_compliance: {ok: 22, total: 22}
      tier3: {used: 0, saved: 0}
      reference: {hits: 1, refs: 1}
      case_total: 158                        # 结构侧
      reference_total: 130
      capacity_by_ns: {inference/vllm-ascend: {interrupt: {count: 85, cap: 30}}}
      content_flow_runs: 4                   # 内容流程侧
      evolve_check_runs: 1
      evolve_check_no_signal: 1
    notes: |
      # 人复核时补充本期解读（miss 归因、异常说明、非指标信息），可多行
```

规则：
- **kind 只有 `live` 参与跨期趋势对比**；`replay`（回放评估）与 `example`（示例）供参考，不参与趋势
  - 结构性指标（`case_total` / `reference_total` / `capacity_by_ns`）**允许出现在 live**：它们是最该看趋势的治理指标，早期只能放在 replay 里 → 按本规则等于没有趋势通道（实测某格已 `85/30`，快照里还停在 `36/30`）
- `verify_metrics.py --check`（CI）校验：period 唯一、kind 合法、recorded_at 必填、metrics 非空、比例字段 ok/total 合法、live 字段在白名单内、`sources` 若填必须是 mapping
- 无数据的指标**如实不写**（诚实退化：reference 刚建立时 hits=0 是现状，不是 bug）

## 闸门与可解读性（`metrics/gates.yaml` + `metrics_health.py`）

阈值**落成数据**（`metrics/gates.yaml`），由 `metrics_health.py` 在周批第 2 步判三件事：

| 面 | 判据（gates.yaml） | 说明 |
|---|---|---|
| 新鲜度 | `live_snapshot_max_age_days` / `structural_max_age_days` | 超期 = 趋势断档（实测：结构侧 10 天没进快照） |
| 越界 | `cell_soft_cap`(>30) / `cell_hard_cap`(>=60) / `feedback_capture_floor`(<=0) | 每条带 `meaning` 与 `action`，报告直接给下一步 |
| 可解读性 | `readability` 规则（如 `source_nonzero`） | 分母/来源无数据时把指标标成**不可解读**，禁止把 `0/N` 读成"零问题" |

**为什么必须单独有这一层**：`verify_metrics.py` 只验**结构**（period 唯一/字段合法），
它不判"该更新的没更新""越界了""这个 0 是没数据还是真没问题"——实测按旧流程走一遍
（trace_metrics → 复核 → append → verify）不会被告知上述任何一条，指标坏了只能等人想起来。
检测器**不进 CI**：安静的一周没有新快照是正常状态，硬门会假红；它服务于周批与季度回顾。

### `--check` 的三态：把"体检器坏了"与"本期没事"分开

`--check` 的退出码**不止"有没有 ✗"**（2026-09-11 起），语义与 `ev_measure.py` 三态同形：

| 退出码 | 含义 | 处置 |
|---|---|---|
| `0` | 判据**全部被评估过**且无越界 | 本期确实没有阻塞项 |
| `1` | 有判据被违反 | 按报告的 `action` 列处置 |
| `2` | 有判据**没被评估**（结构性） | **结论不可用**——"没有越界"不成立，先修检测器/数据源 |

**为什么需要 2 这一态**（两个实测假绿的教训）：修前只看"有没有 ✗"，于是
①`metrics_health.py` 里一处 `collect_structural` 漏解包（返回元组未拆）让容量格子恒为空 →
两条容量闸门**从未触发过一次**，`--check` 照样 exit 0；
②`load_yaml` 把解析异常 `except: return {}` 吞掉 → `gates.yaml` 语法坏掉时判据变成 0 条，
体检器报 `clean（判据全部评过）`——**检测器的配置读坏了它自己不会喊**。
现在两种情况都报 2，并逐条点名（`--json` 的 `broken` 字段），
报告里也给"判据覆盖面"（`闸门 N/M 条已评估 · 可解读性规则 K/L 条已评估`）——
"没报越界"与"没被检查"从此在数据上可区分。诊断面板的指标 tab 首屏据同一份输出显示
「体检器失效」，而不是"闭环未见阻塞项"。

## 汇总流程（owner 职责）

metrics 由 **owner 在 groom 周批时集中生成并 append**（每期一条，团队共享）。工程师不提交 metrics——他们只做诊断（本地 trace）+ 反馈（case confidence 走 PR）；中心化指标（命中/误诊/confidence 分布）直接从仓库 case 统计，无需工程师动作。

```
1. 组一期骨架（**三块一起**，不用再从多个脚本手工搬运）：
   python3 scripts/metrics_snapshot.py --period 2026-W37-live --kind live
   → stdout：人读摘要（含"如实缺席"清单 + 已越界格子）+ YAML 骨架（逐块 sources）
2. **体检**（判据在 metrics/gates.yaml：新鲜度 / 越界 / 可解读性）：
   python3 scripts/metrics_health.py
   → 逐面列出 ✓/!/✗ 与**行动**，末尾报"判据覆盖面"
   → `--check` 退出码三态：0 判据全评过且无越界 · 1 有违反 · 2 有判据**未被评估**（结论不可用）
3. 人复核：核对分母、把"不可解读"的指标写进 notes（禁止把 0/N 读成"零问题"）、
   越界格子按行动列处置（容量拆分走 groom 步骤 6）
4. append 进 metrics/timeline.yaml（每期一条；建议 `--emit-yaml` 直出后手工补 title/notes）
5. python3 scripts/verify_metrics.py --check 通过后随 PR 提交
```

**可解读性纪律**：`metrics_health.py` 判为"不可解读"的指标（例：反馈捕获为 0 时的误诊率），
**不得**在 notes/报告里写成"零误诊/无异常"——那是把"没人回报"读成"没有问题"。如实写
"本期该指标不可解读（原因）"。

## 季度回顾（固定动作）

用 `metrics/timeline.yaml` 中连续 live 快照：核对命中率/误诊率/路由准确率趋势，校准 [roadmap](roadmap.md) 闸门数值，确认学习闭环在数据上成立。趋势直接从 YAML 读取，不需人眼 diff。

**回顾前先跑一次体检**：`python3 scripts/metrics_health.py` —— 它把"哪些指标超期没更新、
哪些闸门越界没人处理、哪些指标本期不可解读"直接列出来，避免回顾时对着过期快照讨论趋势。

<!-- 示例快照保留在 git 历史（W28/W35），如需展示格式见 timeline.yaml 现有 replay 条目 -->
