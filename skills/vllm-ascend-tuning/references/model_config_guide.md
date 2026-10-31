# 模型基准配置使用指南

> **适用阶段:** Phase 0.5 - 模型基准配置匹配（必须首先执行）
>
> **关联文档:** [SKILL.md](../SKILL.md) | [model_matching_guide.md](model_matching_guide.md) | [performance_data_summary.md](performance_data_summary.md) | [model_configs/](model_configs/)

---

## 1. 配置库概述

`model_configs/` 目录包含已验证的生产环境配置文件（YAML 格式），覆盖 vLLM-Ascend 平台上的主流大模型。每个配置文件均经过实际硬件测试验证，记录了该模型在特定场景下的最佳启动参数、环境变量和性能指标。

### 1.1 配置库覆盖范围

| 模型系列 | 配置文件 | 模型类型 | 场景覆盖 |
|----------|----------|----------|----------|
| DeepSeek-V3 | DeepSeek-V3.txt / DeepSeek-V3.1.txt / DeepSeek-V3.2.txt | MoE | 低延迟 / 高吞吐 |
| Qwen3 | Qwen3-8B.txt / Qwen3-30B.txt / Qwen3-32B.txt / Qwen3-235B-A22B.txt | Dense / MoE | 高吞吐 / 性能基线 |
| Qwen3 MoE | Qwen3-MoE-480B.txt | MoE | 多机性能基线 |
| Qwen3.5 | Qwen3.5-27B.txt / Qwen3.5-122B.txt / Qwen3.5-397B.txt | Dense | 低延迟 / 高吞吐 / 最大长度 |
| Qwen3-VL / Qwen2.5-VL | Qwen3-VL.txt / Qwen2.5-VL.txt | 多模态 | 视觉理解 |
| Kimi-K2.5 | Kimi-K2.5.txt | MoE | 高吞吐 |
| GLM-5.1 | GLM-5.1.txt | MoE (PD分离) | 最大长度 / PD分离 |
| MiniMax-M2.5 | MiniMax-M2.5.txt | MoE | 最大长度 / 高吞吐 |
| Qwen3-Embedding | Qwen3-Embedding.txt | Embedding | 文本嵌入 |
| Qwen3-Reranker | Qwen3-Reranker.txt | Reranker | 文档重排序 |

### 1.2 配置文件价值

- **已验证参数**: 所有参数均在实际 Atlas 800I A3-560T (HBM 128G) 平台上测试通过
- **开箱即用**: 直接提取环境变量和启动命令即可部署
- **性能基准**: 附带实测性能数据（吞吐量、TPOT 等），便于对比验证
- **多场景覆盖**: 同一模型通常包含低延迟和高吞吐两种场景配置

---

## 2. YAML 配置文件结构说明

每个配置文件采用标准 YAML 格式组织，包含以下核心字段：

### 2.1 字段总览

