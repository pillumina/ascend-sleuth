# 官方工具独立适配说明

本 Skill 不包含、复制或修改下列官方工具源码。客户机可按与 Skill 分离的官方目录部署；Skill 只消费其输出或生成调用计划。

| 模块 | 官方入口 | 输入 | 输出 | 接入方式 |
|---|---|---|---|---|
| function_monitor | `misc/function_monitor/function_monitor.py`，`log2trace.py` | PyTorch 业务函数/代码块；可选 libkperf | `function_monitor_<pid>.log`、Chrome Trace JSON | 以函数时间区间和 PMU args 输入报告；不自动插桩 |
| gil_tracer | `misc/gil_tracer/gil_trace_record.py`，`gil_trace_convert.py` | Linux root、sysTrace、PID | `GIL_<pid>_rank_<rank>.json`、Chrome Trace JSON | 以 take/drop/推导 hold 关联 Python 线程；不自动开启 |
| host_analyzer | `misc/host_analyzer/entrance.py bind` | NPU 拓扑、进程/线程/IRQ、JSON 配置 | 日志与系统 affinity 改动 | 只生成建议 JSON 和验证计划；执行前需确认 |
| msprof | `analysis/msprof/msprof.py` | CANN collection-dir | SQLite、CSV、`msprof_*.json` | 导入 Host CPU/Runtime API 与 Device 时间线；离线解析可用 |

部署检查：function_monitor 需要 Python/PyTorch，PMU 模式还需要 libkperf/权限；gil_tracer 需要 Linux/root/sysTrace；host_analyzer 默认策略需要 Ascend `npu-smi`、`lscpu`、`taskset` 和常见 `/proc`/`/sys` 节点；msprof 原始采集依赖 CANN，而导出/离线分析依赖相应 msprof 分析环境。
