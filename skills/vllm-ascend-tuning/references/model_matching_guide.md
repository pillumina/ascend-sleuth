# 模型匹配指南

> **适用阶段:** Phase 0.5 - 无精确匹配配置时的回退策略
>
> **关联文档:** [SKILL.md](../SKILL.md) | [model_config_guide.md](model_config_guide.md) | [performance_data_summary.md](performance_data_summary.md) | [model_configs/](model_configs/)

---

## 1. 概述

当 `model_configs/` 目录中没有与目标模型精确匹配的配置文件时，需要按照本指南的匹配优先级策略进行回退。匹配过程分为 5 个阶段，从最精确的匹配逐步放宽到经验配置，确保在任何情况下都能为用户提供可用的启动配置。

### 1.1 匹配原则

- **优先精确匹配**: 始终从阶段1开始，逐级回退
- **最小偏差原则**: 选择与目标模型差异最小的配置
- **场景适配**: 回退时注意场景（低延迟/高吞吐）的适配调整
- **安全优先**: 回退配置应偏保守，避免因参数过激导致 OOM 或性能异常

---

## 2. 匹配优先级（5个阶段）

### 2.1 匹配流程总览

```
阶段1: 同型号不同场景
  |  (如 Qwen3.5-27B 高吞吐 → 低延迟)
  |  未匹配 ↓
阶段2: 同系列不同型号
  |  (如 Qwen3.5-27B → Qwen3.5-122B)
  |  未匹配 ↓
阶段3: 同系列不同版本
  |  (如 Qwen3.5 → Qwen3)
  |  未匹配 ↓
阶段4: 相似规模模型
  |  (如 27B → 32B)
  |  未匹配 ↓
阶段5: 经验配置库
     (使用默认经验配置: MoE / Dense)
```

### 2.2 阶段1: 同型号不同场景

**匹配条件:** 配置库中存在相同模型的不同场景配置。

**匹配规则:**
- 模型名称完全一致
- 配置文件中包含目标场景（低延迟/高吞吐/最大长度）的参数
- 直接使用该场景的参数配置

**调整建议:**
- 如果目标场景与配置场景不同，需要调整关键参数
- 低延迟 → 高吞吐: 增大 `max_num_seqs`，减小 `OMP_NUM_THREADS`，增大 `HCCL_BUFFSIZE`
- 高吞吐 → 低延迟: 减小 `max_num_seqs`，增大 `OMP_NUM_THREADS`，减小 `HCCL_BUFFSIZE`

**示例:**
```
目标: Qwen3.5-27B 低延迟场景
配置库: Qwen3.5-27B.yaml (仅含高吞吐配置)
操作: 使用高吞吐配置为基础，按低延迟参数调整
  - OMP_NUM_THREADS: 1 → 10
  - HCCL_BUFFSIZE: 1024 → 500
  - max_num_seqs: 128 → 64-96
  - max_num_batched_tokens: 16384 → 4000-6000
  - num_speculative_tokens: 3 → 5
```

### 2.3 阶段2: 同系列不同型号

**匹配条件:** 配置库中存在同一系列但不同参数量的模型配置。

**匹配规则:**
- 模型系列前缀相同（如 Qwen3.5-*）
- 选择参数量最接近的型号
- 同系列模型的架构、量化格式、投机解码方法通常一致

**调整建议:**
- 根据参数量差异调整 TP/DP
- 参数量更大: 增大 TP，减少 DP
- 参数量更小: 减小 TP，可增加 DP
- 显存需求按参数量比例估算

**示例:**
```
目标: Qwen3.5-27B
配置库: Qwen3.5-122B.yaml
操作: 使用 Qwen3.5-122B 配置为基础
  - TP: 4 → 2 (参数量减小约 4.5x)
  - DP: 保持或增加
  - max_num_seqs: 可适当增大
  - 投机解码方法: qwen3_5_mtp (同系列一致)
  - 量化格式: W8A8C16 (同系列一致)
```

### 2.4 阶段3: 同系列不同版本

**匹配条件:** 配置库中存在同一系列不同版本的模型配置。

