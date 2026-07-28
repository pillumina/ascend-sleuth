# Script Integration（深度排查工具调用约定）

`/diagnose` 步骤 5 深度排查（Tier 2 未命中）时调用这些已有脚本。

## category → 默认工具

诊断的 category（interrupt / precision / performance）决定默认调哪个 Script：

| category | 默认 Script | 为什么 |
|---|---|---|
| interrupt | 日志分析 / core dump | 看错误签名、栈、崩溃点 |
| precision | `mem-analyze` | tensor 对比基线、数值偏差 |
| performance | `ascend-profile-analyze` / `bench-run` | op 级耗时、通信占比、基线对比 |

## 完整集成点

| Script | 何时调 | 输入 | agent 消费的输出 |
|---|---|---|---|
| `ascend-profile-analyze` | performance 类，Tier 2 未命中，有 profiler 数据 | profiling 目录 | 生成的 `report.md`（op 级耗时/通信占比） |
| `mem-analyze` | precision 类，Tier 2 未命中 | tensor dump 路径 + 参考基线 | 数值偏差表 |
| `bench-run` | performance 类，需基线对比 | 模型/配置 | 吞吐/step time 对比 |
| `collect-profiling` | `/diagnose` 发现缺 profiler 数据时主动收集 | 训练启动配置 | profiling 目录 |
| `machine-ops` | 环境健康自检（`/diagnose` 步骤 1） | 无 | npu-smi / hccl 拓扑状态 |
| `log-format-contracts/*` | 契约文件，非脚本 | —— | `quickly_check` 优先匹配的稳定错误标识（见下） |

## 调用约定（硬要求）

- agent 调 Script 后**只读生成的报告文件**，不把 stdout 全量灌进 context（日志裁剪原则同样适用——context 要留给真正的大头）
- Script 的输出格式（报告路径、字段）写在本文件，由体系维护人和 Script 作者共同维护
- Script 失败 → 不阻塞诊断，降级到 Tier 3 关键词检索 + 人工分析

## 日志格式契约（治 quickly_check 衰减）

`quickly_check` 的 regex 会因框架升级、日志格式变化而失效——这是必然事件。真正解法是让各框架承诺一组稳定的错误标识（`error_code` 字段或保证向后兼容的子串如 `[HCCL_E_TIMEOUT]`），契约存在 `log-format-contracts/`。`quickly_check` 优先匹配稳定标识，而非自由文本。契约建立前，primary + fallback 双 regex 是权宜之计。
