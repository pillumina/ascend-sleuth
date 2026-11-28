# 八阶段流水线规范（pipeline.md）

> 本文件是执行链路的**单一事实来源（SSOT）**：所有命令、参数与产物路径均以 `scripts/run_workflow.py` 及各脚本 argparse 实现为准（核实基准：当前 scripts/ 代码）。

## 1. 目录与产物契约

所有阶段共用一个中间件根目录（run_workflow 创建，默认名 `cluster_analysis_mw`）。下表路径均相对该目录：

| 路径 | 产出者 | 说明 |
|---|---|---|
| `detect_result.json` | detect_prof.py | 输入类型判定（db/text、单卡/多卡/集群），后续阶段的分支依据 |
| `analysis_scope_cache.json` | detect_prof.py | 本次运行的统一分步结果；源签名有效时后续阶段复用，避免重复扫描大 trace |
| `workflow_status.json`、`workflow_cache.json` | run_workflow.py | 阶段状态、覆盖范围、退出码和输入/参数/代码指纹 |
| `advisor/advisor.md`、`advisor/advisor.json` | advisor_fallback.py（原生 advisor all 产物仅留档） | Advisor 结论 |
| `cluster_analysis_output/cluster_analysis.db` | 原生 msprof-analyze 或 cluster_fallback.py | 集群分析主库（SQLite） |
| `cluster_summary/recipes/<name>/*.csv` | recipe_fallback.py | 已有集群输出的派生明细，输入文件只读 |
| `cluster_summary/recipes_summary.{md,json}` | recipe_fallback.py | 已有集群输出的全量 Rank × Step 与 recipe 状态。工作流自行生成的内置集群库沿用源旁的派生目录，并可写入其 RecipeSummary 表 |
| `compare/compare_analysis_result.json` | compare_fallback.py | 卡间对比明细 |
| `compare/performance_comparison_result_*.xlsx` | 原生 msprof-analyze（归一化复制）或 compare_fallback.py | 双卡差异工作簿 |
| `swimlane/swimlane_rank{N}.{md,json}` | swimlane_analyzer.py | 每卡泳道分析 |
| `swimlane/swimlane_compare.md` | swimlane_analyzer.py | 泳道跨卡对比 |
| `insight_bottlenecks.{json,md}` | insight_locator.py | 原总报告结论章节使用的卡级精确定位证据和摘要 |
| `insight_bottlenecks.html` | report_generator.py | 附加定位摘要；不替代完整总报告 |
| `performance_report.html` | report_generator.py | 最终总报告 |

## 2. 阶段规范（P0–P7）

所有阶段由 run_workflow.py 顺序编排。探测、输入能力预检或报告生成失败时退出 1；其他请求阶段失败可生成带明确警示的部分报告，退出 2；完整成功退出 0。预期缺采集能力的 recipe 为 unsupported，执行异常为 failed，不得混淆。缓存只有在上次完整成功且输入、参数、脚本指纹匹配时复用（包括内置比对模块及其模板）；换卡、换输入或代码变化会重新生成，并将旧的中间件产物保存在 `<mw>/_history/`。大文件指纹使用大小与纳秒修改时间，小于等于 1 MiB 的文件额外校验内容；若外部工具保持大小和时间戳却改写大文件，使用 `--force`。

### P0 detect — 输入判定
```bash
python scripts/detect_prof.py --path <输入路径> --output <mw>/detect_result.json --skill-dir <skill根>
```
- 失败处理：中止流水线（无输入类型无法继续）。
- 模式判定：`single`（单卡 Prof）/ `cluster`（多卡 Prof，或集群输出随附卡级 Prof）/ `cluster_output_only`（仅集群输出）。后两种均生成 P7 集群主报告。支持传集群输出件本身或其父目录；只有集群数据时跳过卡级阶段。
- `coverage` 表示卡级证据范围。`cluster_coverage` 由工作流从实际用于出报的时间汇总统计，记录 Rank 数、Step 数和 rank-step 样本数。输入仅有样本卡时，样本数量不限制已有集群汇总的覆盖。
- `input` 保留用户路径；P1–P4 使用 `cluster_root`（或实际单卡目录）。`export_type`、`available_artifacts` 和 `capabilities` 分别表示导出配置、可用文件和当前脚本能力；TEXT 与 DB 可以共存。无分步标识时输出 `analysis_scope=whole_prof`、`step_ids=["prof"]`；真实标识数另存 `known_step_count`。缺摘要时尝试有效事件/会话范围；仍无证据则失败。规则见 [whole_prof_step.md](whole_prof_step.md)。`coverage` 包含期望/实际/缺失 rank、唯一 step 数、rank-step 样本数，另含 `db_window_count`（采集窗行数）、`db_step_scopes`、`device_ids`（rank→device 真实映射）。
- **DB 能力探测**：TEXT 缺失时经 `scripts/lib/prof_data.py`（WAL 感知只读）探测 `analysis.db::StepTraceTime / CommAnalyzer*` 与主 DB 元数据表。逐卡输出 `db_capabilities`（step_rows/window_rows/comm_* /rank_device_map/host_info/step_time/sources）、`db_step_scope`（`step`|`capture_window`）、`device_id` 及来源；`capabilities.fallback_*` 由有效 TEXT/DB 摘要或可推导的事件/时间范围共同决定；无分步整段统一用内置路径。