```yaml
# ============================================
# 模型配置文件结构
# ============================================
model:                    # 模型基本信息
  name:                   # 模型名称
  type:                   # 模型类型 (Dense / MoE / Embedding / Reranker / PD分离)
  description:            # 模型描述
  huggingface_path:       # HuggingFace 模型路径
  architecture:           # 模型架构 (如 DeepseekV3ForCausalLM)

deployment:               # 部署配置
  recommended_tp:         # 推荐 Tensor Parallel 大小
  recommended_dp:         # 推荐 Data Parallel 大小
  min_npu_count:          # 最小 NPU 数量
  recommended_memory:     # 推荐内存大小
  quantization:           # 量化格式 (W4A8 / W8A8 / W8A8C16 / W4A8C16)
  deploy_mode:            # 部署模式 (标准 / PD_separation)

performance:              # 性能参数
  max_model_len:          # 最大模型长度
  max_num_seqs:           # 最大并发序列数
  max_num_batched_tokens:  # 最大批处理 token 数
  gpu_memory_utilization:  # GPU 显存利用率
  block_size:             # KV Cache 块大小

environment_variables:    # 环境变量配置
  HCCL_OP_EXPANSION_MODE:  # HCCL 操作扩展模式 (必须为 AIV)
  HCCL_BUFFSIZE:           # HCCL 缓冲区大小
  OMP_NUM_THREADS:         # OpenMP 线程数
  PYTORCH_NPU_ALLOC_CONF:  # PyTorch NPU 内存分配配置
  LD_PRELOAD:              # 动态链接库预加载 (jemalloc 等)
  TASK_QUEUE_ENABLE:       # 任务队列开关
  VLLM_ASCEND_ENABLE_*:    # vLLM-Ascend 优化开关系列

vllm_parameters:          # vLLM 启动参数
  trust_remote_code:       # 信任远程代码
  quantization:            # 量化方法
  async_scheduling:        # 异步调度
  enable_expert_parallel:  # 专家并行 (MoE 模型)
  enable_prefix_caching:   # 前缀缓存
  distributed_executor_backend:  # 分布式执行后端

speculative_decoding:     # 投机解码配置
  method:                  # 投机解码方法 (mtp / deepseek_mtp / qwen3_5_mtp / eagle3)
  num_speculative_tokens:  # 投机 token 数量
  enforce_eager:           # 是否强制 eager 模式
  disable_padded_drafter_batch:  # 禁用填充 drafter batch

compilation_config:       # 编译/Graph Mode 配置
  cudagraph_mode:          # Graph 模式 (FULL_DECODE_ONLY)
  cudagraph_capture_sizes:  # Graph 捕获 batch sizes 列表

additional_config:        # 额外配置
  enable_cpu_binding:      # CPU 亲和性绑定
  enable_shared_expert_dp:  # 共享专家 DP (MoE)
  multistream_overlap_shared_expert:  # 共享专家多流重叠
  enable_weight_nz_layout:  # 权重 NZ 布局
  enable_npugraph_ex:      # NPU Graph 扩展
  fuse_muls_add:           # 融合 muls+add 算子
  recompute_scheduler_enable:  # 重计算调度器
  layer_sharding:          # 层分片配置

launch_command:           # 完整启动命令
  # 包含可直接执行的完整 vllm serve 命令
```

### 2.2 各字段详细说明

#### model（模型基本信息）

记录模型的名称、类型、架构等元数据信息。

| 子字段 | 说明 | 示例值 |
|--------|------|--------|
| `name` | 模型名称 | `DeepSeek-V3.1` |
| `type` | 模型类型 | `Dense` / `MoE` / `Embedding` / `Reranker` / `PD分离` |
| `description` | 模型描述 | `DeepSeek-V3.1 MoE 模型, 支持投机解码 (MTP)` |
| `huggingface_path` | HF 模型路径 | `deepseek-ai/DeepSeek-V3.1` |
| `architecture` | 模型架构类 | `DeepseekV3ForCausalLM` |

#### deployment（部署配置）

定义模型的并行策略、硬件需求和量化方案。

| 子字段 | 说明 | 示例值 |
|--------|------|--------|
| `recommended_tp` | 推荐 Tensor Parallel 大小 | `8` |
| `recommended_dp` | 推荐 Data Parallel 大小 | `2` |
| `min_npu_count` | 最小 NPU 数量 | `8` |
| `recommended_memory` | 推荐系统内存 | `512 GB` |
| `quantization` | 量化格式 | `W4A8` / `W8A8` / `W8A8C16` |
| `deploy_mode` | 部署模式 | `标准` / `PD_separation` |

#### performance（性能参数）

vLLM 推理引擎的核心性能调优参数。

| 子字段 | 说明 | 低延迟典型值 | 高吞吐典型值 |
|--------|------|-------------|-------------|
| `max_model_len` | 最大上下文长度 | 65536 | 8192-262144 |
| `max_num_seqs` | 最大并发序列数 | 64-96 | 128-512 |
| `max_num_batched_tokens` | 最大批处理 token 数 | 4000-6000 | 8192-16384 |
| `gpu_memory_utilization` | 显存利用率 | 0.9 | 0.9-0.95 |
| `block_size` | KV Cache 块大小 | 128 | 128 |

