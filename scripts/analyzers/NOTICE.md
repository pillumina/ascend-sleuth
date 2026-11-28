# 来源、许可与本地改动

本地分析脚本来自 hu669293657/skills，固定提交为 bf82e886ddda0a9955c2d5422f50b0b4caeb80b6。原作者为 hu669293657。逐项对应关系见 PROVENANCE.yaml，客户采集脚本见 ../collectors/PROVENANCE.yaml。

上游未声明开源许可证。迁入方此前确认了作者对迁入和再分发的口头授权，当前尚无书面许可记录。

## 文件组织

每个分析器的实现放在 scripts/analyzers/<name>/ 中，run.py 是 Sleuth 调用入口。保留运行所需的脚本、模板、配套数据和参考资料。

客户采集脚本位于 scripts/collectors/ascend-dump/ 和 scripts/collectors/cpu-host/。CPU ftrace 采集与分析器共用同一份脚本，通过采集器清单打包。

vLLM 调优资料从原作者仓库查询。

## 本轮同步

- 环境快照引入机器可读兼容性目录及查询实现。
- 单卡 Prof 更新设备身份识别和逐次 kernel 归因，补齐所需模块。
- 集群分析更新已有导出识别、Rank 时间图、通信分类排行和瓶颈报告。
- 集群对比更新时间单位、Step 配对、通信算子聚合和缓存行为。
- CPU 分析和采集更新产品识别、非默认安装路径、绑核方案产物和依赖。

## 本地执行约定

分析器通过 Sleuth 适配器调用，输出 result.json。单卡 Prof 使用标准库路径。集群分析使用内置 fallback，集群对比跳过需要外部工具的高级分析。集群内双卡差异保留 JSON，独立单卡入口负责 Prof 对比。

绑核建议保存到 bind_design.json，配套脚本为 cpu_binder_simple.py。适配器生成建议文件，现场执行由工程师按变更要求处理。

环境快照保留采集失败与目标进程证据。日志归档先解包。原有 BOM 读取、zip 路径校验和 Windows UTF-8 输出修复继续保留。

## 按需查询的上游内容

完整 Prof 工作簿和单卡 HTML 渲染、环境快照 HTML 模板、客户定制绑核生成入口，以及发行维护脚本可从上游查询。当前清单只登记现有分析和采集调用链。

[原作者仓库](https://github.com/hu669293657/skills/tree/bf82e886ddda0a9955c2d5422f50b0b4caeb80b6)
