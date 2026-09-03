# ascend-sleuth Metrics

> 本文是 **metrics 机制的文档化解释**（人读理解用），不是数据存储。指标**数据**在 [`metrics/timeline.yaml`](../metrics/timeline.yaml)（机器可读、CI 校验、append-only）；本文只在机制变化时更新（指标定义、口径、流程），不随每期数据变动。

## 角色分工

| 载体 | 内容 | 变更频率 |
|---|---|---|
| `metrics/timeline.yaml` | 指标时序数据：每期一条快照（period / kind / metrics / notes） | 每期（groom 周批 append） |
| `docs/metrics.md`（本文） | 机制文档：指标定义、口径、汇总流程、示例 | 机制变化时 |
| `scripts/trace_metrics.py` | 从 trace 生成指标（markdown 概览 + `--emit-yaml` 快照骨架） | 随机制 |
| `scripts/verify_metrics.py` | 校验 timeline.yaml 结构（period 唯一 / kind 合法 / 比例字段合法），CI 强制 | 随机制 |

**为什么数据不进 docs**：docs 是给人看的稳定文档，指标数据是随使用增长的结构化记录——两者变更节奏不同，混在一起会让文档随数据漂移（曾发生 W28/W35 字段格式完全不同、跨期不可比的教训）。数据进 `metrics/timeline.yaml` 后，结构由 CI 校验兜底（原则二：不变量写进结构）。

## 指标定义

所有指标由 `trace_metrics.py` 计算（单一数据源），`--emit-yaml` 生成快照骨架。比例类指标务必连同分母解读，样本量小（分母不足 10）时波动很大。

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
| reference 引用 | 引用次数 / 引用后 resolve 率 / 平台分布 | trace `reference_lookup` 事件（引用后 outcome 从 session 最终 status 派生） |
| S2 内容验证（口径，数据积累后进 timeline） | case 被 S2 replay 验证的分布：consistent（内容与外部 resolution 一致）/ self_consistent（自证）/ inconsistent（复审） | `.s2-replay/*.result.yaml` → `settle_s2_feedback.py` 结算 → case `validation_record`。**口径纪律**：consistent ≠ 现场 resolve——S1 现场解决率看 confidence（上表命中率/误诊率），S2 内容验证是独立通道，进 timeline 时标注 `source: issue-replay`，不与 S1 混算。按检查准入三条件，待 S2 结算有真实数据（≥2 期）后再扩展 verify_metrics 白名单 |

## 快照 schema（metrics/timeline.yaml）

每个 period 条目结构固定（由 `trace_metrics.py --emit-yaml` 生成骨架，人复核后 append）：

```yaml
periods:
  - period: "2026-W36"              # 趋势锚点，必须全局唯一
    kind: live                      # live（活诊断周期快照）| replay（回放评估）| example（示例）
    title: "本期诊断指标"
    recorded_at: "2026-08-29"       # 人复核日期（不可自动戳）
    source: "trace_metrics.py 从 traces/*.yaml 自动生成"
    metrics:
      sessions_total: 3
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
    notes: |
      # 人复核时补充本期解读（miss 归因、异常说明、非指标信息），可多行
```

规则：
- **kind 只有 `live` 参与跨期趋势对比**；`replay`（回放评估）与 `example`（示例）供参考，不参与趋势
- `verify_metrics.py --check`（CI）校验：period 唯一、kind 合法、recorded_at 必填、metrics 非空、比例字段 ok/total 合法
- 无数据的指标**如实不写**（诚实退化：reference 刚建立时 hits=0 是现状，不是 bug）

## 汇总流程（owner 职责）

metrics 由 **owner 在 groom 周批时集中生成并 append**（每期一条，团队共享）。工程师不提交 metrics——他们只做诊断（本地 trace）+ 反馈（case confidence 走 PR）；中心化指标（命中/误诊/confidence 分布）直接从仓库 case 统计，无需工程师动作。

```
1. 跑 python3 scripts/trace_metrics.py --emit-yaml
   → stdout：markdown 概览（人读）+ YAML 快照骨架
2. 人复核：核对分母、补充 notes（miss 归因/异常/本期说明）、改 kind 为 live
3. append 进 metrics/timeline.yaml（每期一条）
4. python3 scripts/verify_metrics.py --check 通过后随 PR 提交
```

## 季度回顾（固定动作）

用 `metrics/timeline.yaml` 中连续 live 快照：核对命中率/误诊率/路由准确率趋势，校准 [roadmap](roadmap.md) 闸门数值，确认学习闭环在数据上成立。趋势直接从 YAML 读取，不需人眼 diff。

<!-- 示例快照保留在 git 历史（W28/W35），如需展示格式见 timeline.yaml 现有 replay 条目 -->
