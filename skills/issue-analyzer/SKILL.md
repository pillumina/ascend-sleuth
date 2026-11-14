---
name: "issue-analyzer"
description: "昇腾现网故障日志取证分析（故障类问题，非性能分析）。当用户提供 plog/slog/host/device/framework/dmesg 等日志，排查模型拉起失败、训练/推理中断、算子或驱动报错、服务异常等故障类问题时使用。不用于 Prof 性能分析与瓶颈定位（用 cluster-analysis）、两份 Prof/集群数据对比（单卡用 prof-compare，多卡用 cluster-compare）、环境配置采集与比对（用 ascend-dump-analyzer）、BMC 硬件健康诊断（用 ibmc_analyzer）。"
---

# Ascend Field Issue Analyzer（昇腾现网问题分析）

分析昇腾（Ascend）服务器现网问题的文本日志取证技能。输入客户现场日志（plog、slog/host/device 日志、训练框架日志、推理服务日志、dmesg 等），输出**带完整证据链、经过回验**的 Markdown 分析报告。典型场景：模型拉起失败、训练中断、推理中断。

技能组成：

| 文件 | 用途 |
|---|---|
| `scripts/log_analyzer.py` | 预置通用分析脚本（零依赖 Python 3.7+），覆盖清单/提取/聚合/取证/回验五类操作 |
| `references/fault-patterns.md` | 常见故障模式库（特征关键字 + 排查路径 + 常见根因） |
| `references/log-structure.md` | 昇腾日志结构知识、时间戳格式、现场采集命令 |
| `references/analysis-strategy.md` | 大日志四层处理策略、脚本参数规范、证据回验规范 |
| `references/report-template.md` | MD 分析报告模板（最终交付格式） |

## When to Invoke

- 用户提供昇腾现网日志包（plog/slog/host/device 日志、框架日志、dmesg 等）要求分析
- 用户描述现网问题现象（模型拉起失败、训练/推理中断、服务异常等），需要基于日志定位
- 用户要求产出问题分析报告
- 用户提及 "plog 分析"、"日志定位"、"现网问题"、"训练中断排查"、"拉起失败" 等关键词

**不适用（转其他技能，必要时联动）**：

- 环境快照采集/对比、配置漂移分析 → `ascend-dump-analyzer`
- CPU/Host 侧性能瓶颈定位（怀疑 Host 拖慢设备） → `cpu-host-performance`

## 四条铁律（分析全程必须遵守）

### 铁律 1：脚本优先，禁止大文件直读

现网日志动辄数百 MB 到 GB，直接读取会耗尽上下文、拉长分析时间。

- **硬性阈值**：单文件 >2MB 或 >10000 行，禁止直接 Read，必须通过 `scripts/log_analyzer.py` 处理
- 四层管线：L0 清单扫描 → L1 错误提取 → L2 聚合分布 → L3 聚焦取证（详见 `references/analysis-strategy.md`）
- **优先复用预置脚本**，通过参数组合完成 80% 场景；确需定制时在预置脚本思路上扩展，禁止每次从零现写脚本
- 已知问题时间点时，先用 `--since/--until` 把分析收敛到 ±10 分钟窗口
- 所有分析产物落盘到 `analysis_out/` 工作目录；报告中引用产物路径，不把大段日志塞进上下文

### 铁律 2：证据链 + 回验闭环（反幻觉）

杜绝编造问题点、编造解决方案。

- 每个问题点必须携带**证据三元组**：`日志文件路径:行号` + **逐字引用的原文** + 时间戳。对话中陈述发现、报告中罗列问题点时都必须展示
- 结论三级标注，报告与对话统一使用：
  - `[已验证]`——证据已通过 `verify` 命令回验，原文逐字一致
  - `[推断]`——有日志证据 + 领域经验推演，必须写明推断依据与进一步验证方法
  - `[待确认]`——缺少信息，需用户补充，必须列出需要什么
- **回验闭环**：报告生成前，将全部证据写入 `analysis_out/evidence.json`，运行 `verify` 逐条核对；未通过回验的证据降级为 `[待确认]` 并在报告中说明原因
- 禁止条款：
  - 找不到证据就写"未找到直接证据"，不允许脑补问题点
  - 错误码含义不确定时保留原文并标注"含义待查证（建议查官方错误码参考）"，禁止编造解释
  - 引用原文必须逐字复制（可截断但不得改写），转述内容不得放进"原文"栏
  - "日志事实"（日志明确写了什么）与"经验解读"（分析者认为意味着什么）必须分层表述

### 铁律 3：信息不齐，批量先问

避免在错误方向上消耗大量日志分析时间。

- 分析开始前先完成 Step 0 启动清单核对，缺失项分两类处理：
  - **阻塞性缺失**：没有就无法有效分析（如日志覆盖数天但没有问题时间窗口、不知道单机还是集群）→ **一次性批量提问**，说明每项信息的用途，等用户答复后再继续
  - **非阻塞缺失**：可按假设继续，但所有假设必须显式标注"当前假设：xxx"，并在报告"待确认事项"中回收
- 提问要具体可答：不问"还有什么补充信息"，而问"问题首次发生的大致时间（精确到分钟）？必现还是偶发？单卡还是多卡？"
- 分析中发现日志不足（如只有 plog 没有框架日志），向用户列出**需补充的日志清单 + 现场采集命令**（见 `references/log-structure.md`）

