# Compare 性能比对分析方法论

> 本文档从模型性能优化专家视角，系统总结 msprof-analyze compare 输出件各 Sheet 页的指标含义、分析思路和实践经验。
> 生成 HTML 报告时应同时参考 JSON 中间件数据与本方法论，输出更具专业性的分析结论。

## 一、分析框架总览

性能比对的核心分析路径遵循**"先定界方向，再定位瓶颈，最后下钻根因"**的三步法：

```
第一步：OverallMetrics → 定界（计算/通信/调度，哪个方向有问题？）
第二步：Statistic 页 → 定位（哪个算子/模块/Kernel 劣化最严重？）
第三步：Detail 页 → 下钻（具体的 Kernel 详情、调用栈、Shape 变化）
```

## 二、各 Sheet 指标详解与分析方法

### 1. OverallMetrics（总体性能比对）

#### 核心指标

| 指标 | 含义 | 分析要点 |
|---|---|---|
| E2E Time | 端到端总耗时，计算流从开始到结束的总时间 | 比对双方 E2E 差异是性能变化的最直观体现。若标注 Not minimal profiling，说明采集时存在额外开销，E2E 可能膨胀 |
| Computing Time | 计算流所有 event 耗时总和（重叠部分只计一次） | 增大时需进一步看算子性能或 Kernel 性能 |
| Uncovered Communication Time | 通信未掩盖耗时（含卡间等待），即通信未被计算并行掩盖的部分 | 增大时分析通信性能；若通信无劣化算子，说明计算与通信并行度变差 |
| Free Time | 调度空闲 = E2E - 算子耗时 - 通信不可掩盖耗时 | 包含 SDMA 拷贝时间。增大说明设备闲置增多，可能是 Host 下发瓶颈或流水线气泡 |
| Duration Ratio | 各维度耗时占 E2E 的比例 | 用于判断该维度是否为瓶颈（占比 > 50% 通常值得关注） |
| Diff Duration(ms) | 比对值 - 基准值 | 正数=劣化，负数=改善 |
| Diff Ratio | 比对值 / 基准值 | > 1.0 劣化，< 1.0 改善，基准为 0 时显示 inf |

#### 二级指标（NPU 场景）

| 指标 | 含义 | 分析要点 |
|---|---|---|
| Flash Attention (Fwd/Bwd) (Cube/Vector) | FA 前向/反向的 Cube 计算 vs Vector 转换 | Cube 是核心计算，Vector 是 TransData 等转换算子。Vector 占比高说明数据布局转换开销大 |
| Conv (Fwd/Bwd) (Cube/Vector) | Conv 前向/反向拆解 | 同上，关注 Cube/Vector 比例 |
| Matmul (Cube/Vector) | 矩阵乘的 Cube 计算 vs Vector 转换 | Matmul 是 LLM 推理最核心的计算，Cube 耗时应占主导 |
| Vector (Trans/No Trans) | 转换类 vs 非转换类 Vector | Trans 类（Cast、Transpose、TransData）过多意味着数据格式转换开销 |
| SDMA (Tensor Move) | 拷贝类任务 | 过高说明 H2D/D2D 数据搬运频繁 |
| Wait / Transmit | 通信域内的等待 vs 传输 | Wait 占比高说明同步等待严重（可能是 AllReduce 阻塞）；Transmit 高说明带宽瓶颈 |

#### 分析经验

1. **趋势判断优先**：先看 E2E 是改善还是劣化，再分别看三大维度的变化方向。改善和劣化可能同时存在
2. **贡献占比陷阱**：贡献占比 = |维度差异| / |E2E差异|。当 E2E 差异很小但某维度变化大时，占比可能 > 100%，这并不意味着该维度"造成"了全部差异
3. **Not minimal profiling 警告**：出现此标记时，E2E 存在性能膨胀，通信和调度耗时的绝对值不可信，应关注比率而非绝对值
4. **Free Time 剧增**：如果 Free Time 比率剧增（如从 1x 到 3x），通常是流水线气泡增大或 Host 下发效率下降，而非通信或计算本身的问题
5. **极端改善识别**：通信算子比率 < 0.1（如 allreduce 从 33000us 降至 400us）通常意味着通信策略发生根本性变化（如从同步切到异步），需确认是否为预期行为

### 2. OperatorCompareStatistic（算子统计比对）

#### 核心指标