#### environment_variables（环境变量）

操作系统和框架级的环境变量配置，对性能有直接影响。

| 变量 | 说明 | 低延迟 | 高吞吐 |
|------|------|--------|--------|
| `HCCL_OP_EXPANSION_MODE` | HCCL 操作扩展模式（必须为 AIV） | AIV | AIV |
| `HCCL_BUFFSIZE` | HCCL 通信缓冲区大小 | 256-500 | 500-1024 |
| `OMP_NUM_THREADS` | OpenMP 线程数 | 10 | 1 |
| `PYTORCH_NPU_ALLOC_CONF` | NPU 内存分配策略 | expandable_segments:True | expandable_segments:True |
| `LD_PRELOAD` | 预加载内存分配器 | libjemalloc.so.2 | libjemalloc.so.2 |
| `TASK_QUEUE_ENABLE` | 任务队列 | 1 | 1 |
| `VLLM_ASCEND_ENABLE_MLAPO` | MLA 算子优化 | 1 | - |
| `VLLM_ASCEND_ENABLE_FUSED_MC2` | 融合 MC2 通信 | - | 1 |
| `VLLM_ASCEND_ENABLE_PREFETCH_MLP` | MLP 预取 | - | 1 |
| `VLLM_ASCEND_ENABLE_NZ` | NZ 布局 | - | 1 |

#### vllm_parameters（vLLM 启动参数）

vLLM 推理引擎的命令行参数配置。

| 参数 | 说明 | 适用模型 |
|------|------|----------|
| `trust_remote_code` | 信任远程代码 | 所有模型 |
| `quantization ascend` | 使用昇腾量化 | 量化模型 |
| `async_scheduling` | 异步调度 | 所有模型 |
| `enable_expert_parallel` | 专家并行 | MoE 模型 |
| `enable_prefix_caching` / `no_enable_prefix_caching` | 前缀缓存开关 | 视场景而定 |
| `distributed_executor_backend` | 分布式后端 (mp) | Embedding/Reranker |

#### speculative_decoding（投机解码配置）

投机解码（Speculative Decoding）通过预测后续 token 来加速推理。

| 子字段 | 说明 | 常见值 |
|--------|------|--------|
| `method` | 投机解码方法 | `mtp` / `deepseek_mtp` / `qwen3_5_mtp` / `eagle3` |
| `num_speculative_tokens` | 投机 token 数量 | 3-5（低延迟用 5，高吞吐用 3） |
| `enforce_eager` | 强制 eager 模式 | true / false |
| `disable_padded_drafter_batch` | 禁用填充 drafter batch | false |

**方法与模型对照：**

| 模型系列 | 推荐方法 | num_speculative_tokens |
|----------|----------|----------------------|
| DeepSeek-V3.1 | mtp | 3 |
| DeepSeek-V3.2 | deepseek_mtp | 3 |
| Qwen3.5 | qwen3_5_mtp | 3-5 |
| Kimi-K2.5 | eagle3 | 3 |
| GLM-5.1 | deepseek_mtp | 3 |

#### compilation_config（编译/Graph Mode 配置）

Graph Mode 通过预编译计算图减少运行时开销。

| 子字段 | 说明 | 典型值 |
|--------|------|--------|
| `cudagraph_mode` | Graph 模式 | `FULL_DECODE_ONLY` |
| `cudagraph_capture_sizes` | Graph 捕获的 batch sizes | 低延迟: 小 sizes；高吞吐: 大 sizes |

**低延迟典型配置：**
```json
{"cudagraph_mode": "FULL_DECODE_ONLY", "cudagraph_capture_sizes": [1,6,12,18,24,30,36,42,48,54,72,96,108,144,192]}
```

**高吞吐典型配置：**
```json
{"cudagraph_mode": "FULL_DECODE_ONLY", "cudagraph_capture_sizes": [1,4,8,16,32,64,96,128,192,256,384,512]}
```

#### additional_config（额外配置）

vLLM-Ascend 特有的高级优化配置。

