# prof-compare（Prof 数据比对分析）

昇腾 Prof 数据比对工具：**比对两份 Prof 数据（GPU vs NPU / NPU vs NPU / GPU vs GPU）**，自动检测安装 msprof-analyze 并调用 compare 生成结果 xlsx，随后解析为 HTML 可视化分析报告与中文版 xlsx。也支持对已有的 compare 结果 xlsx 直接分析翻译。

---

## 一、应用场景

| 场景 | 说明 |
|---|---|
| GPU → NPU 迁移性能评估 | 以 torch.profiler 采集的 GPU 数据为基准，比对 TorchNPU/MindSpore 采集的 NPU 数据，评估迁移后的性能差异 |
| NPU 版本升级前后对比 | CANN/驱动/框架版本升级前后，验证性能收益或回退 |
| 优化前后对比 | 算子替换、通信优化、并行策略调整等优化项的单机/单卡收益验证 |
| 已有 compare 结果分析 | 手上已有 compare 输出的 `performance_comparison_result_*.xlsx`，需要解析、可视化和翻译为中文 |

## 二、可以解决什么问题

- **定界方向**：E2E 时间差异来自计算、通信还是调度？（OverallMetrics 四大维度拆解 + 各维度贡献占比）
- **算子劣化定位**：哪些算子劣化最严重？劣化是否集中于少数算子？（Diff Duration Top10 + 累计劣化占比集中度）
- **模块级下钻**：劣化集中在哪个模块？调用栈定位到代码位置
- **Kernel 级分析**：劣化 Kernel 定位、按类型汇总、**负载均衡分析**（max/min 方差 > 2x 预警）、两卡数据量比对、多 Shape 分布
- **通信分析**：通信改善/劣化算子定位，区分**等待 vs 传输**（Wait/Transit 拆解）
- **内存分析**：内存增长 Top 算子与分配明细（NPU vs NPU 全零内存场景自动识别）
- **Host 侧分析**：API 下发耗时劣化定位，区分纯耗时变化 vs 调用次数变化
- 报告以**改善亮点 / 劣化风险**双维度呈现，中文 xlsx 消除英文表头阅读障碍

## 三、输入要求

### 3.1 两种工作模式

| 模式 | 输入 | 典型场景 |
|---|---|---|
| 模式一（直比） | 两份 Prof 数据路径：`-d` 待比对 + `-bp` 基准 | 从采集数据开始，全自动出报告 |
| 模式二（xlsx 分析） | compare 输出的 `performance_comparison_result_*.xlsx` | 已有结果，只需分析/翻译 |

### 3.2 输入文件夹如何获取

**NPU 数据（TorchNPU）**

训练/推理脚本中用 `torch_npu.profiler` 采集，输出到 `*_ascend_pt/` 目录，指定 Prof 路径到该层级：

```text
*_ascend_pt/
├── ASCEND_PROFILER_OUTPUT/     # 内含 kernel_details.csv、op_statistic.csv、
│   ├── ...                     # trace_view.json（Text 格式）
│   └── analysis.db             # 或 Db 格式（两者同时存在时优先 Db）
├── FRAMEWORK/
└── PROF_*/
```

**NPU 数据（MindSpore）**

```text
profiler/
└── {rank-*}_{timestamps}_ascend_ms/
    └── ASCEND_PROFILER_OUTPUT/
```

注意：MindSpore 不支持算子/内存比对（对应 Sheet 不存在属正常现象）。

**GPU 数据（torch.profiler 导出）**

```text
pytorch_profiling/
└── *.pt.trace.json             # chrome trace 格式
```

采集建议：开启 `profile_memory=True`（内存比对）与 `record_shapes=True`（Shape 精准匹配）。

**典型采集代码**

```python
# NPU (TorchNPU)
from torch_npu.profiler import profile, ProfilerActivity
with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.NPU]) as prof:
    run_one_step()   # 建议只采集一个 step

# GPU
from torch.profiler import profile, ProfilerActivity
with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA],
             profile_memory=True, record_shapes=True) as prof:
    run_one_step()
prof.export_chrome_trace("gpu_trace.json")
```

**已有 compare 结果 xlsx**

模式一直比成功后，输出目录会生成 `performance_comparison_result_<时间戳>.xlsx`（终端也会打印总体比对结论），把它作为模式二的输入即可。

### 3.3 关键约定与建议

- **建议只采集一个 step**：多 step 数据会混入预热/抖动，影响 E2E、通信等待等判断；多 step 场景用 `--compare_args "--base_step=1 --comparison_step=1"` 固定比对步
- `-d` 传待比对侧（NPU / 优化后 / 新版本），`-bp` 传基准侧（GPU / 优化前 / 旧版本）
- `--enable_api_compare` 依赖 `trace_view.json`（Text 格式数据）
- msprof-analyze 未安装时自动从 PyPI 在线安装（Python ≥ 3.7，建议 3.9+）

## 四、可以得到什么输出