### P1 advisor（原生留档 + 内置归一化）
探测到 `msprof-analyze` 时先执行原生 `advisor all`（产物 mstt_advisor_* 仅留档），随后**始终**运行内置实现归一化（advisor.md/advisor.json 为总报告契约件，保证两种路径产物一致）：
```bash
python scripts/advisor_fallback.py --root <输入路径> --output <mw>/advisor
```
- 内置实现按卡回退：`step_trace_time.csv` 缺失时读 `analysis.db::StepTraceTime`（us）；`communication.json` 缺失时读 `analysis.db::CommAnalyzerTime`（ms）。整段单 step 口径在 advisor.md 与 JSON 标注（不能按真实训练迭代解释）；NULL 指标计数一并输出。

### P2 cluster（原生优先）
优先复用已有的集群输出，保留用户提供的库和 CSV。缺集群输出时才从多卡 Prof 生成。原生可用时执行 `msprof-analyze cluster analysis -d <输入路径> --top_num N`；原生失败或没有可用集群时间输出时用内置实现：
```bash
python scripts/cluster_fallback.py --root <输入路径> [--force]
```
- DB-only：步骤行来自 `analysis.db::StepTraceTime`（有效 step 用原 id；无分步数据整体用 `prof` 汇总标签），通信三表来自 `CommAnalyzer*`（ms/MB/GB/s）；rank→device 用主 DB `RANK_DEVICE_MAP`，host 用 `HOST_INFO`，缺失才回退推断。
- 派生来源写入 `ClusterBaseInfo`（step_source/device_map_source/host_source/communication_source/step_id_semantics）与 `status_info`（NULL 指标计数、未映射 step 计数），见 db_support.md §4。

### P3 recipes 与集群时间汇总
内置 recipe 为 P7 生成统一汇总。仅当本次由原生 P2 新生成集群输出时，额外运行原生支持的 8 项 recipe 留档。已有集群数据由一键工作流传入 `--cluster-db` 和/或 `--step-csv`，派生文件写到独立的 `cluster_summary/`。缺少可选 `ClusterBaseInfo` 时照常读取逐 Rank 时间，不推断并行参数或补写原库。缺失指标保留未知，依赖该字段或卡级明细的 recipe 标为 unsupported。
```bash
python scripts/recipe_fallback.py --root <输入路径> --top-num 20
```
- CATEGORIES 注册的 23 个正式 recipe；extra recipe `communication_bandwidth_sum` 实际执行但未注册（扩展定位，见 recipes_catalog.md）。
- 基础 Rank × Step 汇总先于进阶 recipe 落盘。`--skip-recipes` 仍生成该汇总。已有集群输出的 recipe 默认最长 7200 秒，可用 `--recipe-timeout` 调整。进阶阶段失败且基础汇总可用时，保留主报告并显示失败阶段。
- 通信算子判定正则：当前以 recipe_fallback.py 的 `COMM_NAME_PATTERN` 为准（二期收敛至 scripts/lib/config.py）。

### P4 compare（原生优先）
- 原生路径：复用内置选卡（通信占比最小=baseline、最大=compare；`--base-rank/--compare-rank` 可覆盖）→ `msprof-analyze compare -d <baseline卡> -c <compare卡> -o <mw>/compare/native` → 原生 xlsx 归一化复制为 `<mw>/compare/performance_comparison_result_{max}_{min}.xlsx`（文件名按比对 rank、基线 rank 排列）→ `compare_fallback.py --json-only` 补产 `compare_analysis_result.json`（仅产 JSON，不触碰 xlsx）。选卡失败/原生命令失败/未找到 xlsx/JSON 补产失败 → 整体回退完整内置实现。
- 降级：
```bash
python scripts/compare_fallback.py --root <输入路径> --output <mw>/compare [--base-rank <N> --compare-rank <N>]
```
- `--base-rank/--compare-rank` 未给时自动选卡；产物 `performance_comparison_result_{tag}.xlsx` + `compare_analysis_result.json`。
- 选卡与 step 摘要均支持 DB 回退（`analysis.db::StepTraceTime`，us）；比较口径 `step`（真实 step 对齐）或 `whole_prof`（各卡整段汇总，`prof` 标签）随 `compare_analysis_result.json` 的 `step_scope` 声明，采集窗口径不得输出迭代吞吐结论。通信维度在 `communication.json` 缺失时回退 `CommAnalyzerTime`（ms）。

