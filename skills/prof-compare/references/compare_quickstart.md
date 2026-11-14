# msprof-analyze compare 参数速查与数据准备

本文件供直比模式（`run_compare.py`）执行时参考：如何校验用户提供的 Prof 数据、如何为 `--compare_args` 挑选合适的参数。

## 1. Prof 数据格式校验

compare 支持任意两边组合：GPU vs NPU、NPU vs NPU、GPU vs GPU（同构亦可）。

### NPU 数据（TorchNPU / MindSpore）

目录需指定到以下任意一层级：

```text
# TorchNPU（Text 格式）
*_ascend_pt/
├── ASCEND_PROFILER_OUTPUT/
│   ├── kernel_details.csv
│   ├── op_statistic.csv
│   └── trace_view.json
├── FRAMEWORK/
└── PROF_*/

# TorchNPU（Db 格式）
*_ascend_pt/
└── ASCEND_PROFILER_OUTPUT/
    ├── analysis.db
    └── ascend_pytorch_profiler_{rank_id}.db

# MindSpore
profiler/{rank-*}_{timestamps}_ascend_ms/
└── ASCEND_PROFILER_OUTPUT/
```

- Text 与 Db 格式均可比对；同一目录两者同时存在时，工具优先使用 Db 格式
- `--enable_api_compare` 依赖 `trace_view.json`（Text 格式）

### GPU 数据（torch.profiler 导出）

```text
pytorch_profiling/
└── *.pt.trace.json
```

- 建议采集时开启 `profile_memory=True`（内存比对）与 `record_shapes=True`（Shape 匹配）

### Step 要求

- 建议只采集一个 step 的数据；多 step 数据会混入预热/抖动，影响 E2E、通信等待等判断
- 多 step 场景需固定比对步：`--compare_args "--base_step=<基准step> --comparison_step=<比对step>"`（两者必须成对配置，且 step 需实际存在）

## 2. 参数选择决策

按用户关注点选择开关（设置了任意开关后，工具只执行已设置的比对能力；全部不设则开启全部）：

| 用户诉求 | 推荐参数 |
|---|---|
| 快速定界：差异来自计算/通信/调度哪个方向 | `--enable_profiling_compare` |
| 哪些算子劣化了 | `--enable_operator_compare` |
| 通信慢在哪 | `--enable_communication_compare` |
| 内存涨在哪 | `--enable_memory_compare` |
| NPU vs NPU 看 Kernel 细节 | `--enable_kernel_compare`（可加 `--use_kernel_type` 提速） |
| Host 侧下发慢 | `--enable_api_compare` |
| 全量分析（默认） | 不传任何 `--enable_*` 开关 |

### 辅助参数

| 参数 | 使用时机 |
|---|---|
| `--disable_details` | 只要统计结论、明细 Sheet 太大或比对太慢时 |
| `--disable_module` | 无需模块级比对（双方都有 Python Function 时默认输出 Module Sheet） |
| `--use_input_shape` | 同名算子多 Shape、需精确匹配时 |
| `--max_kernel_num=N`（最小 4） | 需要更细粒度的算子比对（逐层下钻子算子）时 |
| `--op_name_map={'a':'b'}` | GPU/NPU 算子命名不一致（如融合算子改名）时 |
| `--gpu_flow_cat=<标识>` | GPU trace 中 Device Duration 全为 0 时，从 chrome://tracing 的 Flow events 找连线标识填入 |
| `--force` | 提示文件属主/大小校验失败时强制执行 |
| `--debug` | compare 报错需要定位原因时 |

## 3. 输出与后续分析

- compare 成功后在输出目录生成 `performance_comparison_result_<时间戳>.xlsx`，并在终端打印总体比对结果（含 `Mem Usage`）
- `run_compare.py` 会自动定位最新 xlsx 并调用 `main_analyzer.py` 完成 Sheet 级解析、HTML 报告与中文 xlsx 生成
- 常见报错排查：
  - `Sheet 不存在`：对应 `--enable_*` 开关未开启，或数据类型不支持（如 MindSpore 不支持算子/内存比对）
  - `无明细 Sheet`：`--disable_details` 已设置
  - `Not minimal profiling` 警告：E2E 时间存在性能膨胀，影响通信/调度耗时判断，建议按最小化采集重新采集数据