| 子字段 | 说明 | 适用场景 |
|--------|------|----------|
| `enable_cpu_binding` | CPU 亲和性绑定 | 所有模型 |
| `enable_shared_expert_dp` | 共享专家 DP | MoE 模型 |
| `multistream_overlap_shared_expert` | 共享专家多流重叠 | MoE 模型 |
| `enable_weight_nz_layout` | 权重 NZ 布局 | MoE 模型 |
| `enable_npugraph_ex` | NPU Graph 扩展 | PD 分离 |
| `fuse_muls_add` | 融合算子 | PD 分离 |
| `recompute_scheduler_enable` | 重计算调度 | PD 分离 |
| `layer_sharding` | 层分片 | PD 分离 |

#### launch_command（完整启动命令）

包含可直接复制执行的最完整 vLLM 启动命令，集成了上述所有配置。

---

## 3. 不同模型类型的配置差异

### 3.1 Dense 模型

Dense（稠密）模型所有参数在每个 token 计算中均参与，配置特点：

- **并行策略**: 主要使用 TP，通常不需要 EP
- **环境变量**: 相对精简，核心是 HCCL 和 OMP 配置
- **投机解码**: 使用 `mtp` 或 `qwen3_5_mtp` 方法
- **批处理**: 高吞吐场景 max_num_batched_tokens 可达 16384
- **典型代表**: Qwen3.5-27B、Qwen3-32B

```yaml
# Dense 模型典型配置
model:
  type: Dense
deployment:
  recommended_tp: 2-8
  quantization: W8A8C16
performance:
  max_num_seqs: 128-256
  max_num_batched_tokens: 16384
vllm_parameters:
  enable_expert_parallel: false  # 不需要
speculative_decoding:
  method: mtp
```

### 3.2 MoE 模型

MoE（混合专家）模型通过稀疏激活提升效率，配置特点：

- **并行策略**: 必须启用 `--enable-expert-parallel`，EP 大小通常等于总卡数
- **环境变量**: 需要更多优化开关（PREFETCH_MLP、DENSE_OPTIMIZE、NZ、FUSED_MC2）
- **投机解码**: 根据模型系列选择对应方法
- **额外配置**: 通常包含 `multistream_overlap_shared_expert` 等专家优化
- **典型代表**: DeepSeek-V3.1、Qwen3-MoE-480B、Kimi-K2.5

```yaml
# MoE 模型典型配置
model:
  type: MoE
deployment:
  recommended_tp: 8-16
  quantization: W4A8
vllm_parameters:
  enable_expert_parallel: true  # 必须启用
additional_config:
  enable_shared_expert_dp: true
  multistream_overlap_shared_expert: true
  enable_weight_nz_layout: true
```

### 3.3 Embedding 模型

文本嵌入模型用于将文本转换为向量表示，配置特点：

- **并行策略**: 通常单卡部署（TP=1），高并发可用多卡
- **无投机解码**: 不支持 Speculative Decoding
- **大 batch**: max_num_seqs 可达 512
- **短序列**: max_model_len 通常为 8192
- **嵌入模式**: 需要配置 `embedding_mode: true`
- **典型代表**: Qwen3-Embedding

```yaml
# Embedding 模型典型配置
model:
  type: Embedding
deployment:
  recommended_tp: 1
  min_npu_count: 1
performance:
  max_num_seqs: 512
  max_model_len: 8192
speculative_decoding: null  # 不支持
additional_config:
  embedding_mode: true
  pooling_method: last
```

### 3.4 Reranker 模型

重排序模型用于对文档按相关性重新排序，配置特点：

- **并行策略**: 通常单卡部署（TP=1）
- **无投机解码**: 不支持 Speculative Decoding
- **大 batch**: max_num_seqs 可达 512
- **重排序模式**: 需要配置 `reranker_mode: true`
- **典型代表**: Qwen3-Reranker

```yaml
# Reranker 模型典型配置
model:
  type: Reranker
deployment:
  recommended_tp: 1
  min_npu_count: 1
performance:
  max_num_seqs: 512
  max_model_len: 8192
speculative_decoding: null  # 不支持
additional_config:
  reranker_mode: true
  pooling_method: cls
```

