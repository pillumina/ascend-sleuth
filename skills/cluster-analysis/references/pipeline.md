# 八阶段流水线规范（pipeline.md）

> 本文件是执行链路的**单一事实来源（SSOT）**：所有命令、参数与产物路径均以 `scripts/run_workflow.py` 及各脚本 argparse 实现为准（核实基准：当前 scripts/ 代码）。
> 合并自原 workflow.md 与 vendor_integration.md。

## 1. 目录与产物契约

所有阶段共用一个中间件根目录（run_workflow 创建，默认名 `cluster_analysis_mw`）。下表路径均相对该目录：

| 路径 | 产出者 | 说明 |
|---|---|---|
| `detect_result.json` | detect_prof.py | 输入类型判定（db/text、单卡/多卡/集群），后续阶段的分支依据 |
| `analysis_scope_cache.json` | detect_prof.py | 本次运行的统一分步结果；源签名有效时后续阶段复用，避免重复扫描大 trace |
| `workflow_status.json`、`workflow_cache.json` | run_workflow.py | 阶段状态、覆盖范围、退出码和输入/参数/代码指纹 |
| `advisor/advisor.md`、`advisor/advisor.json` | advisor_fallback.py（原生 advisor all 产物仅留档） | Advisor 结论 |
| `cluster_analysis_output/cluster_analysis.db` | 原生 msprof-analyze 或 cluster_fallback.py | 集群分析主库（SQLite） |
| `cluster_analysis_output/recipes/<name>/*.csv` | recipe_fallback.py | 各 recipe 明细 CSV |
| `cluster_analysis_output/recipes_summary.{md,json}` | recipe_fallback.py | recipe 汇总（同时写入 DB 表 RecipeSummary） |
| `compare/compare_analysis_result.json` | compare_fallback.py | 卡间对比明细 |
| `compare/performance_comparison_result_*.xlsx` | 原生 msprof-analyze（归一化复制）或 compare_fallback.py | 对比 Excel（vendor compare 消费此文件） |
| `reports/cluster_analysis_report.html` | vendor_bridge（cluster） | vendor 单模式报告（最终报告 iframe 内嵌；独立报告模式下为唯一交付） |
| `reports/compare_analysis_report.html` | vendor_bridge（compare） | vendor 对比报告（iframe 内嵌） |
| `reports/cluster_data.json`、`reports/chinese_xlsx/` | vendor_bridge 附带产物 | 报告数据与中文表 |
| `swimlane/swimlane_rank{N}.{md,json}` | swimlane_analyzer.py | 每卡泳道分析 |
| `swimlane/swimlane_compare.md` | swimlane_analyzer.py | 泳道跨卡对比 |
| `insight_bottlenecks.{json,md}` | insight_locator.py | 原总报告结论章节使用的卡级精确定位证据和摘要 |
| `insight_bottlenecks.html` | report_generator.py | 附加定位摘要；不替代完整总报告 |
| `performance_report.html` | report_generator.py | 最终总报告（相对路径引用 reports/ 子目录） |

## 2. 阶段规范（P0–P7）

所有阶段由 run_workflow.py 顺序编排。探测、输入能力预检或报告生成失败时退出 1；其他请求阶段失败可生成带明确警示的部分报告，退出 2；完整成功退出 0。预期缺采集能力的 recipe 为 unsupported，执行异常为 failed，不得混淆。缓存只有在上次完整成功且输入、参数、脚本指纹匹配时复用；换卡、换输入或代码变化会重新生成，并将旧的中间件产物保存在 `<mw>/_history/`。大文件指纹使用大小与纳秒修改时间，小于等于 1 MiB 的文件额外校验内容；若外部工具保持大小和时间戳却改写大文件，使用 `--force`。

### P0 detect — 输入判定
```bash
python scripts/detect_prof.py --path <输入路径> --output <mw>/detect_result.json --skill-dir <skill根>
```
- 失败处理：中止流水线（无输入类型无法继续）。
- 模式判定：`single`（单卡）/ `cluster`（多卡，有可用卡目录）/ `cluster_output_only`（输入仅含 `cluster_analysis_output`、无任何卡目录）。
- `input` 保留用户路径；P1–P4 使用 `cluster_root`（或实际单卡目录）。`export_type`、`available_artifacts` 和 `capabilities` 分别表示导出配置、可用文件和当前脚本能力；TEXT 与 DB 可以共存。无分步标识时输出 `analysis_scope=whole_prof`、`step_ids=["prof"]`；真实标识数另存 `known_step_count`。缺摘要时尝试有效事件/会话范围；仍无证据则失败。规则见 [whole_prof_step.md](whole_prof_step.md)。`coverage` 包含期望/实际/缺失 rank、唯一 step 数、rank-step 样本数，另含 `db_window_count`（采集窗行数）、`db_step_scopes`、`device_ids`（rank→device 真实映射）。
- **DB 能力探测**：TEXT 缺失时经 `scripts/lib/prof_data.py`（WAL 感知只读）探测 `analysis.db::StepTraceTime / CommAnalyzer*` 与主 DB 元数据表。逐卡输出 `db_capabilities`（step_rows/window_rows/comm_* /rank_device_map/host_info/step_time/sources）、`db_step_scope`（`step`|`capture_window`）、`device_id` 及来源；`capabilities.fallback_*` 由有效 TEXT/DB 摘要或可推导的事件/时间范围共同决定；无分步整段统一用内置路径。
- **独立报告模式（cluster_output_only）**：跳过 P1–P4、P6、P7，只执行 P5 vendor cluster 子报告；**不生成总报告 performance_report.html**。