| 指标 | 含义 | 分析要点 |
|---|---|---|
| Base/Comparison Device Duration(ms) | 基准/比对算子在 device 上执行总耗时 | 按算子名聚合后的总和 |
| Base/Comparison Operator Number | 基准/比对算子调用次数 | 次数变化说明模型结构或执行路径变化 |
| Diff Duration(ms) | 比对耗时 - 基准耗时 | 按 diff 降序排列定位 TOP 劣化算子 |
| Diff Ratio | 比对耗时 / 基准耗时 | > 1.0 劣化，红色标记 |

#### 分析经验

1. **集中度判断**：Top 10 算子劣化量占总劣化量的比例 > 80% 说明问题集中，可针对性优化；< 50% 说明劣化分散，可能是系统性问题
2. **调用次数变化**：如果 Number 列变化，说明模型结构变化（如新增算子或执行路径不同），需先确认比对基准是否合理
3. **GPU vs NPU 场景**：GPU 和 NPU 算子名不同（如 GPU 的 `aten::flash_attention` vs NPU 的自定义算子），需配合 `--op_name_map` 映射

### 3. OperatorCompare（算子明细比对）

#### 核心指标

| 指标 | 含义 |
|---|---|
| Kernel Details | 算子下发的所有 Kernel 信息（名称、task id、task type、input shape、耗时） |
| Device Duration(us) | 该算子下发到 device 的所有 Kernel 耗时总和 |
| Input Shape / Input Type | 算子输入的 Shape 和数据类型 |

#### 分析经验

1. **Kernel 数量变化**：基准侧 3 个 Kernel、比对侧 5 个 Kernel，说明算子拆分方式变化，可能引入额外 TransData
2. **Shape 不匹配**：如果 Input Shape 不同，说明数据流发生变化，需检查上游算子输出
3. **关联统计页**：先从 Statistic 页定位 TOP 劣化算子名，再到 Detail 页搜索该算子查看 Kernel 级详情

### 4. ModuleCompareStatistic（模块统计比对）

#### 核心指标

| 指标 | 含义 |
|---|---|
| Module Class / Module Level / Module Name | 模块的类名、层级、唯一标识 |
| [ TOTAL ] 行 | 该模块的总体情况（含子模块） |
| Device Self Time(ms) | 排除子模块的自身耗时 |
| Device Total Time(ms) | 包含子模块的总耗时 |
| Diff Total Ratio | 比对 Total Time / 基准 Total Time |
| Base/Comparison Call Stack | 调用栈，用于定位代码行 |

#### 分析经验

1. **先看 [ TOTAL ] 行**：筛选 Operator Name 为 `[ TOTAL ]` 的行，按 Device Total Time Diff 降序定位劣化模块
2. **Self vs Total**：Self Time 差异大说明该模块自身算子劣化；Total 差异大但 Self 差异小说明子模块劣化
3. **调用栈价值**：调用栈直接指向代码文件和行号，是定位代码级问题的最直接途径
4. **需 with_stack 采集**：模块比对需要采集时开启 `with_stack` 选项，否则无 Python Function 事件

### 5. ModuleCompare（模块明细比对）

#### 分析经验

1. **TOTAL 行 + 明细行配合**：TOTAL 行看模块整体，明细行看具体算子
2. **调用栈对比**：如果基准和比对的调用栈不同，说明代码执行路径发生变化
3. **时间单位为 us**：与 Statistic 页的 ms 不同，注意单位转换

### 6. CommunicationCompare（通信比对）

#### 核心指标

| 指标 | 含义 |
|---|---|
| Communication OP Name | 通信算子名（如 allreduce、alltoall、allgather、reducescatter） |
| Task Name | Task 级明细（仅 NPU），如 Reduce_Inline、Memcpy、Notify_Record、Notify_Wait |
| Total/Avg/Max/Min Duration(us) | 通信算子的统计指标 |
| Diff Ratio | 比对总耗时 / 基准总耗时 |

#### 分析经验

1. **Wait vs Transmit**：从 OverallMetrics 的通信域拆解判断瓶颈是等待（同步）还是传输（带宽）
2. **Notify_Wait 异常**：Notify_Wait 耗时剧增通常意味着流水线同步点增多或阻塞加重
3. **极端改善**：allreduce 从 33000us 降至 400us（ratio=0.013），通常是通信策略根本性变化（如从同步 AllReduce 切为异步或融合通信）
4. **Task 明细价值**：summary 行只看总体，Task 明细行能区分是 Reduce_Inline 劣化还是 Memcpy 劣化
5. **alltoall 是 MoE 关键**：在 MoE 模型中，alltoall 通信占比极高，其性能直接影响整体吞吐