### 3.5 PD 分离模型

Prefill-Decode 分离架构将预填充和解码分离到不同节点，配置特点：

- **部署模式**: `PD_separation`，需要分别配置 Prefill 和 Decode 节点
- **KV 传输**: 使用 KV Connector（如 MooncakeConnectorV1）传输 KV Cache
- **高 TP**: Prefill 节点使用高 TP（TP8-16），Decode 节点使用高 DP（DP32）
- **额外环境变量**: 需要 ASCEND_AGGREGATE_ENABLE、VLLM_ASCEND_ENABLE_FLASHCOMM1 等
- **典型代表**: GLM-5.1

```yaml
# PD 分离模型典型配置
model:
  type: MoE (PD分离部署)
deployment:
  deploy_mode: PD_separation
  recommended_tp: 16
  recommended_dp: 2
  min_npu_count: 32
environment_variables:
  VLLM_ASCEND_ENABLE_FUSED_MC2: 1
  VLLM_ASCEND_ENABLE_FLASHCOMM1: 1
  ASCEND_AGGREGATE_ENABLE: 1
  ASCEND_A3_ENABLE: 1
additional_config:
  enable_npugraph_ex: true
  fuse_muls_add: true
  recompute_scheduler_enable: true
  layer_sharding: ["q_b_proj", "o_proj"]
# KV 传输配置
kv_transfer:
  kv_connector: MooncakeConnectorV1
  kv_role: kv_producer / kv_consumer
  kv_port: 30000
```

### 3.6 模型类型配置差异汇总

| 配置项 | Dense | MoE | Embedding | Reranker | PD分离 |
|--------|-------|-----|-----------|----------|--------|
| Expert Parallel | 否 | 是 | 否 | 否 | 是 |
| 投机解码 | mtp | 模型相关 | 不支持 | 不支持 | 模型相关 |
| 量化格式 | W8A8C16 | W4A8 | 无 | 无 | W8A8C16 |
| 推荐 TP | 2-8 | 8-16 | 1 | 1 | 16 |
| max_num_seqs | 128-256 | 64-128 | 512 | 512 | 64 |
| 共享专家优化 | 不需要 | 需要 | 不需要 | 不需要 | 需要 |
| KV Connector | 不需要 | 不需要 | 不需要 | 不需要 | 需要 |

---

## 4. 配置文件命名规则

### 4.1 标准命名格式

配置文件采用统一的命名规范：

```
{模型名}.yaml
```

### 4.2 命名示例

| 模型 | 配置文件名 |
|------|-----------|
| DeepSeek-V3.1 | `DeepSeek-V3.1.yaml` |
| DeepSeek-V3.2 | `DeepSeek-V3.2.yaml` |
| Qwen3.5-27B | `Qwen3.5-27B.yaml` |
| Qwen3.5-122B | `Qwen3.5-122B.yaml` |
| Qwen3.5-397B | `Qwen3.5-397B.yaml` |
| Qwen3-32B | `Qwen3-32B.yaml` |
| Qwen3-MoE-480B | `Qwen3-MoE-480B.yaml` |
| Kimi-K2.5 | `Kimi-K2.5.yaml` |
| GLM-5.1 | `GLM-5.1.yaml` |
| MiniMax-M2.5 | `MiniMax-M2.5.yaml` |

### 4.3 命名规则说明

- 模型名使用官方完整名称，保留版本号和参数量后缀
- 参数量后缀使用大写 B（如 `27B`、`122B`、`397B`）
- MoE 模型在名称中标注 `MoE`（如 `Qwen3-MoE-480B`）
- 多模态模型在名称中标注 `VL`（如 `Qwen3-VL`）
- 文件扩展名统一为 `.yaml`

> **注意:** 当前 `model_configs/` 目录中部分配置文件使用 `.txt` 扩展名，内容结构等同于 YAML 格式。后续更新将逐步统一为 `.yaml` 扩展名。

---

## 5. 如何读取和使用配置文件