### P5 独立单卡对比入口

Sleuth 使用独立的 prof-compare 入口处理单卡 Prof 对比。集群流水线保留 P4 的工作簿、差异 JSON 和主报告。

### P6 swimlane
```bash
python scripts/swimlane_analyzer.py --card <卡号> --rank <N> --output <mw>/swimlane [--compare-dir <mw>]
```
- 多卡时每卡产出 swimlane_rank{N}.md/.json，随后产出 swimlane_compare.md。
- Chrome Trace 流式解析，防大文件 OOM。
- **能力门槛**：依赖 `trace_view.json` 或 `kernel_details.csv`；两者皆缺（DB-only 数据）时该卡记 unsupported 并注明原因，不算失败，P6a 仍可用 DB 原始事件定位。

### P6a Insight 瓶颈定位（原流程上的新增子阶段）
```bash
python scripts/insight_locator.py --detect <mw>/detect_result.json --output <mw>
```
- 单卡和多卡均执行。
- 只读原始卡级 DB/CSV/trace，补充真实组映射、通信实例去重、到达/Host 差异、计算热点及 Free 时间窗；缺少证据时记录原因。DB-only 回退：step 摘要取 `analysis.db::StepTraceTime`（有效 step 用原 id；无分步数据整体用 `prof` 标签，单采集窗以 `SESSION_TIME_INFO` 为边界）；计算热点取主 DB `TASK⋈COMPUTE_TASK_INFO`（通信算子按名称启发过滤，候选证据，`compute_source` 随证据输出；PMU 比例不可用）。
- 输出被 P7 嵌入原“结论与建议”章节，原主报告、模式路由和 P0–P7 其余阶段继续保留。方法与定位契约见 [insight_localization.md](insight_localization.md)，有卡级数据时必须阅读；DB 适配契约见 [db_support.md](db_support.md)。

### P7 report
```bash
python scripts/report_generator.py --middleware <mw> --mode {single|cluster|compare} --output <mw>/performance_report.html
```
- mode 由 detect_result.json 判定（run_workflow 自动传递，`cluster_output_only` 使用 `cluster` 渲染）。所有输入共用 `scripts/report_assets/template.html`。
- 图表 ECharts 懒初始化；`<details>` 区块默认展开；样式与模板规范见 html_template_spec.md。
- `performance_report.html` 仍是默认主交付；其“结论与建议”章节读取 P6a 结果，按通信、计算、Free 展示关键点。同名定位摘要是配套产物。

## 3. run_workflow 一键编排

```bash
python scripts/run_workflow.py --input <Prof数据路径或集群输出目录> --output-dir <输出根> \
    [--top-num 20] [--base-rank N --compare-rank N] [--report-mode cluster] \
    [--skip-recipes] [--skip-compare] [--skip-swimlane] [--skip-report] [--force] [--no-native] [--timeout 300] [--recipe-timeout 7200]
```
- 卡级 Advisor、双卡比对和缺失集群件的生成优先使用已探测到的原生 CLI。`--no-native` 禁用原生。`--force` 重算派生结果，保留用户提供的集群源。
- 未提供的可选参数均取脚本默认值；json 解析输入异常已由 run_workflow 保护（try/except）。

## 4. 全局纪律