### 7. MemoryCompareStatistic（内存统计比对）

#### 核心指标

| 指标 | 含义 |
|---|---|
| Base/Comparison Allocated Memory(MB) | 基准/比对算子分配的 device 内存 |
| Diff Memory(MB) | 比对内存 - 基准内存 |
| Diff Ratio | 比对内存 / 基准内存 |

#### 分析经验

1. **全零内存场景**：NPU vs NPU 比对时，如果未开启 `profile_memory=True`，所有内存值为 0。此时应提示用户检查采集配置
2. **无显著算子但有总差异**：如果没有明显占用大的算子，问题在于内存释放（持有时间过久），需用 TensorBoard 或 MindStudio Insight 分析内存生命周期
3. **内存增长 vs 内存泄漏**：比对是单 step 数据，内存增长可能是模型结构变化导致，不一定是泄漏

### 8. KernelCompare（Kernel 比对）

#### 核心指标

| 指标 | 含义 |
|---|---|
| Kernel名称 + Input Shape | 按 Kernel Type + Input Shape 分组，基准与比对共用同一 Shape |
| Total/Avg/Max/Min Duration(us) | Kernel 统计指标，分基准和比对两组 |
| Calls | 调用次数，基准和比对分别统计 |
| Diff Total/Avg Ratio | 总耗时比率 / 平均耗时比率 |
| 输入数据量 | Shape 各维度相乘后所有 tensor 求和（如 "128,4096;4096,10240" = 524288 + 41943040 = 42.5M elements） |

#### 通信算子与计算算子分离

报告中将 Kernel 分为两类分别分析：
- **通信算子**（`hcom_` 前缀）：单独折叠展示，不分析 Shape 和方差（通信等待时间取决于网络和同步，不反映负载不均）
- **计算算子**：Top10 绝对耗时 + 负载均衡分析 + 多 Shape 分布

#### 分析经验

1. **输入数据量说明**：基准与比对共用同一 Shape 列，因此同一行的数据量相同。数据量的价值在于横向对比不同算子的计算密度（同样数据量谁更慢），以及同名算子不同 Shape 行之间的数据量差异
2. **calls 变化**：base_calls ≠ comp_calls 说明执行路径变化（模型结构或调度策略改变），这是比数据量变化更重要的信号
3. **单次耗时 vs 调用次数**：Calls 不变但 Avg Duration 增加 → 单次执行效率下降；Calls 增加但 Avg 不变 → 算子被额外调用
4. **显著劣化阈值**：ratio > 1.05 视为显著劣化，需重点关注；ratio > 1.10 为严重劣化
5. **负载均衡判断**：仅对 calls > 10 的计算算子做 max/min 方差分析。方差 > 2x 标记为轻微，> 3x 为显著，> 5x 为严重。calls < 10 的小算子方差不具统计意义
6. **同名不同 Shape**：同一 Kernel 名称（如 QuantMatmulV2）的多行对应不同层/专家的输入，数据量差异反映各层负载分配。例如 QuantMatmulV2 三种 Shape 分别为 42.5M/21.5M/10.8M，说明不同层的矩阵维度差异 4 倍
7. **仅 NPU vs NPU**：Kernel 比对仅在 NPU 与 NPU 比对场景下可用

### 9. KernelTypeCompare（Kernel 类型比对）

#### 分析经验

1. **简化模式**：使用 `--use_kernel_type` 时输出，按 Kernel Type + Core Type 分组，适合快速概览
2. **Cube vs Vector**：关注 Cube 类 Kernel（核心计算）和 Vector 类 Kernel（转换算子）的总体趋势
3. **类型聚合**：按 Kernel Type 聚合后，可以快速判断哪类算子整体劣化

### 10. ApiCompare（API 比对）

#### 核心指标

| 指标 | 含义 |
|---|---|
| Total Duration(ms) | API 总耗时（含子 event） |
| Self Time(ms) | Self 耗时（排除子 event） |
| Avg Duration(ms) | 平均单次耗时 |
| Calls | 调用次数 |
| Diff Self/Avg/Calls Ratio | Self/平均/次数的比率 |

#### 分析经验