### 5.1 使用流程（必须严格遵守）

```
Step 1: 读取 YAML 配置文件
   |
Step 2: 提取环境变量
   |
Step 3: 提取 vLLM 启动参数
   |
Step 4: 提取场景配置（低延迟/高吞吐）
   |
Step 5: 生成完整启动命令
   |
Step 6: 按照基准参数启动服务并进行测试
```

### 5.2 Step 1: 读取 YAML 配置文件

```python
# 示例：读取 DeepSeek-V3.1 配置
read_file("references/model_configs/DeepSeek-V3.1.yaml")

# 示例：读取 Qwen3.5-27B 配置
read_file("references/model_configs/Qwen3.5-27B.yaml")
```

### 5.3 Step 2: 提取环境变量

从配置文件的 `environment_variables` 字段提取所有环境变量，按顺序设置：

```bash
# 示例：DeepSeek-V3.1 环境变量
export LD_PRELOAD="/usr/lib/aarch64-linux-gnu/libjemalloc.so.2"
export HCCL_OP_EXPANSION_MODE="AIV"
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export VLLM_USE_V1=1
export HCCL_BUFFSIZE=500
export VLLM_ASCEND_ENABLE_MLAPO=1
export TASK_QUEUE_ENABLE=1
export VLLM_ASCEND_BALANCE_SCHEDULING=1
export OMP_PROC_BIND=false
export OMP_NUM_THREADS=10
```

### 5.4 Step 3: 提取 vLLM 启动参数

从配置文件中提取以下内容：

- **并行策略**: `--data-parallel-size`、`--tensor-parallel-size`、`--enable-expert-parallel`
- **批处理参数**: `--max-num-seqs`、`--max-num-batched-tokens`、`--max-model-len`
- **量化配置**: `--quantization ascend`
- **调度配置**: `--async-scheduling`
- **投机解码**: `--speculative-config`
- **编译配置**: `--compilation-config`
- **额外配置**: `--additional-config`

### 5.5 Step 4: 选择场景配置

同一模型可能有多个场景配置，根据调优目标选择：

| 调优目标 | 场景选择 | 关键差异 |
|----------|----------|----------|
| 优化 TTFT/TPOT | 低延迟 | OMP_NUM_THREADS=10, HCCL_BUFFSIZE=256-500, max_num_seqs=64-96 |
| 优化吞吐量 | 高吞吐 | OMP_NUM_THREADS=1, HCCL_BUFFSIZE=500-1024, max_num_seqs=128+ |
| 最大上下文 | 最大长度 | 最大 TP, max_model_len 最大化 |
| PD 分离 | PD_separation | 分别配置 Prefill/Decode 节点 |

### 5.6 Step 5: 生成完整启动命令

将提取的环境变量和启动参数组合为完整命令：

```bash
# ============================================
# 环境变量
# ============================================
export LD_PRELOAD="/usr/lib/aarch64-linux-gnu/libjemalloc.so.2"
export HCCL_OP_EXPANSION_MODE="AIV"
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export VLLM_USE_V1=1
export HCCL_BUFFSIZE=500
export VLLM_ASCEND_ENABLE_MLAPO=1
export TASK_QUEUE_ENABLE=1
export OMP_NUM_THREADS=10

# ============================================
# vLLM 启动命令
# ============================================
vllm serve /path/to/DeepSeek-V3.1-w4a8 \
  --data-parallel-size 2 \
  --tensor-parallel-size 8 \
  --enable-expert-parallel \
  --max-num-seqs 96 \
  --max-num-batched-tokens 6000 \
  --max-model-len 65536 \
  --quantization ascend \
  --async-scheduling \
  --speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}' \
  --compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY"}' \
  --additional-config '{"enable_shared_expert_dp": true, "multistream_overlap_shared_expert": true}' \
  --gpu-memory-utilization 0.9 \
  --trust-remote-code
```

### 5.7 Step 6: 启动服务并进行测试

