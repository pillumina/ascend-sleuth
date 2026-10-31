# 常见故障模式库

> **定位声明**：本库是"排查线索库"，提供特征关键字、排查路径与常见根因排序，**不是结论库**。任何模式命中都必须以日志证据支撑（铁律 2），最终结论按三级置信度标注。关键字命中有噪声是正常的——用 stats 看分布、用 context 看原文，再判断是否真命中。

## 使用方法

1. 按问题现象选定场景章节（拉起失败 / 训练中断 / 推理中断）
2. 把对应章节的"提取关键字"拼进 `extract --keywords`（叠加在默认模式之上）
3. 按"排查路径"顺序取证；"常见根因"仅作为假设清单，逐个找证据排除或确认

## 通用排查路径（任何场景先做）

1. 锁定时间窗（±10 分钟）→ 2. scan 确认日志覆盖 → 3. extract + stats 看错误分布 → 4. **定位"第一个异常"** → 5. 按场景章节下钻

**首个错误原则**：中断/失败类问题 80% 的线索在"第一个异常"里，后续大量报错多为连锁反应。特别注意：
- **超时报错的节点往往不是根因节点**——是它等别的节点等超时了，先挂的才是根因
- 跨文件找最早异常前，必须做多机时钟对齐检查（见 `log-structure.md` 第四节）
- "第一个异常"要区分：根因事件（如 device ECC 错误）vs 首个症状（如各 rank 集体报 timeout）

## 场景一：模型拉起失败

**提取关键字**：`version,mismatch,not found,cannot open shared object,permission,denied,load,rank,rendezvous,port,init`

### 1.1 环境与版本类

| 要素 | 内容 |
|---|---|
| 特征 | `version mismatch`、`not compatible`、`cannot open shared object file`（动态库加载失败）、`No such file or directory`、`permission denied` |
| 排查路径 | ① 取拉起时段最早的 ERROR 及其上下文 ② 对照环境信息表（驱动/固件/CANN/框架版本组合）③ 动态库报错看 `LD_LIBRARY_PATH` 相关变量与库实际路径 |
| 常见根因 | 驱动/固件/CANN/框架版本不匹配；环境变量缺失或指向错误；容器内 toolkit/驱动未正确挂载；运行用户权限/属组问题；残留旧进程占用资源 |

### 1.2 设备状态类

| 要素 | 内容 |
|---|---|
| 特征 | `device ... abnormal/fault/offline/unavailable/busy`、`device reset`、拉起即失败且伴随 dmesg 设备事件 |
| 排查路径 | ① device 日志看问题卡状态 ② dmesg 看该卡内核级事件（ECC/PCIe/复位）③ 向用户索取 `npu-smi info` 输出 |
| 常见根因 | 设备残留进程占用（上次任务未退干净）；设备处于异常态需复位；ECC 不可纠错后设备被隔离；掉卡/链路异常 |

### 1.3 分布式初始化类

| 要素 | 内容 |
|---|---|
| 特征 | `HCCL ... init ... fail`、`rank table`、`rendezvous`、`connection refused`、`network unreachable`、`port ... already in use`、`hostname ... resolve` |
| 排查路径 | ① 确认失败发生在哪一步（建链前的网络问题 vs 建链中的 HCCL 问题）② 检查 rank table/组网配置与实际节点 ③ 网络不通类看 dmesg 网卡事件 |
| 常见根因 | rank table/主机名解析/端口占用；参数面网络不通（路由/防火墙/网卡）；HCCL 初始化参数与组网不匹配；个别节点服务未起 |

### 1.4 框架与模型类

| 要素 | 内容 |
|---|---|
| 特征 | `load ... weight/checkpoint failed`、`config`、`compile`、`op ... not support`、`shape`、`dtype`、`out of memory`（拉起即 OOM） |
| 排查路径 | ① 框架日志最早的 Python 栈 ② 权重/配置文件路径核对 ③ 算子编译失败看具体算子名 |
| 常见根因 | 权重路径错误或文件损坏；配置项错误；算子不支持/编译失败；batch size 或并行配置导致显存不足 |

## 场景二：训练中断

**提取关键字**：`watchdog,timeout,rank,nan,inf,loss,oom,kill,signal,reset,ecc`

### 2.1 通信类（最常见）

**watchdog / 集合通信超时**：

