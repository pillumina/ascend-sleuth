# 示例报告说明

本目录存放由本 Skill 分析器对模拟 trace（含 NET_RX 软中断热点、调度延迟、CPU 负载不均衡、nvme0q2 中断、CPU5 降频等典型模式）端到端生成的真实示例报告，供交付前对照格式与内容深度。

| 文件 | 说明 |
|------|------|
| `sample_report.md` | 中文 Markdown 报告：14 节固定结构，含结论摘要、证据总表、问题详情（Metric/Value/Threshold/Evidence/Confidence 五要素）、指标中文释义 |
| `sample_report.html` | 单文件离线 HTML 报告（inline SVG 图表，无 CDN/外部依赖），双击即可用浏览器打开，内容与 MD 版一致 |

对应的报告骨架模板见 `../templates/report_template.md`（用于数据缺失时的人工撰写或结构定制）。

示例场景概要：
- Host 状态 CRITICAL：NET_RX 软中断集中单核、调度延迟 p95 超阈值
- 中断统计含 eth0（网络收包）与 nvme0q2（存储队列中断）两类热点
- CPU 5 出现低频运行样本（1200/2400 MHz，低频占比 90%），因该核负载低未触发高负载降频告警，可对照 `analyzer/diagnosis.py` 中 CPU_FREQUENCY_LOW 的组合判断逻辑