```bash
# 1. 使用生成的命令启动 vLLM 服务
# 2. 运行性能测试
vllm bench serve \
  --model /path/to/model \
  --dataset-name sharegpt \
  --num-prompts 100

# 3. 记录测试结果（TTFT、TPOT、吞吐量）
# 4. 与基准配置性能数据对比
```

---

## 6. 配置文件更新维护规范

### 6.1 更新流程

1. **测试验证**: 所有参数变更必须在 Atlas 800I A3-560T (HBM 128G) 平台实际测试
2. **记录性能**: 更新配置时同步记录性能指标（吞吐量、TPOT、TTFT）
3. **版本标注**: 在配置文件中更新 `最后更新` 日期
4. **向后兼容**: 保留历史版本配置（如 v0.13.0 基线配置）
5. **文档同步**: 更新配置后同步更新本指南和性能汇总文档

### 6.2 新增模型配置流程

```
1. 在 model_configs/ 目录创建 {模型名}.yaml 文件
2. 按照 YAML 结构规范填写所有字段
3. 在实际硬件上测试验证
4. 记录性能基准数据
5. 更新 SKILL.md 中的配置库表格
6. 更新 performance_data_summary.md 性能数据表
```

### 6.3 配置文件版本管理

- 每个配置文件包含 `最后更新` 日期字段
- 重大版本变更时保留历史配置（如 `DS_v3_1.yaml` 为 v0.13.0 基线）
- 配置变更需记录变更原因和性能影响

---

## 7. 注意事项

### 7.1 核心原则

> **有相同模型配置时，必须严格按照基准参数进行测试，不能随意修改参数！**

这是整个调优流程的第一原则。当存在相同模型的配置文件时：

1. **严格遵循**: 直接使用配置文件中的所有参数，不做任何修改
2. **先测后调**: 先用基准参数测试获得基线性能，再进行针对性调优
3. **记录偏差**: 如因环境差异必须修改参数，需记录修改原因和影响

### 7.2 量化模型说明

- 配置文件中标注了量化格式（如 W4A8、W8A8）
- 如果实际没有量化模型，可去掉 `--quantization ascend` 参数
- 量化模型路径需包含量化后缀（如 `/path/to/DeepSeek-V3.1-w4a8`）

### 7.3 跨平台配置

- 当前版本**不区分 A2/A3 配置**，统一使用最优配置
- 配置文件名中的 A2/A3 后缀仅用于信息显示，不影响参数选择
- 硬件检测（`npu-smi info`）仅用于信息记录

### 7.4 环境差异处理

当实际环境与配置文件不完全匹配时：

| 差异情况 | 处理方式 |
|----------|----------|
| 卡数不同 | 参见 [model_matching_guide.md](model_matching_guide.md) 经验微调指南 |
| 显存不足 | 降低 max_num_seqs 20-30%，或增大 TP |
| 无量化模型 | 去掉 `--quantization ascend`，降低 max_model_len |
| CANN 版本不同 | 核心参数不变，注意新版本特性开关兼容性 |
| 无精确匹配配置 | 参见 [model_matching_guide.md](model_matching_guide.md) 回退策略 |

### 7.5 常见问题

**Q: 配置文件中的环境变量是否全部必须设置？**

A: `HCCL_OP_EXPANSION_MODE="AIV"` 是必须的。其他环境变量根据场景选择，但建议全部设置以获得最佳性能。

**Q: 投机解码配置是否可以关闭？**

A: 可以。如果不需要投机解码，去掉 `--speculative-config` 参数即可，但 TPOT 会增加约 30-40%。

**Q: 不同场景如何切换配置？**

A: 同一模型配置文件中可能包含多个场景配置。低延迟场景关注 TPOT（~20ms），高吞吐场景关注吞吐量（max tps），根据目标选择对应参数集。

**Q: 配置文件中的参数是否适用于所有 CANN 版本？**

A: 核心参数（并行策略、批处理参数）通用。部分环境变量开关（如 `VLLM_ASCEND_ENABLE_*`）可能因 CANN/vllm-ascend 版本不同而有所差异，请参考 [env-variables.md](env-variables.md) 确认兼容性。