**匹配规则:**
- 系列名相同但版本不同（如 Qwen3.5 → Qwen3）
- 优先选择最新版本的配置
- 注意架构差异可能影响投机解码方法

**调整建议:**
- 检查投机解码方法是否兼容（如 qwen3_5_mtp vs mtp）
- 检查模型架构是否一致（如 Qwen2_5ForCausalLM vs Qwen3ForCausalLM）
- 环境变量和编译配置通常可通用

**示例:**
```
目标: Qwen3.5-27B
配置库: Qwen3-32B.yaml
操作: 使用 Qwen3-32B 配置为基础
  - 投机解码方法: mtp → qwen3_5_mtp (版本差异)
  - TP: 根据参数量调整 (32B→27B, TP 可减小)
  - 架构验证: 确认 Qwen3.5 是否有架构变更
```

### 2.5 阶段4: 相似规模模型

**匹配条件:** 配置库中存在参数量相近的不同系列模型配置。

**匹配规则:**
- 参数量差异在 50% 以内
- 模型类型相同（Dense 匹配 Dense，MoE 匹配 MoE）
- 优先选择同类型（Dense/MoE）的配置

**调整建议:**
- 量化格式可能不同，需根据实际模型调整
- 投机解码方法需要根据目标模型支持的方法调整
- 并行策略根据模型结构调整

**示例:**
```
目标: Qwen3.5-27B (Dense)
配置库: 无 Qwen3.5 配置，但有 Qwen3-32B.yaml
操作: 使用 Qwen3-32B 配置为基础
  - 参数量: 32B → 27B (差异 15%，在可接受范围)
  - TP: 可保持或减小
  - 投机解码: 需确认 Qwen3.5 支持的方法
```

### 2.6 阶段5: 经验配置库

**匹配条件:** 以上所有阶段均未找到合适配置。

**匹配规则:**
- 根据模型类型（MoE / Dense）选择对应经验配置
- 使用通用优化参数作为起点
- 部署后根据实际性能进行调优

**注意事项:**
- 经验配置为通用模板，非针对特定模型优化
- 首次部署后建议运行基准测试获取性能基线
- 根据测试结果参考经验微调指南进行调整

---

## 3. MoE 模型经验配置

当没有任何匹配的 MoE 模型配置时，使用以下经验配置：

### 3.1 环境变量

```bash
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_BUFFSIZE=1024
export OMP_NUM_THREADS=1
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libjemalloc.so.2
export TASK_QUEUE_ENABLE=1
export VLLM_ASCEND_ENABLE_PREFETCH_MLP=1
export VLLM_ASCEND_ENABLE_DENSE_OPTIMIZE=1
export VLLM_ASCEND_ENABLE_NZ=1
export VLLM_ASCEND_ENABLE_FUSED_MC2=1
```

### 3.2 vLLM 启动参数

```bash
vllm serve /path/to/model \
  --tensor-parallel-size 8 \
  --max-model-len 8192 \
  --max-num-batched-tokens 8192 \
  --max-num-seqs 128 \
  --gpu-memory-utilization 0.9 \
  --async-scheduling \
  --speculative-config '{"num_speculative_tokens": 3, "method":"qwen3_5_mtp", "enforce_eager": true}' \
  --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY", "cudagraph_capture_sizes":[4,8,12,16,20,24,28,32,36,40,44,48,52,56,60,64,68,72,76,80,84,88,92,96,100,104,108,112,116,120,124,128]}' \
  --additional-config '{"enable_cpu_binding":true, "multistream_overlap_shared_expert": true, "enable_weight_nz_layout":true}'
```

### 3.3 MoE 经验配置说明

