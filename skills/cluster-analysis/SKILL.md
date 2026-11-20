---
name: cluster-analysis
description: 昇腾（Ascend）NPU Prof 性能分析（单份数据）。当用户提供一份 Prof 采集数据目录（单卡或多卡/集群），要求分析性能、定位瓶颈、排查慢卡/慢算子/通信问题、advisor 诊断，或生成性能分析 HTML/MD 报告时使用，例如"分析这个 prof 的性能问题"、"看看这个 Prof 哪里慢"。自动识别输入形态（单卡/多卡、db/text、仅含 cluster_analysis_output），缺失时自动生成 cluster_analysis_output，执行八阶段流水线与全部进阶 recipe，产出含左侧导航与子报告嵌入的完整 HTML 报告。不用于对比两份 Prof 或两个集群（多卡/集群对比用 cluster-compare，单卡对比用 prof-compare）；不用于现网报错/中断等故障日志排查（用 issue-analyzer）；不用于 Host 侧 ftrace/系统级瓶颈诊断（用 cpu-host-performance）。
---

# 昇腾 NPU 训练性能分析技能（cluster-analysis）

面向昇腾 NPU 训练与推理场景的性能分析技能。原生 CLI 按子命令预检后优先使用；内置 fallback 支持 TEXT 导出与 DB-only 两种数据源（TEXT 缺失时自动回退 `analysis.db` 适配层，见 [references/db_support.md](references/db_support.md)），能力不等价处均透明标注。没有有效分步标识时，整个 prof 按每卡一个汇总 step（`prof`）分析；TEXT 空 Step 与 DB NULL-step 统一处理。有真实 step 时保留原分步。缺摘要时使用可读事件与时间范围建立整段 step；仍无有效范围或数据时明确报不足。无分步数据必须阅读 [references/whole_prof_step.md](references/whole_prof_step.md)。

TEXT 导出目录可以同时存在 DB。以采集配置和实际产物能力共同路由，不根据 DB 文件存在猜测导出格式。后续阶段使用 detector 给出的实际卡根目录。原始 step 与整段汇总 step（`prof`）分别标记；整段分析只计一个 step，不解释为一次训练迭代或一个推理请求。报告先检查 `workflow_status.json`：`complete` 才算完整完成，`partial`/`failed` 必须说明失败阶段。结论限于已提供 rank 和 step/window，通信占比高或 collective 耗时短不等于已经定位慢卡。

在原有八阶段完整流程上增加 **P6a Insight 瓶颈定位**，不改变原有模式路由或裁剪阶段。默认主交付仍为 `performance_report.html`：在原“结论与建议”章节内，先说明主导问题，再按通信、计算、Free 各展示最多三个关键点，给出中文卡号、泳道、完整算子、精确时间、影响口径和简短归因。Advisor、全部 recipe、双卡比对、泳道统计与 vendor 子报告仍完整执行和展示。

有卡级数据时执行 P6a，并完整阅读 [references/insight_localization.md](references/insight_localization.md)。`insight_bottlenecks.json` 是总报告使用的定位证据，同名 `.md`/`.html` 是附加摘要，不能代替总报告或被当作完成完整流程的依据。

## 必读入口

执行任何分析前，**必须先完整阅读 `references/pipeline.md`**。它是执行链路的单一事实来源（SSOT），涵盖：

- 八阶段流水线规范（P0–P7 命令、参数、目录与产物契约）
- 全局纪律（原生 CLI 优先、单卡/多卡差异、全量 recipe、unit 换算、泳道与报告纪律）
- 并行波次调度（子 agent Wave 0–4，每波最多 3 个并行）
- run_workflow 一键编排与端到端验收清单

## 能力速览

1. **输入自动识别**：单卡/多卡、db/text 格式、框架（PyTorch/MindSpore）、已有 `cluster_analysis_output`；逐卡输出 db 能力清单（step 摘要/采集窗、通信表、rank-device 映射）。
2. **DB 适配层**：TEXT 导出缺失时自动读取 `analysis.db`（StepTraceTime / CommAnalyzer*）与主 DB（RANK_DEVICE_MAP / HOST_INFO / SESSION_TIME_INFO），WAL 感知只读；单位、窗口语义与来源标记契约见 [references/db_support.md](references/db_support.md)。
3. **Advisor 诊断**：单卡做单卡 advisor；多卡对全部卡聚合 advisor，输出 md。
4. **集群分析输出件**：多卡缺失时自动生成（db + 基表；DB-only 由适配层建库，来源写入 ClusterBaseInfo/status_info），置于单卡 prof 目录同级。
5. **进阶分析**：五大类 23 正式 + 1 扩展 recipe 全量执行，能力矩阵透明呈现（不支持者标注原因）。
6. **性能比对**：通信占比最大 vs 最小两卡对比，vendor prof-compare 生成 HTML 与中文 xlsx；支持真实 step 对齐与整段 prof 汇总比较（`step_scope=step|whole_prof`）。
7. **泳道统计**：每卡 Process / Ascend Hardware / Communication 三类算子统计，多卡跨卡比对；依赖 trace_view.json/kernel_details.csv，DB-only 数据泳道记为 unsupported（P6a 仍可用 DB 原始事件定位）。
8. **最终 HTML 报告**：信息概览在前、结论建议随后，左侧固定导航，分区可折叠默认展开，vendor 子报告 iframe 内嵌。
   在原结论章节内新增通信实例去重、真实通信组映射、慢卡及 Host 回溯、计算指标与 Free 时间窗定位，保持原报告导航和其余章节。
9. **独立报告模式**：输入仅含 `cluster_analysis_output`（无任何卡目录，mode=`cluster_output_only`）时，跳过完整流水线，只调用 vendor cluster-output-analysis 生成独立报告 `reports/cluster_analysis_report.html`，**不生成总报告 performance_report.html**。

## 参考文档索引

| 文档 | 内容 |
|------|------|
| `references/pipeline.md` | **单一事实来源**：阶段命令、目录契约、全局纪律、并行调度、验收清单、扩展守则 |
| `references/recipes_catalog.md` | 五大类 23 正式 + 1 扩展 recipe 目录 |
| `references/msprof_cli.md` | msprof-analyze 原生 CLI 与 fallback 能力对照 |
| `references/html_template_spec.md` | HTML 模板交互规范（模板改动只改这里） |
| `references/insight_localization.md` | 原报告结论章节的 Insight 映射、慢卡归因、计算/Free 证据及定位输出契约 |
| `references/whole_prof_step.md` | 无分步 TEXT/DB 整段单 step 规则、来源、时间边界与验收 |
| `references/db_support.md` | DB-only 适配契约：analysis.db/主 DB 已验证 schema、单位、采集窗语义、来源标记与限制 |

> vendor 子技能（`vendor/cluster-output-analysis/`、`vendor/prof-compare/`）**只经 `scripts/vendor_bridge.py` 调用**（参数与返回码见 pipeline.md P5），禁止绕过桥接器直接调用其内部脚本；其内部 SKILL.md 仅供维护者参考，分析任务无需读取。
