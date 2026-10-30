# 现象导览（中断 / 精度 / 性能）

用户先给现象，这份导览只做一件事：把现象对到一条流程 ref-id。每条流程的正文在 `references/methodologies/<ref-id>.yaml`，导览行里的 ref-id 就是文件名去掉 `.yaml`。判不出属于哪一节、也不要用「你是哪类用户」去问。

## 中断（跑不起来、跑着停了、报错退出）

这类问题在问：任务为什么没有按预期跑完。

- 进程还在、但一步也不往下走，日志不报错 → `asys collect -r=stacktrace --remote=<pid> --all --quiet` 取调用栈，看栈里没有 CANN 函数（任务没下发）/ 有 SendTask（卡在下发）/ 有 Synchronize（卡在执行）→ `ascend-process-hang-triage`
- 跑着跑着打印一段报错就退出了 → 在 plog 里 `grep -rn ERROR` 取首报错，按首报错分层：错误码 / 接口调用 / 任务执行 / 心跳丢失 / 资源未释放 → `ascend-process-interrupt-triage`
- 命令刚起来就挂：import 报错、模块找不到、算子重复注册 → 先分「版本与安装面」还是「代码漂移面」，别直接升级 → `msllm-startup-version-env-triage`（推理侧量化模型拉不起来另见 `glm-quantized-startup-triage`）
- 被系统杀掉，或明确报内存不足（out of memory / 207001）→ 先看是谁申请的：C 标准接口、CANN Host 内存还是 Device 内存，再按 mem_stats 统计核对 → `ascend-oom-triage`
- 多机任务里出现 EI/EJ 开头的故障码，或某个 rank 一直在等对端 → 先确认是不是通信的问题，再收全量节点日志找根节点（报错 rank 常常只是在等）→ `ascend-hccl-comm-fault-triage`
- 报错里有 AI Core Error / EZ9999 / fault kernel_name，或怀疑卡本身坏了 → 按 RAS 硬件 → NPU 硬件 → 软件越界 → msaicerr 分析四层分流 → `ascend-aicore-error-triage`

判不出属于哪支时问：**进程还在吗？在的话把 PID 给我；已经退出了就把第一行报错贴出来。**

## 精度（结果不对、对不上、不稳定）

这类问题在问：结果为什么和应有的值不一样。

- loss 跟 GPU 或基线对不上、变成 NaN、溢出 → 先做 CheckList 排除非算子因素，再固定随机性、缩小规模复现，按现象分流 → `ascend-train-precision-triage`
- 同一份输入跑两次结果不一样，或换个 batch 位置就变 → 先分清是「重复跑不一致」还是「跨 batch 组合不一致」，再确认确定性开关有没有被业务代码中途重置 → `ascend-determinism-triage`
- 没有报错，但输出乱码、答非所问、生僻字重复 → 先按输入预处理 / 前向计算 / 传输与后处理三段定界，再按五条机制分流 → `ascend-garbled-output-triage`
- 已经知道从第几层、第几个 token 或哪个算子开始不对 → 先定阈值，找首个超标节点并过三关，再溯源到引入点 → `precision-first-divergence-triage`（只想单独验一个算子见 `single-operator-accuracy-verification`）
- 推理服务（vLLM）答得不对，或离线 om 模型精度不达标 → 先把问题场景与标杆场景对齐，找到首个差异 token 再 dump 比对 → `vllm-infer-precision-triage` / `ascend-om-infer-precision-triage`
- RL 场景里 reward 对不上、训练侧和推理侧对不齐 → 先约定指标口径、对齐环境与权重，再用首步 bad case 定界是训还是推 → `rl-precision-alignment-overview`

判不出属于哪支时问：**是跟基线或 GPU 比出来的差异，还是同一条命令自己跑两次都不一样？**

## 性能（变慢、加卡不加速、某张卡慢）

这类问题在问：时间花到哪去了、为什么规模上去了却没变快。

- 整体变慢了，但说不清慢在哪 → 先把耗时拆成计算、通信未掩盖、空闲三块，只定方向不下钻，再逐级拆解做守恒自检 → `performance-delimiting-and-comparison` / `profiler-breakdown-method`
- 加卡不加速，或通信耗时占比明显涨了 → 看一个迭代内有没有卡的等待时长比例 > 0.2，再分慢卡还是链路 → `msprof-comm-bottleneck-thresholds`
- 多卡里个别卡明显慢，或有的卡「算得少还显得快」→ 跑集群分析能力逐项定性，只在六类里下结论 → `multi-rank-slow-rank-detection`
- 单个算子慢，想知道下一步动哪里 → 按七列 pipe 数据判流水模式与 Bound 类型，再按策略表选方向 → `operator-bottleneck-attribution`
- 卡上利用率上不去，像在等 CPU 下发 → Host Bound 三条判据同时成立才算，缺一条只写证据不足 → `profiler-host-bound-triage`（要下 Host 侧结论先过证据门槛，见 `hostbound-evidence-gate`）
- 显存越跑越高、接近 OOM 或碎片化 → 先确认采集数据可用度，再按曲线形态分泄漏 / OOM / 碎片 → `memory-leak-and-oom-triage`

判不出属于哪支时问：**是端到端整体变慢，还是某一张卡、某一个算子单独慢？**