| 配置项 | 经验值 | 说明 |
|--------|--------|------|
| `HCCL_OP_EXPANSION_MODE` | AIV | HCCL 必须使用 AIV 模式 |
| `HCCL_BUFFSIZE` | 1024 | 高吞吐场景缓冲区大小 |
| `OMP_NUM_THREADS` | 1 | 高吞吐场景线程配置 |
| `VLLM_ASCEND_ENABLE_PREFETCH_MLP` | 1 | MLP 预取优化 |
| `VLLM_ASCEND_ENABLE_DENSE_OPTIMIZE` | 1 | Dense 层优化 |
| `VLLM_ASCEND_ENABLE_NZ` | 1 | NZ 布局优化 |
| `VLLM_ASCEND_ENABLE_FUSED_MC2` | 1 | 融合 MC2 通信优化 |
| `tensor-parallel-size` | 8 | 默认 TP 大小 |
| `max-model-len` | 8192 | 保守的上下文长度 |
| `max-num-seqs` | 128 | 中等并发度 |
| `speculative method` | qwen3_5_mtp | 通用投机解码方法 |
| `cudagraph_capture_sizes` | 4-128 步进4 | 覆盖常见 batch sizes |
| `enable_cpu_binding` | true | CPU 亲和性绑定 |
| `multistream_overlap_shared_expert` | true | 共享专家多流重叠 |
| `enable_weight_nz_layout` | true | 权重 NZ 布局 |

> **注意:** MoE 模型如果支持 `--enable-expert-parallel`，应额外添加该参数。投机解码方法需根据模型实际支持的方法调整（如 DeepSeek 系列用 `mtp`，Qwen3.5 用 `qwen3_5_mtp`）。

---

## 4. Dense 模型经验配置

当没有任何匹配的 Dense 模型配置时，使用以下经验配置：

### 4.1 环境变量

```bash
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_BUFFSIZE=1024
export OMP_NUM_THREADS=1
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
```

### 4.2 vLLM 启动参数

```bash
vllm serve /path/to/model \
  --tensor-parallel-size 8 \
  --max-model-len 8192 \
  --max-num-batched-tokens 16384 \
  --max-num-seqs 256 \
  --gpu-memory-utilization 0.9 \
  --speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}' \
  --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}'
```

### 4.3 Dense 经验配置说明

| 配置项 | 经验值 | 说明 |
|--------|--------|------|
| `HCCL_OP_EXPANSION_MODE` | AIV | HCCL 必须使用 AIV 模式 |
| `HCCL_BUFFSIZE` | 1024 | 高吞吐场景缓冲区大小 |
| `OMP_NUM_THREADS` | 1 | 高吞吐场景线程配置 |
| `PYTORCH_NPU_ALLOC_CONF` | expandable_segments:True | NPU 内存分配优化 |
| `tensor-parallel-size` | 8 | 默认 TP 大小 |
| `max-model-len` | 8192 | 保守的上下文长度 |
| `max-num-batched-tokens` | 16384 | Dense 模型可用更大 batch |
| `max-num-seqs` | 256 | 高并发度 |
| `speculative method` | mtp | 通用投机解码方法 |
| `cudagraph_mode` | FULL_DECODE_ONLY | Graph Mode 配置 |

> **注意:** Dense 模型相比 MoE 配置更精简，不需要专家并行和共享专家优化。`max-num-batched-tokens` 和 `max-num-seqs` 可设为更大值，因为 Dense 模型计算密度更高。

### 4.4 Dense 与 MoE 经验配置对比

| 配置项 | Dense | MoE | 差异原因 |
|--------|-------|-----|----------|
| `max-num-batched-tokens` | 16384 | 8192 | Dense 计算密度高，可处理更大 batch |
| `max-num-seqs` | 256 | 128 | Dense 显存占用更可控 |
| `LD_PRELOAD` | 不需要 | jemalloc | MoE 多线程场景更需要内存优化 |
| `TASK_QUEUE_ENABLE` | 不需要 | 1 | MoE 调度更复杂 |
| `VLLM_ASCEND_ENABLE_*` | 不需要 | 多项 | MoE 需要更多 Ascend 优化 |
| `enable_expert_parallel` | 不需要 | 需要 | MoE 特有 |
| `additional-config` | 无 | 多项 | MoE 需要专家优化 |
| `speculative method` | mtp | qwen3_5_mtp | 方法选择不同 |

---

## 5. 跨平台配置说明

### 5.1 统一配置原则

> **当前版本不区分 A2/A3 配置，统一使用最优配置。**

无论实际硬件是 A2（910B2）还是 A3（910B4），均使用同一套配置参数。配置文件名中的 A2/A3 后缀仅用于信息显示，不影响参数选择。