### P1 advisor（原生留档 + 内置归一化）
探测到 `msprof-analyze` 时先执行原生 `advisor all`（产物 mstt_advisor_* 仅留档），随后**始终**运行内置实现归一化（advisor.md/advisor.json 为总报告契约件，保证两种路径产物一致）：
```bash
python scripts/advisor_fallback.py --root <输入路径> --output <mw>/advisor
```
- 内置实现按卡回退：`step_trace_time.csv` 缺失时读 `analysis.db::StepTraceTime`（us）；`communication.json` 缺失时读 `analysis.db::CommAnalyzerTime`（ms）。整段单 step 口径在 advisor.md 与 JSON 标注（不能按真实训练迭代解释）；NULL 指标计数一并输出。

### P2 cluster（原生优先）
原生：`msprof-analyze cluster analysis -d <输入路径> --top_num N`。原生成功但产物缺 `cluster_analysis.db` 时（下游 recipes/泳道依赖），用内置实现补齐（幂等：db 已存在自动跳过）。原生失败/不可用降级：
```bash
python scripts/cluster_fallback.py --root <输入路径> [--force]
```
- DB-only：步骤行来自 `analysis.db::StepTraceTime`（有效 step 用原 id；无分步数据整体用 `prof` 汇总标签），通信三表来自 `CommAnalyzer*`（ms/MB/GB/s）；rank→device 用主 DB `RANK_DEVICE_MAP`，host 用 `HOST_INFO`，缺失才回退推断。
- 派生来源写入 `ClusterBaseInfo`（step_source/device_map_source/host_source/communication_source/step_id_semantics）与 `status_info`（NULL 指标计数、未映射 step 计数），见 db_support.md §4。

### P3 recipes（原生优先）
原生：逐个执行 8 个 recipe 子命令（cluster_time_summary / communication_time_sum / slow_rank / slow_link / communication_bottleneck / free_analysis / compute_op_sum / hccl_sum，附 `--top_num`）。原生成功但缺 `recipes_summary.json`（总报告契约件，原生不产出）时，用内置实现补齐全量 23+1 recipe 与汇总件。原生失败/不可用降级：
```bash
python scripts/recipe_fallback.py --root <输入路径> --top-num 20
```
- CATEGORIES 注册的 23 个正式 recipe；extra recipe `communication_bandwidth_sum` 实际执行但未注册（扩展定位，见 recipes_catalog.md）。
- 通信算子判定正则：当前以 recipe_fallback.py 的 `COMM_NAME_PATTERN` 为准（二期收敛至 scripts/lib/config.py）。

### P4 compare（原生优先）
- 原生路径：复用内置选卡（通信占比最小=baseline、最大=compare；`--base-rank/--compare-rank` 可覆盖）→ `msprof-analyze compare -d <baseline卡> -c <compare卡> -o <mw>/compare/native` → 原生 xlsx 归一化复制为 `<mw>/compare/performance_comparison_result_{max}_{min}.xlsx`（vendor glob 契约，历史命名 xlsx 一并清理）→ `compare_fallback.py --json-only` 补产 `compare_analysis_result.json`（仅产 JSON，不触碰 xlsx）。选卡失败/原生命令失败/未找到 xlsx/JSON 补产失败 → 整体回退完整内置实现。
- 降级：
```bash
python scripts/compare_fallback.py --root <输入路径> --output <mw>/compare [--base-rank <N> --compare-rank <N>]
```
- `--base-rank/--compare-rank` 未给时自动选卡；产物 `performance_comparison_result_{tag}.xlsx` + `compare_analysis_result.json`。
- 选卡与 step 摘要均支持 DB 回退（`analysis.db::StepTraceTime`，us）；比较口径 `step`（真实 step 对齐）或 `whole_prof`（各卡整段汇总，`prof` 标签）随 `compare_analysis_result.json` 的 `step_scope` 声明，采集窗口径不得输出迭代吞吐结论。通信维度在 `communication.json` 缺失时回退 `CommAnalyzerTime`（ms）。

