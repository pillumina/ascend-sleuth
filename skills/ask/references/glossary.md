# 新人前 10 分钟会碰到的词（术语 | 一句话解释 | 相关 ref-id）
plog | Host 侧应用进程打的日志，报错先从这里找 | ascend-log-classification
首报错 | 日志里第一条 ERROR，定位从它开始而不是最后一条 | ascend-process-interrupt-triage
系统类日志 | Device 侧产生，EP 形态要用 msnpureport 导出 | ascend-log-locations
trace 日志 | 维测信息先记内存，出错或进程结束才落盘 | ascend-trace-logs
npu-smi | 查卡状态、显存占用与健康状态的命令 | npu-smi-950-device-ops
OOM（207001） | 内存申请失败，先分 Device 显存还是 Host 内存 | ascend-oom-triage
集合通信 | 多卡之间交换数据的操作（all_reduce 一类） | ascend-hccl-comm-fault-triage
EI 码 | 通信库的故障码，按建链与执行阶段分表 | hccl-error-codes
msprof | 采性能数据的工具，产出 PROF_* 目录 | msprof-collect-parse
msprobe | 采精度数据的工具，按算子存输入输出 | msprobe-data-dump
标杆 | 用来对照的一侧：GPU 结果或历史正常版本 | vllm-infer-precision-triage
溢出（NaN/Inf） | 算出非有限值，先找第一个出现的那一步 | msprobe-overflow-check
确定性 | 同一输入重复跑，结果是否逐比特一致 | batch-consistency-and-determinism-switches
batch 一致性 | 同一 token 换 batch 位置或大小，输出是否一致 | batch-consistency-and-determinism-switches
慢卡 | 多卡里拖慢整体的一张，判据看等待时长比例 | msprof-comm-bottleneck-thresholds
Host Bound | 设备在等 CPU 下发任务，不是算得慢 | profiler-host-bound-triage
绑核 | 把进程或线程固定到指定 CPU 核，减少迁移 | cpu-binding-inspection-procedure
asys | 收集故障现场（日志、调用栈）的工具 | ascend-asys
mssanitizer | 查算子越界、踩踏、竞争、未初始化 | mssanitizer
EP / RC 形态 | 部署形态：EP 是标准形态，RC 是开放形态 | ascend-log-locations
精度模式 | 离线模型转换时决定算子用 fp16 还是 fp32 | atc-precision-mode-and-switches
实验基线 | 改动前的同条件耗时，比性能前先钉住 | operator-tuning-experiment-method