### 5.2 硬件检测

```bash
# 自动检测 NPU 型号（仅用于信息显示）
npu-smi info | grep "910B"

# 识别规则:
# 910B4 = A3
# 910B2 = A2
```

### 5.3 跨平台注意事项

- 硬件检测结果仅用于信息记录和显示，不影响配置选择
- 所有配置参数在 A2 和 A3 平台上通用
- 如果遇到平台特定的兼容性问题，参考 [env-variables.md](env-variables.md) 确认环境变量兼容性
- PD 分离配置中的 `ASCEND_A3_ENABLE=1` 仅在 A3 平台生效，A2 平台可忽略

---

## 6. 经验微调指南

当基准配置或经验配置与实际环境不完全匹配时，按以下规则进行调整：

### 6.1 微调指南表格

| 差异 | 调整方向 |
|------|----------|
| 卡数更多 | 增加 DP 或 TP，保持 TPOT 目标 |
| 卡数更少 | 减少 DP 优先，必要时降低 max-model-len |
| 显存不足 | 降低 max-num-seqs 20-30%，或增大 TP |
| 延迟偏高 | 检查 OMP_NUM_THREADS，减小 HCCL_BUFFSIZE |
| 吞吐不足 | 增加 max-num-seqs，增大 HCCL_BUFFSIZE |

### 6.2 微调详细说明

#### 卡数更多

当实际可用 NPU 数量多于配置推荐时：

```
策略: 优先增加 DP，保持 TP 不变
  - 增加 DP 可线性提升吞吐量
  - TP 保持不变可维持 TPOT 目标
  - 示例: 配置 DP2+TP8 (16卡) → 实际 32卡 → DP4+TP8

备选策略: 增加 TP
  - 适用于需要更大模型或更长上下文的场景
  - 增加 TP 会减少单卡计算量，可能降低 TPOT
  - 示例: TP8 → TP16
```

#### 卡数更少

当实际可用 NPU 数量少于配置推荐时：

```
策略: 优先减少 DP，保持 TP 不变
  - 减少 DP 可保持模型并行效率
  - 吞吐量会相应降低
  - 示例: 配置 DP4+TP4 (16卡) → 实际 8卡 → DP1+TP8 或 DP2+TP4

备选策略: 减少 TP
  - 仅当 DP 已经为 1 时考虑
  - 减少 TP 可能导致显存不足
  - 需要同时降低 max-model-len
  - 示例: TP8 → TP4, max-model-len 65536 → 32768
```

#### 显存不足

当出现 OOM（Out of Memory）错误时：

```
优先策略: 降低 max-num-seqs
  - 降低 20-30% 通常可解决显存问题
  - 示例: max-num-seqs 128 → 96 或 64

备选策略1: 增大 TP
  - 将模型分散到更多卡上
  - 示例: TP4 → TP8

备选策略2: 降低 max-model-len
  - 减少 KV Cache 占用
  - 示例: max-model-len 65536 → 32768

备选策略3: 降低 gpu-memory-utilization
  - 示例: 0.9 → 0.85
  - 注意: 会减少可用于 KV Cache 的显存
```

#### 延迟偏高

当 TPOT 高于目标值时：

```
优先检查: OMP_NUM_THREADS
  - 低延迟场景应为 10
  - 高吞吐场景为 1
  - 如果设置错误，TPOT 会显著升高

调整策略: 减小 HCCL_BUFFSIZE
  - 低延迟: 256-500
  - 高吞吐: 500-1024
  - 减小缓冲区可降低通信延迟

备选策略:
  - 增大 num_speculative_tokens (3 → 5)
  - 减小 max_num_batched_tokens
  - 检查是否启用了 async-scheduling
  - 检查 cudagraph_capture_sizes 是否覆盖实际 batch sizes
```

#### 吞吐不足

当吞吐量低于预期时：