### P5 vendor — 集成开源报告
```bash
python scripts/vendor_bridge.py cluster --data-dir <mw>/cluster_analysis_output --reports-dir <mw>/reports
python scripts/vendor_bridge.py compare --compare-dir <mw>/compare --reports-dir <mw>/reports
```
纪律（禁止绕过 vendor_bridge 直接调 vendor 内部脚本）：
- vendor_bridge 固定以 `--mode single` 调 vendor/generate_cluster_report.py；compare 模式 glob `performance_comparison_result_*.xlsx` 取第一个交 main_analyzer.py。
- 返回码：0 = 成功；2 = 输入缺失/不支持 → 跳过并继续（不算失败）；其他 = 失败。
- 产物写入 reports/ 子目录，最终报告以相对路径 iframe 内嵌。
- **独立报告模式**下 `vendor_bridge.py cluster` 是唯一执行阶段，`reports/cluster_analysis_report.html` 即最终交付。

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
- 有卡级数据时必跑，单卡同样执行；独立报告模式仍按原规定只执行 P5。
- 只读原始卡级 DB/CSV/trace，补充真实组映射、通信实例去重、到达/Host 差异、计算热点及 Free 时间窗；缺少证据时记录原因。DB-only 回退：step 摘要取 `analysis.db::StepTraceTime`（有效 step 用原 id；无分步数据整体用 `prof` 标签，单采集窗以 `SESSION_TIME_INFO` 为边界）；计算热点取主 DB `TASK⋈COMPUTE_TASK_INFO`（通信算子按名称启发过滤，候选证据，`compute_source` 随证据输出；PMU 比例不可用）。
- 输出被 P7 嵌入原“结论与建议”章节，原主报告、模式路由和 P0–P7 其余阶段继续保留。方法与定位契约见 [insight_localization.md](insight_localization.md)，有卡级数据时必须阅读；DB 适配契约见 [db_support.md](db_support.md)。

### P7 report
```bash
python scripts/report_generator.py --middleware <mw> --mode {single|cluster|compare} --output <mw>/performance_report.html
```
- mode 由 detect_result.json 判定决定（run_workflow 自动传递）。
- 图表 ECharts 懒初始化；`<details>` 区块默认展开；样式与模板规范见 html_template_spec.md。
- `performance_report.html` 仍是默认主交付；其“结论与建议”章节读取 P6a 结果，按通信、计算、Free 展示关键点。其余全部章节保留，同名定位摘要是配套产物。

## 3. run_workflow 一键编排

```bash
python scripts/run_workflow.py --input <Prof数据路径> --output-dir <输出根> \
    [--top-num 20] [--base-rank N --compare-rank N] [--report-mode cluster] \
    [--skip-recipes] [--skip-compare] [--skip-swimlane] [--skip-report] [--force] [--no-native] [--timeout 300]
```
- 默认**原生优先**：探测到 `msprof-analyze`（PATH 存在性）即各阶段优先原生，失败或产物缺口自动回退/由 fallback 补齐；`--no-native` 整体禁用原生，全部使用内置实现；`--msprof-cli` 兼容保留（no-op）。
- 未提供的可选参数均取脚本默认值；json 解析输入异常已由 run_workflow 保护（try/except）。

## 4. 全局纪律

1. **原生 CLI 优先（默认）**：run_workflow 以 `shutil.which('msprof-analyze')` 探测；可用则 P1 `advisor all`（留档）、P2/P3 `cluster` 子命令、P4 `compare` 均优先原生，失败或产物缺口（db/summary/json）自动回退或由 fallback 补齐；`--no-native` 整体禁用（能力对照见 msprof_cli.md）。
2. **单卡模式**：P2/P3/P4 跳过；advisor 和 P6 泳道做单卡；P7 `--mode single`。**多卡模式**：P1 对**所有卡**聚合 advisor；默认比对通信占比最大/最小的不同 rank，要求 step 窗口一致。**独立报告模式**：只执行 P5 vendor cluster 子报告，不生成总报告。
3. **进阶分析全量执行**：23 正式 + 1 扩展 recipe 全跑；部分数据缺失的 recipe 输出「不支持/数据缺失」说明，不算失败。
4. **unit 纪律**：单位由字段/schema 定义，不由 DB/TEXT 容器决定。Step trace 为 μs（CSV 与 `analysis.db::StepTraceTime` 同）；TEXT communication.json、`analysis.db::CommAnalyzer*` 和新表 ClusterCommunicationTime 的时间为 ms；主 DB 事件/会话/STEP_TIME 为 ns；中间库记录 communication_time_unit，旧版 schema 按其声明转换。报告统一标注单位；累计算子耗时必须与同一 rank/step 窗口的 Computing 总和比较，不能除以平均单 step。
5. **step/采集窗纪律**：无分步数据把整个 prof 作为一个汇总 step（`prof`），真实分步保留原编号；原始 NULL-step 来源不改写。汇总 step 可用于整个范围的分析，但不推算单次训练迭代或推理请求吞吐。契约详见 whole_prof_step.md。
6. **泳道分类纪律**：Thread xxx / Stream xxx / Communication 域（Group 内非 Plane 泳道，如 dp:xx）三类汇总；Plane 泳道不单独成节。
7. **报告纪律**：信息概览最前 → 结论与建议随后 → 详情分区；左侧固定导航；`<details>` 可折叠且**默认全部展开（含子报告）**；集群总览按 Step 区分；无「卡片清单（cluster 模式）」分区；vendor 报告以 iframe 内嵌。模板实现细节统一见 html_template_spec.md（模板规范的修改只更新该文件）。
8. **增量定位契约**：在原结论章节内展示主导问题与通信、计算、Free 各至多三个关键点；中文列名、精确时间、跨卡实例去重和影响口径见 insight_localization.md。配套定位摘要不改变完整流程的完成条件。