### 铁律 4：标准化报告输出

- 最终交付使用 `references/report-template.md` 模板生成 Markdown 报告，保存到 `analysis_out/report_<问题简称>_<日期>.md`
- 报告必含：结论摘要（TL;DR）、问题描述、分析范围、关键问题点（证据表）、问题发生过程（时间线表 + Mermaid 图）、根因分析（含已排除假设）、解决方案（含验证方法）、问题总结、附录
- 每个关键问题点带置信度标注（同铁律 2 三级）

## 工作流（七步）

> 流程节奏：**中途同步发现但不暂停**——每个阶段结束时向用户简报关键发现（1~3 句），然后自动继续；仅 Step 0 出现阻塞性缺失时才等待用户答复。

### Step 0 信息核对（问）

按启动清单核对（详见 `references/analysis-strategy.md`）。整理已有信息与缺失项；阻塞性缺失 → 批量提问并等待；非阻塞 → 标注假设继续。
产出：`analysis_out/case_info.md`

### Step 1 日志清单（L0）

`log_analyzer.py scan` 生成 manifest；检查日志是否覆盖问题时间窗、是否缺关键日志（dmesg/框架日志等）；向用户同步范围与缺口。
产出：`analysis_out/manifest.{json,md}`

### Step 2 错误面扫描（L1+L2）

按场景从 `references/fault-patterns.md` 挑选关键字叠加到默认模式上 → `extract`（带时间窗）→ `stats` 看分布。先看全局分布，再决定下钻方向。
产出：`analysis_out/hits.{json,md}`、`analysis_out/stats.md`

### Step 3 时间线重建（L3）

对重点命中行用 `context` 取上下文 → 跨文件按时间排序 → **定位"第一个错误"** → 多机场景先做时钟对齐检查（见 `references/log-structure.md`）。
产出：`analysis_out/timeline.md`

### Step 4 根因分析

用 `references/fault-patterns.md` 做模式匹配 + 补充取证；严格区分日志事实与经验解读；日志不足则列出补充清单请用户提供。
产出：`analysis_out/root_cause_notes.md`（中间笔记，不直接交付）

### Step 5 证据回验

整理全部证据为 `evidence.json`（格式见 `references/analysis-strategy.md`）→ `verify` 逐条核对 → 按回验结果定级置信度。
产出：`analysis_out/evidence.json`、`analysis_out/verify_result.{json,md}`

### Step 6 报告生成

按 `references/report-template.md` 生成报告，用 `computer://` 链接交付用户。
产出：`analysis_out/report_<问题简称>_<日期>.md`

## log_analyzer.py 速查

运行方式：`python <本技能目录>/scripts/log_analyzer.py <command> [options]`

| 命令 | 层级 | 用途 | 关键参数 |
|---|---|---|---|
| `scan` | L0 | 目录清单（文件/大小/行数/首末时间戳/类型识别） | `--dir --depth --out --md` |
| `extract` | L1 | 错误提取（级别/关键字/自定义正则 + 时间窗过滤） | `--dir/--files --since --until --keywords --patterns --no-default --top --out --md` |
| `stats` | L2 | 聚合分布（按模式/文件/时间桶统计 hits） | `--hits hits.json --bucket 1m/10m/1h/1d --md` |
| `context` | L3 | 聚焦取证（指定行号或正则第 N 次命中的 ±N 行上下文） | `--file --line N`（或 `--regex R --nth K`）`--before --after` |
| `verify` | 回验 | 逐条核对 evidence.json 中的 file:line:quote | `--evidence evidence.json [--root 日志包根目录] --md` |

完整参数说明与输出格式见 `references/analysis-strategy.md`。

## 与其他技能联动

| 场景 | 联动方式 |
|---|---|
| 需要环境版本/配置信息佐证版本类问题 | `ascend-dump-analyzer`（若用户有 dump JSON；没有则引导采集） |
| 日志指向 host 侧性能/调度问题，文本日志证据不足 | `cpu-host-performance`（需用户提供 ftrace/trace 采集数据） |
| 需要 npu-smi 当前状态、dmesg 等未提供的日志 | 按 `references/log-structure.md` 采集命令清单向用户索取 |

## 分析产物目录约定

```
analysis_out/
├── case_info.md        # 问题描述与环境信息（Step 0）
├── manifest.json/.md   # 日志清单（Step 1）
├── hits.json/.md       # 错误提取结果（Step 2）
├── stats.md            # 聚合分布（Step 2）
├── timeline.md         # 时间线（Step 3）
├── root_cause_notes.md # 根因分析笔记（Step 4）
├── evidence.json       # 证据登记表（Step 5）
├── verify_result.json/.md  # 回验结果（Step 5）
└── report_*.md         # 最终报告（Step 6）
```

**原始日志一律只读**。所有产物写入独立目录，绝不修改、移动、删除原始日志。

## 重要注意事项

- 报告与对话中引用日志时，使用相对日志包根目录的路径 + 行号（如 `plog/host-192-168-1-10/device-3.log:1234`），保证用户能在日志包中定位
- Mermaid 图与时间线表格并存：图直观展示故障传播链，表保底可读（任何查看器都能看）
- `references/fault-patterns.md` 是**排查线索库，不是结论库**——任何模式命中仍需日志证据支撑（铁律 2）
- 中断类问题优先找"第一个异常"：后续大量报错多为连锁反应，超时报错的节点往往不是根因节点