```
调整策略: 增加 max-num-seqs
  - 增大并发度可提升吞吐量
  - 注意: 过大会增加 TPOT
  - 示例: max-num-seqs 96 → 128 或 256

备选策略: 增大 HCCL_BUFFSIZE
  - 高吞吐: 500-1024
  - 增大缓冲区可提升通信效率

其他优化:
  - 确认 OMP_NUM_THREADS=1 (高吞吐场景)
  - 启用 VLLM_ASCEND_ENABLE_FUSED_MC2=1
  - 增大 max_num_batched_tokens
  - 增加 DP (如果有额外卡)
  - 确认投机解码已启用
```

### 6.3 场景切换微调

当需要在低延迟和高吞吐场景之间切换时：

| 参数 | 低延迟 → 高吞吐 | 高吞吐 → 低延迟 |
|------|----------------|----------------|
| `OMP_NUM_THREADS` | 10 → 1 | 1 → 10 |
| `HCCL_BUFFSIZE` | 500 → 1024 | 1024 → 500 |
| `max_num_seqs` | 96 → 128+ | 128 → 64-96 |
| `max_num_batched_tokens` | 6000 → 16384 | 16384 → 6000 |
| `num_speculative_tokens` | 5 → 3 | 3 → 5 |
| `DP` | 减小 | 增大 |
| `TP` | 保持或减小 | 保持或增大 |

---

## 7. 匹配决策流程图

```
开始
  |
  v
检测目标模型名称
  |
  v
配置库中是否有相同模型? ──是──> 使用该配置 (阶段1: 同型号不同场景)
  |                                |
  否                               调整场景参数
  |                                |
  v                                v
配置库中是否有同系列不同型号? ──是──> 使用该配置 (阶段2: 同系列不同型号)
  |                                    |
  否                                   调整 TP/DP
  |                                    |
  v                                    v
配置库中是否有同系列不同版本? ──是──> 使用该配置 (阶段3: 同系列不同版本)
  |                                    |
  否                                   调整投机解码方法
  |                                    |
  v                                    v
配置库中是否有相似规模模型? ──是──> 使用该配置 (阶段4: 相似规模模型)
  |                                    |
  否                                   调整量化/并行策略
  |                                    |
  v                                    v
模型类型是 MoE 还是 Dense?
  |              |
  MoE            Dense
  |              |
  v              v
使用 MoE      使用 Dense
经验配置       经验配置
(阶段5)       (阶段5)
  |              |
  v              v
部署后运行基准测试
  |
  v
根据经验微调指南调整
  |
  v
完成
```

---

## 8. 注意事项

### 8.1 匹配优先级

- 始终从阶段1开始逐级匹配，不要跳过中间阶段
- 每个阶段的匹配都应选择差异最小的配置
- 阶段5（经验配置）是最后手段，非最优选择

### 8.2 参数调整安全边界

| 参数 | 安全调整范围 | 风险说明 |
|------|-------------|----------|
| `max_num_seqs` | 原值 50%-200% | 过低影响吞吐，过高导致 OOM |
| `max_model_len` | 原值 50%-100% | 过低影响功能，过高导致 OOM |
| `HCCL_BUFFSIZE` | 128-2048 | 过低影响通信效率，过高浪费显存 |
| `OMP_NUM_THREADS` | 1-20 | 需根据场景选择，错误设置严重影响性能 |
| `TP` | 1-16 | 需为 2 的幂次，且不超过总卡数 |
| `DP` | 1-N | TP * DP 不超过总卡数 |

### 8.3 验证建议

- 回退配置部署后，务必运行 `vllm bench` 进行性能测试
- 将测试结果与 [performance_data_summary.md](performance_data_summary.md) 中的基准数据对比
- 如果性能差异过大（>30%），重新评估匹配阶段和参数调整
- 记录最终使用的配置参数，供后续参考

### 8.4 模型类型判断

如果不确定目标模型是 Dense 还是 MoE：

```bash
# 方法1: 查看模型配置文件
cat /path/to/model/config.json | grep -i "moe\|expert\|num_experts"

# 方法2: 查看模型架构
cat /path/to/model/config.json | grep "architectures"

# 判断规则:
# - 配置中有 num_experts / moe 相关字段 → MoE 模型
# - 架构名含 MoE / Expert → MoE 模型
# - 否则 → Dense 模型
```