1. **集群源优先**：有可用的集群输出时，直接从其中的 Rank × Step 生成集群汇总。已有源的缓存同时校验数据库、WAL 和时间 CSV 的指纹；运行期间源变化时停止出报。
2. **卡级阶段**：P1 聚合实际提供且可分析的 Prof；至少两张卡具备可比口径时才执行默认双卡比对。泳道和 Insight 按可用卡级证据执行。仅有单卡 Prof 时跳过 P2–P4。
3. **进阶分析全量执行**：23 正式 + 1 扩展 recipe 全跑；部分数据缺失的 recipe 输出「不支持/数据缺失」说明，不算失败。
4. **unit 纪律**：单位由字段/schema 定义，不由 DB/TEXT 容器决定。Step trace 为 μs（CSV 与 `analysis.db::StepTraceTime` 同）；TEXT communication.json、`analysis.db::CommAnalyzer*` 和新表 ClusterCommunicationTime 的时间为 ms；主 DB 事件/会话/STEP_TIME 为 ns；中间库记录 communication_time_unit，旧版 schema 按其声明转换。报告统一标注单位；累计算子耗时必须与同一 rank/step 窗口的 Computing 总和比较，不能除以平均单 step。
5. **step/采集窗纪律**：无分步数据把整个 prof 作为一个汇总 step（`prof`），真实分步保留原编号；原始 NULL-step 来源不改写。汇总 step 可用于整个范围的分析，但不推算单次训练迭代或推理请求吞吐。契约详见 whole_prof_step.md。
6. **泳道分类纪律**：Thread xxx / Stream xxx / Communication 域（Group 内非 Plane 泳道，如 dp:xx）三类汇总；Plane 泳道不单独成节。
7. **报告纪律**：信息概览最前 → 结论与建议随后 → 详情分区；左侧固定导航；`<details>` 可折叠且**默认全部展开（含子报告）**；集群总览按 Step 区分；无「卡片清单（cluster 模式）」分区；有 prof-compare 子报告时以 iframe 内嵌。模板实现细节统一见 html_template_spec.md（模板规范的修改只更新该文件）。
8. **增量定位契约**：在原结论章节内展示主导问题与通信、计算、Free 各至多三个关键点；中文列名、精确时间、跨卡实例去重和影响口径见 insight_localization.md。配套定位摘要不改变完整流程的完成条件。

## 5. 并行波次调度（子 agent）

分析任务多且相互独立，按「波次（Wave）」调度子 agent，每波最多 3 个并行：

- **Wave 0**：主 agent 运行 P0 检测，选定集群源并确认卡级证据。只有集群输出时运行 P3 汇总和 P7 出报。
- **Wave 1**（互不依赖，3 个子 agent 并行）：
  - 子 agent A：P1 全卡 advisor
  - 子 agent B：P2 集群输出件生成（多卡且缺失时；单卡跳过）
  - 子 agent C：P4 比对 xlsx（多卡时；单卡跳过）
- **Wave 2**：
  - 子 agent D：P3 全量 recipe（依赖 P2）
  - 子 agent F：P6 泳道统计（若卡数多，按卡拆分为多个子 agent，每个负责若干卡）
- **Wave 3**：
  - 主 agent：P6a 精确定位（依赖 P0 卡列表）。
- **Wave 4**：主 agent 运行 P7 生成汇总报告。

> 泳道统计（P6）逐卡独立、互不依赖，是最佳并行点；trace_view.json 较大（数百 MB），每个子 agent 用流式解析脚本处理，不要整文件读入。

## 6. 端到端验收清单

1. `detect_result.json` 存在且含类型判定字段。
2. 有卡级摘要时，advisor.md 和 advisor.json 由内置实现归一化。
3. 集群输入的数据库或 CSV 中有有效 Rank × Step 时间数据，报告计数与源数据一致。
4. `recipes_summary.json` 有基础集群时间汇总。执行进阶 recipe 后，`recipes_summary.md` 记录执行状态与缺失证据。
5. 双卡比对完成时，`performance_comparison_result_*.xlsx` 与 `compare_analysis_result.json` 成对存在。
6. 工作流中独立单卡子报告阶段标记为 skipped，单卡 Prof 对比通过独立入口执行。
7. 泳道明细覆盖具备泳道数据的参加卡；有两张以上可用卡时另有 swimlane_compare.md。
8. `performance_report.html` 可直接打开，并展示已分析的数据范围。
9. 有卡级数据时 P6a 结果存在并进入原总报告；通信实例跨卡仅一条，三部分各最多三条，缺失卡与证据不足有明确范围说明。P6a 成功不代替前八项验收。
10. **DB-only 输入**：`detect_result.json` 逐卡含 `db_capabilities`/`db_step_scope`（原始 step 或 capture_window）和 `analysis_scope`（实际 step 或 whole_prof）；advisor/compare/insight 产物标注 DB 来源；整段口径有明确说明（`prof` 标签、每卡 1 step、无单次迭代吞吐结论）；泳道记 unsupported 而非失败；派生 `cluster_analysis_output` 的 ClusterBaseInfo 含来源键。

## 7. 扩展守则（新增阶段 / recipe 的固定模式）

- 新增阶段：脚本只做「输入路径 → 产物路径」的单向变换，参数命名对齐现有惯例（--root/--output），并在 run_workflow 注册阶段号与产物检查。
- 新增 recipe：函数返回统一 `(rows, reason)` —— rows 为 list[dict]，不支持时 `(None, "原因")`；正式 recipe 在 CATEGORIES 注册，extra recipe 需在 recipes_catalog.md 标注。
- 跨脚本共享常量（目录名、正则、阈值）只允许放 scripts/lib/config.py。