## 5. 并行波次调度（子 agent）

分析任务多且相互独立，按「波次（Wave）」调度子 agent，每波最多 3 个并行：

- **Wave 0**：主 agent 运行 P0 检测，确定模式（单卡/多卡/仅 cluster_analysis_output）与后续步骤清单。若判定为独立报告模式（cluster_output_only），直接执行 P5 vendor cluster 子报告后结束（无 Wave 1–4、无总报告）。
- **Wave 1**（互不依赖，3 个子 agent 并行）：
  - 子 agent A：P1 全卡 advisor
  - 子 agent B：P2 集群输出件生成（多卡且缺失时；单卡跳过）
  - 子 agent C：P4 比对 xlsx（多卡时；单卡跳过）
- **Wave 2**：
  - 子 agent D：P3 全量 recipe（依赖 P2）
  - 子 agent E：P5 vendor compare 子报告（依赖 P4）
  - 子 agent F：P6 泳道统计（若卡数多，按卡拆分为多个子 agent，每个负责若干卡）
- **Wave 3**：
  - 子 agent G：P5 vendor cluster 子报告（依赖 P2）
  - 主 agent：P6a 精确定位（依赖 P0 卡列表，与 vendor 独立）。
- **Wave 4**：主 agent 运行 P7 汇总报告，嵌入全部子报告。

> 泳道统计（P5）逐卡独立、互不依赖，是最佳并行点；trace_view.json 较大（数百 MB），每个子 agent 用流式解析脚本处理，不要整文件读入。

## 6. 端到端验收清单

1. `detect_result.json` 存在且含类型判定字段。
2. advisor.md 与 advisor.json 至少其一存在（始终由内置实现归一化；原生 advisor all 产物仅留档）。
3. `cluster_analysis.db` 为有效 SQLite 文件。
4. `recipes_summary.md` 覆盖全部执行过的 recipe（对应 summary JSON 存在）。
5. 多卡时 `performance_comparison_result_*.xlsx` 与 `compare_analysis_result.json` 成对存在。
6. `reports/` 下至少一份 vendor HTML；vendor SKIP 属预期时最终报告应有标注。
7. 多卡时 swimlane_rank{N}.md 覆盖全部参与卡，swimlane_compare.md 存在。
8. `performance_report.html` 可直接打开，内嵌子报告可见（相对路径未断）。
9. 独立报告模式（cluster_output_only）：只要求 `detect_result.json` + `reports/cluster_analysis_report.html` 存在，**不得**生成 `performance_report.html`。
10. 有卡级数据时 P6a 结果存在并进入原总报告；通信实例跨卡仅一条，三部分各最多三条，缺失卡与证据不足有明确范围说明。P6a 成功不代替前九项验收。
11. **DB-only 输入**：`detect_result.json` 逐卡含 `db_capabilities`/`db_step_scope`（原始 step 或 capture_window）和 `analysis_scope`（实际 step 或 whole_prof）；advisor/compare/insight 产物标注 DB 来源；整段口径有明确说明（`prof` 标签、每卡 1 step、无单次迭代吞吐结论）；泳道记 unsupported 而非失败；派生 `cluster_analysis_output` 的 ClusterBaseInfo 含来源键。

## 7. 扩展守则（新增阶段 / recipe 的固定模式）

- 新增阶段：脚本只做「输入路径 → 产物路径」的单向变换，参数命名对齐现有惯例（--root/--output），并在 run_workflow 注册阶段号与产物检查。
- 新增 recipe：函数返回统一 `(rows, reason)` —— rows 为 list[dict]，不支持时 `(None, "原因")`；正式 recipe 在 CATEGORIES 注册，extra recipe 需在 recipes_catalog.md 标注。
- 跨脚本共享常量（目录名、正则、阈值）只允许放 scripts/lib/config.py。