1. **Self Time 是关键**：Total Duration 包含子 event，Self Time 才反映该 API 自身的执行效率
2. **纯耗时变化 vs 调用次数变化**：calls_ratio=1.0 说明调用次数不变，diff 来自单次耗时变化；calls_ratio≠1.0 说明执行路径变化
3. **Host 侧瓶颈**：如果大量 API 的 Self Time 都微增（如各 +1ms），可能是 Host 侧调度效率下降，而非单个 API 问题
4. **wait_event / record_event**：这类同步类 API 耗时增加通常反映流水线并行度变差
5. **xpu_ops:: 前缀**：NPU 自定义算子 API，其 Self Time 变化直接反映算子下发效率

## 三、综合分析决策树

```
E2E 改善？
├── 是 → 识别改善亮点（哪个维度贡献最大？哪个通信算子改善最显著？）
│   └── 是否有局部劣化？（调度 Free Time 是否增加？是否有 Kernel 劣化？）
│       ├── 是 → 改善中有隐患，需关注劣化项以防回退
│       └── 否 → 全面改善，记录优化经验
└── 否 → 定位劣化方向
    ├── 计算劣化 → OperatorCompareStatistic → Top10 算子 → OperatorCompare → Kernel 详情
    ├── 通信劣化 → CommunicationCompare → 通信算子 → Wait vs Transmit 判断
    │   └── 通信无劣化算子 → 计算与通信并行度变差 → 集群分析
    └── 调度劣化 → Free Time 增加 → Host 下发瓶颈或流水线气泡
        └── ApiCompare → 检查 wait_event/record_event 是否增加
```

## 四、常见场景与解读

### 场景 1：GPU → NPU 迁移后性能劣化
- 看 OverallMetrics 定界：通常是 Computing Time 增大
- 看 OperatorCompareStatistic：定位劣化 TOP 算子
- 看 OperatorCompare：检查 Kernel 数量是否增多（NPU 可能插入额外 TransData）
- 检查 Vector (Trans) 占比：过高说明数据布局转换开销大

### 场景 2：NPU 版本升级后性能变化
- 看 KernelCompare：Kernel 级别的变化最直接反映底层优化效果
- 看 ApiCompare：Host 侧 API 变化反映框架调度优化
- 关注 significant_degraded：版本升级不应引入显著劣化的 Kernel

### 场景 3：MoE 模型通信瓶颈
- 看 CommunicationCompare：alltoall 是 MoE 核心通信算子
- 看 OverallMetrics 的 Wait vs Transmit：Wait 高说明同步阻塞
- 看 ApiCompare 的 c10d::alltoall_base_：Self Time 反映下发效率

### 场景 4：KV Cache 优化效果验证
- 看 E2E 改善幅度：KV Cache 优化应直接降低 E2E
- 看 Computing Time 中 Flash Attention 变化：FA 是 KV Cache 的主要受益者
- 看 Memory：KV Cache 优化应减少内存占用
- 看 KernelCompare：关注 FlashAttention 相关 Kernel 的变化

## 五、指标单位速查

| Sheet | 时间单位 | 内存单位 |
|---|---|---|
| OverallMetrics | ms | - |
| OperatorCompareStatistic | ms | - |
| OperatorCompare | us | - |
| ModuleCompareStatistic | ms | - |
| ModuleCompare | us | - |
| CommunicationCompare | us | - |
| MemoryCompareStatistic | - | MB |
| MemoryCompare | - | KB |
| KernelCompare | us | - |
| KernelTypeCompare | us | - |
| ApiCompare | ms | - |

## 六、比率解读速查

| Diff Ratio 范围 | 含义 | 颜色 | 建议 |
|---|---|---|---|
| < 0.1 | 极端改善 | 绿色 | 通常是策略性变化，确认是否符合预期 |
| 0.1 - 0.9 | 显著改善 | 绿色 | 优化有效 |
| 0.9 - 1.0 | 轻微改善 | 浅绿 | 在噪声范围内 |
| 1.0 | 持平 | 灰色 | 无变化 |
| 1.0 - 1.05 | 轻微劣化 | 浅红 | 可能是噪声，关注趋势 |
| 1.05 - 1.10 | 显著劣化 | 红色 | 需要关注和优化 |
| > 1.10 | 严重劣化 | 深红 | 需要立即优化 |
| inf | 基准为 0 | - | 新增项，需评估是否必要 |