| 输出件 | 文件名 | 说明 |
|---|---|---|
| compare 结果 xlsx | `performance_comparison_result_<时间戳>.xlsx` | 仅模式一：msprof-analyze compare 的原始比对结果（含总体/算子/模块/内存/Kernel/通信/API 等 Sheet） |
| 中间件 JSON | `compare_analysis_result.json` | 所有 Sheet 的结构化分析结果（机器可读，供二次加工） |
| HTML 报告 | `compare_analysis_report.html` | 改善亮点/劣化风险双维度可视化报告 |
| 中文 xlsx | `compare_chinese_result.xlsx` | 原版英文表头翻译为中文，多 Sheet 标签页 |
| 中文 CSV | `chinese_csv/*.csv` | 每个 Sheet 一个独立 CSV（与 xlsx 同步生成） |

默认输出目录为 `./compare_output_<时间戳>`，可用 `-o` 自定义。

## 五、流程图

```mermaid
flowchart TD
    A[用户输入] --> B{输入类型?}
    B -- 两份 Prof 数据目录 --> C[模式一: 直比编排<br/>run_compare.py]
    B -- 已有 compare xlsx --> F[模式二: xlsx 分析<br/>main_analyzer.py]
    C --> D{msprof-analyze<br/>已安装?}
    D -- 否 --> D2[pip install msprof-analyze<br/>自动安装] --> E
    D -- 是 --> E[msprof-analyze compare<br/>生成 performance_comparison_result_*.xlsx]
    E -- --compare_only 到此为止 --> Z[仅交付 compare xlsx]
    E --> F
    F --> G[8 个解析器模块逐 Sheet 解析<br/>总体/算子/模块/内存/<br/>Kernel/通信/API]
    G --> H[中间件 JSON<br/>compare_analysis_result.json]
    H --> I[HTML 报告<br/>compare_analysis_report.html<br/>改善亮点 + 劣化风险]
    H --> J[中文 xlsx<br/>compare_chinese_result.xlsx]
    J --> K[中文 CSV<br/>chinese_csv/*.csv]
    I --> L[交付: 定界方向 → 定位瓶颈 → 下钻根因]
    K --> L
```

分析遵循综合决策树：先定界方向（计算/通信/调度）→ 再定位瓶颈（Top 算子/模块/Kernel/通信）→ 最后下钻根因（明细、调用栈、Shape、负载均衡）。

## 六、脚本与参考文档一览

| 文件 | 作用 |
|---|---|
| `scripts/run_compare.py` | 模式一直比编排：检测/安装 msprof-analyze → compare → 自动进入分析 |
| `scripts/main_analyzer.py` | 模式二主调度：xlsx 解析 → JSON → HTML → 中文 xlsx |
| `scripts/html_generator.py` | HTML 报告生成器 |
| `scripts/csv_translator.py` | 中文翻译器（xlsx + CSV 同步输出） |
| `scripts/parsers/` | 8 个解析器模块（overall_metrics / operator / module / memory / kernel / communication / api_compare / common），覆盖 11 类 Sheet |
| `references/analysis_methodology.md` | 分析方法论（各 Sheet 指标含义、决策树、常见场景解读、单位速查表） |
| `references/compare_quickstart.md` | compare 参数速查与 Prof 数据准备要求 |

## 七、使用样例提示词

**样例 1：GPU vs NPU 迁移比对（模式一，最常见）**

```text
请使用 prof-compare 对比 GPU 基准数据 /data/gpu_pytorch_profiling/（torch.profiler 导出，
含 *.pt.trace.json）和 NPU 数据 /data/npu_ascend_pt/。帮我生成 HTML 分析报告和中文版 xlsx，
并告诉我 E2E 差异主要来自计算、通信还是调度。
```

**样例 2：NPU 优化前后对比（只看算子性能）**

```text
对比昇腾优化前后的两份 prof：优化前 /data/before_ascend_pt/，优化后 /data/after_ascend_pt/。
只关心算子性能，请透传 --compare_args "--enable_operator_compare --use_input_shape"，
输出 HTML 报告并列出劣化 Top10 算子。
```

**样例 3：多 step 数据固定比对步**

```text
我有两份多 step 的 prof 数据：/data/new_ascend_pt/ 和基准 /data/base_ascend_pt/，
请用 prof-compare 直比，固定比对第 3 个 step（--base_step=3 --comparison_step=3），
输出目录指定为 /data/out。
```

**样例 4：已有 compare 结果 xlsx（模式二）**

```text
我手上已有 compare 的输出文件 /data/performance_comparison_result_20260901.xlsx，
请用 prof-compare 解析它，生成 HTML 报告和中文 xlsx，
并重点分析：劣化 Top 算子有哪些、通信等待和传输哪个占主导、Kernel 负载是否均衡。
```

**样例 5：只要 compare xlsx，不要分析报告**

```text
请对 /data/ascend_pt/ 和 /data/gpu_trace/ 执行 prof-compare 的 --compare_only 模式，
只生成 compare 的 xlsx 结果文件即可。
```