| 要素 | 内容 |
|---|---|
| 特征 | `watchdog`、`timeout`、`timed out`、`waiting for`、多个 rank 同时报通信等待；HCCL 相关错误 |
| 排查路径 | ① **找最早停止输出/最早异常的 rank**（它大概率是根因）② 对该 rank 所在节点做下钻：host 日志、dmesg、device 日志 ③ 其余 rank 的超时报错作为"症状"证据即可 |
| 常见根因 | 某 rank 算子 hang 或 host 侧卡死导致其他 rank 集体超时；参数面网络抖动/光模块异常/丢包；个别节点负载异常（CPU 打满、内存回收卡顿） |

**网络类**：dmesg 中网卡 up/down、光模块告警、丢包/重传统计异常 → 建议用户做网络专项检查。

### 2.2 Device 侧故障

| 特征 | 指向 | 排查路径 |
|---|---|---|
| `ECC`（可纠错） | 内存翻转，偶发可纠正 | 看发生频率与累积量；孤立一次通常不致中断，密集出现需关注 |
| `ECC`（不可纠错）/ device fault | 设备级故障 | dmesg + device 日志交叉验证；常伴随 device reset |
| device OOM | 显存耗尽 | 中断前的显存增长轨迹（框架日志显存输出）；batch/梯度累积/内存泄漏 |
| 算子错误 + core dump | 算子执行异常 | 框架日志找算子名与栈；需要 dump 分析时联动 `ascend-dump-analyzer` 或引导采集 |
| `device reset/offline` | 设备复位/掉卡 | 找 reset 之前的第一个设备事件（reset 本身多为结果） |

### 2.3 Host 侧故障

| 特征 | 指向 | 排查路径 |
|---|---|---|
| dmesg `Out of memory` / `Killed process` | host OOM killer 杀进程 | dmesg 找被杀进程名与时刻，对齐框架日志中断点 |
| `Segmentation fault` / `SIGABRT` / core dump | 进程崩溃 | 栈首行通常在框架日志；注意区分 host 侧栈与 device 侧错误 |
| 磁盘满 `No space left on device` | checkpoint/日志写满 | 检查中断时刻磁盘相关报错 |
| 训练进程被人为 kill（SIGTERM） | 运维操作/调度系统回收 | 结合"已采取措施"与作业调度日志，勿误判为故障 |

### 2.4 数值类

`loss=nan/inf`、梯度爆炸告警：通常是中断**之前**的先兆异常（后续可能引发算子错误或 watchdog）。排查学习率、数据（脏数据/溢出）、混合精度配置；在时间线上作为先导事件标注。

### 2.5 系统级

| 特征 | 指向 | 排查路径 |
|---|---|---|
| 日志时间出现大段空洞后从头开始 | 节点重启 | `uptime`/`last reboot`；找重启原因（掉电/panic/运维） |
| kernel panic | 内核崩溃 | dmesg 尾部；多为驱动/硬件触发 |
| 各节点时间戳整体错位 | NTP 跳变误导 | 时钟对齐检查（`log-structure.md` 第四节），避免误判事件顺序 |

## 场景三：推理中断 / 服务异常

**提取关键字**：`crash,signal,timeout,request,oom,leak,restart,upstream`

| 特征 | 指向 | 排查路径 |
|---|---|---|
| 服务进程崩溃（信号/栈） | 单请求触发缺陷或资源越界 | 崩溃前最后处理的请求日志；找首个异常请求 |
| 运行一段时间后 OOM | 显存/内存泄漏累积 | 对比服务启动初期与崩溃前的资源类日志；请求量与内存增长曲线 |
| 大量请求超时后服务假死 | 长尾/雪崩 | 找第一个超时请求及其处理线程日志；上游依赖是否先故障 |
| 单实例故障、整体降级 | 个别实例问题 | 按实例分文件看首个异常实例 |

## 附：分场景提取关键字速查（可直接拼进 --keywords）

| 场景 | 关键字 |
|---|---|
| 拉起失败 | `version,mismatch,compatible,shared object,permission,denied,not found,rank table,rendezvous,connection refused,network unreachable,port,init,load,weight,checkpoint,compile` |
| 训练中断 | `watchdog,timeout,timed out,rank,nan,inf,loss,oom,killed,signal,segfault,core dump,reset,ecc,offline,panic,reboot` |
| 推理中断 | `crash,timeout,request,oom,leak,restart,signal,upstream,refuse` |
| 通信专项 | `hccl,link,network,socket,connect,route,nic,光模块,断链` |
| 设备专项 | `device,npu,ecc,temperature,power,clock,reset,abnormal` |

> 中文关键字（如"断链"）仅适用于中文日志；客户日志多为英文，优先用英文关键字。
