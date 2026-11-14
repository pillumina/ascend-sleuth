\---

name: vllm-ascend-tuning

description: "vLLM-Ascend 推理服务全链路性能调优。当用户要求提升 vLLM-Ascend 推理速度/吞吐量、降低延迟（TTFT/TPOT）、选择并行策略（TP/DP/EP）、配置 Graph Mode/Speculative Decoding/量化/PD 分离、或做性能基准测试时使用。涵盖并行策略、编译优化、OS 级调优、torch_npu、CANN/HCCL、vLLM 参数等 Phase 0–11，内置主流模型已验证 YAML 配置。不用于 Prof 数据的事后分析与瓶颈定位（用 cluster-analysis）；不用于故障报错排查（用 issue-analyzer）；不包含服务部署启动本身。"

keywords:

 - vllm 调优

 - vllm 性能优化

 - ascend 推理优化

 - 昇腾推理性能

 - 吞吐量优化

 - 延迟优化

 - 并行策略

 - TP DP EP

 - tensor parallel

 - expert parallel

 - speculative decoding

 - MTP EAGLE

 - graph mode

 - cudagraph

 - 编译优化

 - LTO PGO

 - jemalloc tcmalloc

 - torch_npu 优化

 - HCCL 调优

 - CANN 优化

 - 量化推理

 - W4A8 W8A8

 - PD 分离

 - 性能基准

 - 环境变量调优

 - vllm bench

 - vllm 基准测试

 - 性能测试

 - 吞吐量测试

 - 延迟测试

 - TTFT TPOT

 - AISBench

\---



\# vLLM-Ascend 性能调优



\## 概述



本技能提供 vLLM-Ascend 系统级性能调优的完整工作流，涵盖从并行策略、编译、OS、框架到模型推理的全链路优化。



\*\*适用场景：\*\*

\- 用户要求提升 vLLM 推理速度/吞吐量

\- 用户询问如何配置最佳性能参数

\- 用户询问如何选择并行策略（TP/DP/EP）

\- 用户遇到推理延迟高或吞吐量不足的问题

\- 用户希望了解不同优化手段的效果对比

\- 用户需要配置 Speculative Decoding



\*\*不适用场景（请使用其他技能）：\*\*

\- 分析 Profiling 数据找瓶颈 -> cluster-analysis

\- 集群性能对比 -> cluster-compare

\- 两份单卡 Prof 对比 -> prof-compare

\- 现网故障/报错排查 -> issue-analyzer



\---



\## 快速配置模板



\### 低延迟场景 (TPOT \~20ms)



```bash

\# 环境变量

export VLLM_USE_V1=1

export HCCL_BUFFSIZE=500

export VLLM_ASCEND_ENABLE_MLAPO=1

export OMP_NUM_THREADS=10



\# vLLM 启动

vllm serve /path/to/model \\

 --data-parallel-size 2 \\

 --tensor-parallel-size 8 \\

 --enable-expert-parallel \\

 --max-num-seqs 96 \\

 --max-num-batched-tokens 6000 \\

 --speculative-config '{"num_speculative_tokens": 5, "method":"mtp"}' \\

 --compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY"}'

```



\### 高吞吐场景 (TPOT \~50ms)



```bash

\# 环境变量

export VLLM_USE_V1=1

export HCCL_BUFFSIZE=1024

export VLLM_ASCEND_ENABLE_FUSED_MC2=1

export OMP_NUM_THREADS=1



\# vLLM 启动

vllm serve /path/to/model \\

 --data-parallel-size 4 \\

 --tensor-parallel-size 4 \\

 --enable-expert-parallel \\

 --max-num-seqs 128 \\

 --max-num-batched-tokens 16384 \\

 --speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}' \\

 --compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY", 

                        "cudagraph_capture_sizes": \[1,4,8,16,32,64,128]}'

```



\---



\## 工作流



```

Phase 0: 确认调优目标与场景（低延迟 vs 高吞吐）

   |

Phase 0.5: ⭐ 模型基准配置匹配（YAML 配置库）- 必须首先执行

   |  - 检测硬件平台

   |  - 查找相同模型配置文件

   |  - ⭐ 严格按照基准参数配置生成启动命令

   |  - 按照基准参数启动服务并进行测试

   |

Phase 1: 并行策略选择（TP/DP/EP）

   |

Phase 2: 环境检查（NPU 状态、vLLM 版本、CANN 版本）

   |

Phase 3: 编译优化（LTO/PGO Python）

   |

Phase 4: OS 级调优（jemalloc/tcmalloc、CPU、NUMA、Swap）

   |

Phase 5: torch_npu 优化（内存分配、调度队列、CPU 亲和性）

   |

Phase 6: CANN / HCCL 调优（通信模式、RDMA、缓冲区）

   |

Phase 7: vLLM 参数调优（max_model_len、batch、Graph Mode）

   |

Phase 8: Speculative Decoding 配置

   |

Phase 9: 量化调优（W4A8、W8A8、W4A8C16）

   |

Phase 10: PD 分离架构（可选）

   |

Phase 11: ⭐ 性能验证与基准测试（默认使用 vllm bench）

   |  - 使用 vllm bench serve 进行在线服务测试

   |  - 使用 vllm bench throughput 进行离线吞吐量测试

   |  - 对比基准配置性能

   |  - AISBench 作为备选

```



\*\*重要提示\*\*: Phase 0.5 是必须首先执行的步骤，流程如下：

1\. 检测硬件平台

2\. \*\*查找相同模型的配置文件\*\* (如 Qwen3.5-27B → Qwen3.5-27B.yaml)

3\. \*\*读取基准参数配置\*\* (环境变量 + vLLM 启动参数)

4\. \*\*严格按照基准参数生成启动命令\*\*

5\. \*\*按照基准参数启动服务并进行测试\*\*

6\. 如果没有相同模型配置，回退到相似配置或经验配置



\---



\## Phase 0: 确认调优目标



首先确认用户的调优目标和当前环境：



```

\[?] 请确认调优目标：

 1. 优化首 token 延迟（TTFT） -> 低延迟场景 (TPOT \~20ms)

 2. 优化整体吞吐量（tokens/s） -> 高吞吐场景 (TPOT \~50ms)

 3. 优化 P99 尾延迟 -> 稳定性场景

 4. 内存优化（降低显存占用） -> 大模型/长序列场景

 5. 综合优化 -> 均衡方案



\[?] 当前环境信息：

 - NPU 型号与数量

 - CANN 版本

 - vLLM / vllm-ascend 版本

 - 模型名称与大小（是否 MoE）

 - 部署方式（裸机 / 容器）

```



\---



\## Phase 0.5: 模型基准配置匹配



> \*\*详细参考:\*\* \[model_config_guide.md](references/model_config_guide.md) | \[model_configs/](references/model_configs/)



\### 0.5.1 配置库说明



`model_configs/` 目录包含已验证的生产环境配置文件（YAML 格式），覆盖主流大模型：



| 模型系列 | 类型 | 配置文件 | 场景覆盖 |

|----------|------|----------|----------|

| DeepSeek-V3 | MoE | DeepSeek-V3.yaml | 高吞吐 |

| DeepSeek-V3.1 | MoE | DeepSeek-V3.1.yaml | 低延迟/高吞吐 |

| DeepSeek-V3.2 | MoE | DeepSeek-V3.2.yaml | 低延迟/高吞吐 |

| Qwen3-8B | Dense | Qwen3-8B.yaml | 低延迟/高吞吐 |

| Qwen3-30B | Dense | Qwen3-30B.yaml | 低延迟/高吞吐 |

| Qwen3-32B | Dense | Qwen3-32B.yaml | 高吞吐/性能基线 |

| Qwen3-235B-A22B | MoE | Qwen3-235B-A22B.yaml | 高吞吐 |

| Qwen3-MoE-480B | MoE | Qwen3-MoE-480B.yaml | 多机性能基线 |

| Qwen3.5-27B | Dense | Qwen3.5-27B.yaml | 最大长度/高吞吐/低延迟 |

| Qwen3.5-122B | MoE | Qwen3.5-122B.yaml | 最大长度/高吞吐/低延迟 |

| Qwen3.5-397B | MoE | Qwen3.5-397B.yaml | 最大长度/高吞吐/低延迟 |

| GLM-4 | Dense | GLM-4.yaml | 低延迟/高吞吐 |

| GLM-5.1 | MoE | GLM-5.1.yaml | 最大长度/PD分离 |

| Kimi-K2.5 | MoE | Kimi-K2.5.yaml | 高吞吐 |

| MiniMax-M2.5 | MoE | MiniMax-M2.5.yaml | 最大长度/高吞吐 |

| Qwen2.5-VL | 多模态 | Qwen2.5-VL.yaml | 多模态推理 |

| Qwen3-VL | 多模态 | Qwen3-VL.yaml | 多模态推理 |

| Qwen3-Embedding | Embedding | Qwen3-Embedding.yaml | 文本嵌入 |

| Qwen3-Reranker | Reranker | Qwen3-Reranker.yaml | 文档重排序 |



> \*\*注意\*\*: 配置文件中可能包含 A2/A3 后缀，但测试时不区分，统一使用最优配置。

> **版本兼容**: 配置文件基于特定版本的 vllm-ascend 和 CANN 验证。使用不同版本时，部分参数可能不兼容。建议检查配置文件中的参数是否在当前版本中受支持。v0.13.0.RC1 性能基线配置已标注版本信息。



\*\*新增 v0.13.0.RC1 性能基线配置：\*\*

\- `DeepSeek-V3.1.yaml` - DeepSeek-V3.1 A3 混部性能基线 (14 条记录)

\- `DeepSeek-V3.2.yaml` - DeepSeek-V3.2 A3 混部性能基线 (8 条记录)

\- `Qwen3-32B.yaml` - Qwen3-32B A3 混部性能基线 (13 条记录)

\- `Qwen3-MoE-480B.yaml` - Qwen3 MoE 480B 多机性能基线 (24 条记录)



\### 0.5.2 匹配流程 (必须严格遵守)



```

\[\*] Step 1: 检测硬件平台

   - 执行: npu-smi info | grep "910B"

   - 记录: 硬件型号 (仅用于信息显示)



\[\*] Step 2: 查找相同模型配置文件

   - 精确匹配：模型名完全相同 -> 使用该配置文件

   - 示例: 模型 Qwen3.5-27B -> 查找 Qwen3.5-27B.yaml



\[\*] Step 3: ⭐ 读取基准参数配置

   - 从 YAML 文件中提取:

     - 环境变量 (export ...)

     - vLLM 启动参数 (--tensor-parallel-size, --max-model-len 等)

     - 场景配置 (低延迟/高吞吐)



\[\*] Step 4: ⭐ 严格按照基准参数生成启动命令

   - 直接使用配置文件中的参数

   - 不做任何修改 (除非没有量化模型)



\[\*] Step 5: ⭐ 按照基准参数启动服务并进行测试

   - 使用生成的命令启动 vLLM

   - 运行性能测试

   - 记录测试结果



\[\*] 回退策略: 如果没有相同模型配置

   - 查找同系列模型配置 (如 Qwen3.5 → Qwen3)

   - 使用经验配置库

```



\### 0.5.2.1 自动硬件检测



```bash

\# 自动检测 NPU 型号（仅用于信息显示）

npu-smi info | grep "910B"



\# 识别规则:

\# 910B4 = A3

\# 910B2 = A2

```



\### 0.5.2.2 无精确匹配时的回退策略



| 匹配阶段 | 策略 | 示例 |

|----------|------|------|

| \*\*阶段1\*\* | 同型号不同场景 | Qwen3.5-27B 高吞吐 → 低延迟 |

| \*\*阶段2\*\* | 同系列不同型号 | Qwen3.5-27B → Qwen3.5-122B |

| \*\*阶段3\*\* | 同系列不同版本 | Qwen3.5 → Qwen3 |

| \*\*阶段4\*\* | 相似规模模型 | 27B → 32B |

| \*\*阶段5\*\* | 经验配置库 | 使用默认经验配置 |



\### 0.5.2.3 跨平台配置说明



> \*\*注意\*\*: 当前版本不区分 A2/A3 配置，统一使用最优配置。



\### 0.5.3 读取配置文件



```python

\# 示例：读取 DeepSeek-V3.1 A3 配置

read_file("references/model_configs/DeepSeek-V3.1.yaml")



\# 示例：读取性能汇总

read_file("references/performance_data_summary.md")

```



\### 0.5.4 提取关键配置



从 YAML 文件提取以下内容作为调优基准：



\*\*环境变量：\*\*

\- `HCCL_OP_EXPANSION_MODE`（必须为 AIV）

\- `HCCL_BUFFSIZE`（低延迟: 256-500, 高吞吐: 500-1024）

\- `OMP_NUM_THREADS`（低延迟: 10, 高吞吐: 1）

\- `VLLM_ASCEND_ENABLE_\*` 系列优化开关

\- 网络配置（`HCCL_IF_IP`, `\*_SOCKET_IFNAME`）



\*\*vLLM 启动参数：\*\*

\- 并行策略（`--data-parallel-size`, `--tensor-parallel-size`, `--enable-expert-parallel`）

\- 批处理参数（`--max-num-seqs`, `--max-num-batched-tokens`）

\- Speculative Decoding 配置（`--speculative-config`）

\- Graph Mode 配置（`--compilation-config`）



\### 0.5.5 基准配置应用示例



\*\*场景：用户要部署 DeepSeek-V3.1，A3 单机 8 卡，低延迟\*\*



```bash

\# Step 1: 读取配置文件

\# 从 DeepSeek-V3.1.yaml 低延迟场景提取



\# Step 2: 应用环境变量

export HCCL_OP_EXPANSION_MODE="AIV"

export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"

export HCCL_BUFFSIZE=500

export OMP_NUM_THREADS=10

export TASK_QUEUE_ENABLE=1

export VLLM_USE_V1=1

export VLLM_ASCEND_ENABLE_MLAPO=1

export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libjemalloc.so.2:$LD_PRELOAD



\# Step 3: 应用 vLLM 启动参数

vllm serve /path/to/DeepSeek-V3.1-w4a8 \\

 --data-parallel-size 2 \\

 --tensor-parallel-size 8 \\

 --enable-expert-parallel \\

 --max-num-seqs 96 \\

 --max-num-batched-tokens 6000 \\

 --max-model-len 65536 \\

 --quantization ascend \\

 --speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}' \\

 --compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY"}'



\# Step 4: 根据实际情况微调

\# - 如果显存不足：降低 max-num-seqs 或 max-model-len

\# - 如果延迟偏高：检查 HCCL_BUFFSIZE 或 OMP_NUM_THREADS

```



\### 0.5.6 性能参考数据



| 模型 | 场景 | 卡数 | 单卡吞吐 | TPOT | 数据来源 |

|------|------|------|----------|------|----------|

| DeepSeek-V3.1 | 低延迟 | 8 | 95 tps | 20ms | DeepSeek-V3.1.yaml |

| DeepSeek-V3.1 | 高吞吐 | 8 | 280 tps | 48ms | DeepSeek-V3.1.yaml |

| DeepSeek-V3.1 | 高吞吐(v0.13.0) | 8 | 457 tps | 45ms | DeepSeek-V3.1.yaml |

| DeepSeek-V3.2 | 高吞吐(v0.13.0) | 8 | 520 tps | 42ms | DeepSeek-V3.2.yaml |

| Qwen3-32B | 高吞吐(v0.13.0) | 8 | 680 tps | 38ms | Qwen3-32B.yaml |

| Qwen3 MoE 480B | 高吞吐(v0.13.0) | 32 | 150 tps | 50ms | Qwen3-MoE-480B.yaml |

| Qwen3.5-397B | 低延迟 | 16 | 173 tps | 21ms | Qwen3.5-397B.yaml |

| Qwen3.5-122B | 低延迟 | 4 | 467 tps | 23ms | Qwen3.5-122B.yaml |

| Qwen3.5-27B | 低延迟 | 2 | 640 tps | 20ms | Qwen3.5-27B.yaml |

| Kimi-K2.5 | 高吞吐 | 16 | 335 tps | 40ms | Kimi-K2.5.yaml |



\### 0.5.7 经验微调指南



当基准配置与实际环境不完全匹配时，按以下规则调整：



| 差异 | 调整方向 |

|------|----------|

| 卡数更多 | 增加 DP 或 TP，保持 TPOT 目标 |

| 卡数更少 | 减少 DP 优先，必要时降低 max-model-len |

| 显存不足 | 降低 max-num-seqs 20-30%，或增大 TP |

| 延迟偏高 | 检查 OMP_NUM_THREADS，减小 HCCL_BUFFSIZE |

| 吞吐不足 | 增加 max-num-seqs，增大 HCCL_BUFFSIZE |



\### 0.5.8 经验配置库 (最终回退)



> \*\*详细参考:\*\* \[model_matching_guide.md](references/model_matching_guide.md)



当没有任何匹配配置时，使用以下经验配置：



\#### MoE 模型经验配置



```bash

\# 环境变量

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



\# vLLM 参数

vllm serve /path/to/model \\

 --tensor-parallel-size 8 \\

 --max-model-len 8192 \\

 --max-num-batched-tokens 8192 \\

 --max-num-seqs 128 \\

 --gpu-memory-utilization 0.9 \\

 --async-scheduling \\

 --speculative-config '{"num_speculative_tokens": 3, "method":"qwen3_5_mtp", "enforce_eager": true}' \\

 --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY", "cudagraph_capture_sizes":\[4,8,12,16,20,24,28,32,36,40,44,48,52,56,60,64,68,72,76,80,84,88,92,96,100,104,108,112,116,120,124,128]}' \\

 --additional-config '{"enable_cpu_binding":true, "multistream_overlap_shared_expert": true, "enable_weight_nz_layout":true}'

```



\#### Dense 模型经验配置



```bash

\# 环境变量

export HCCL_OP_EXPANSION_MODE="AIV"

export HCCL_BUFFSIZE=1024

export OMP_NUM_THREADS=1

export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"



\# vLLM 参数

vllm serve /path/to/model \\

 --tensor-parallel-size 8 \\

 --max-model-len 8192 \\

 --max-num-batched-tokens 16384 \\

 --max-num-seqs 256 \\

 --gpu-memory-utilization 0.9 \\

 --speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}' \\

 --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}'

```



\---



\## Phase 1: 并行策略选择



> \*\*详细参考:\*\* \[parallel_strategy.md](references/parallel_strategy.md)



\### 1.1 场景与策略对照



| 场景 | 模型规模 | 推荐策略 | 说明 |

|------|----------|----------|------|

| 低延迟 | 大模型(397B) | DP1+TP16 | 最大 TP 减少通信 |

| 低延迟 | 中模型(122B) | DP1+TP4 | 平衡配置 |

| 低延迟 | 小模型(27B) | DP1+TP2 | 单机小卡 |

| 高吞吐 | 大模型 | DP1+TP16 | 保持大 TP |

| 高吞吐 | DeepSeek系列 | DP4+TP4 | 平衡 DP/TP |

| 最大长度 | 所有模型 | 最大 TP | 减少显存碎片 |



\### 1.2 MoE 模型必须配置



```bash

\# MoE 模型必须启用 Expert-Parallel

\--enable-expert-parallel



\# EP 大小通常等于总卡数

\# 例如 16 卡: EP16

```



\### 1.3 关键原则



```

\[\*] 低延迟场景:

 - 优先增大 TP，减少通信开销

 - DP 尽量小 (DP1 或 DP2)

 - 使用 Speculative Decoding 加速



\[\*] 高吞吐场景:

 - DP/TP 平衡配置 (如 DP4+TP4)

 - 增大 max-num-seqs 提升并发

 - 适当放宽 TPOT 要求到 50ms



\[\*] MoE 模型:

 - 必须启用 --enable-expert-parallel

 - EP 大小 = 总卡数

 - Shared Expert 可启用 DP

```



\---



\## Phase 2: 环境检查



```bash

\# NPU 状态

npu-smi info



\# CANN 版本

cat /usr/local/Ascend/ascend-toolkit/latest/version.cfg 2>/dev/null || \\

cat /usr/local/Ascend/version.cfg 2>/dev/null



\# vLLM 版本

pip show vllm vllm-ascend



\# PyTorch / torch_npu 版本

python -c "import torch; print(torch.__version__)"

python -c "import torch_npu; print(torch_npu.__version__)"



\# 系统信息

uname -a

cat /etc/os-release

```



\---



\## Phase 3: 编译优化



> \*\*详细参考:\*\* \[compilation.md](references/compilation.md)



\### 3.1 安装优化版 Python（LTO + PGO）



```bash

\# 下载预编译优化版 Python 3.11（Bisheng 编译器）

mkdir -p /workspace/tmp \&\& cd /workspace/tmp

wget https://repo.oepkgs.net/ascend/pytorch/vllm/python/py311_bisheng.tar.gz

tar -zxvf ./py311_bisheng.tar.gz -C /usr/local/

mv /usr/local/py311_bisheng/ /usr/local/python

export PATH=/usr/bin:/usr/local/python/bin:$PATH

```



\*\*重要提示：\*\* 编译优化需在安装 vLLM/vllm-ascend 之前完成。



\---



\## Phase 4: OS 级调优



> \*\*详细参考:\*\* \[os_level.md](references/os_level.md)



\### 4.1 jemalloc 优化



jemalloc 是多线程场景下性能优秀的内存分配器，可减少内存碎片和锁竞争。



```bash

\# 安装

sudo apt update

sudo apt install libjemalloc2



\# 配置（在启动 vLLM 前设置）

export LD_PRELOAD=/usr/lib/"$(uname -i)"-linux-gnu/libjemalloc.so.2:$LD_PRELOAD

```



\### 4.2 TCMalloc 优化



TCMalloc 通过多级缓存结构减少互斥锁竞争，优化大对象处理。



```bash

\# 安装

sudo apt update

sudo apt install libgoogle-perftools4 libgoogle-perftools-dev



\# 查找 libtcmalloc.so 位置

find /usr -name libtcmalloc.so\*



\# 配置（优先级高于 jemalloc）

export LD_PRELOAD="$LD_PRELOAD:/usr/lib/aarch64-linux-gnu/libtcmalloc.so"



\# 验证

ldd `which python`

```



\### 4.3 CPU 性能模式



```bash

\# 设置为 performance 模式（需 root 权限）

echo performance | tee /sys/devices/system/cpu/cpu\*/cpufreq/scaling_governor

```



\*\*效果：\*\* 保持 CPU 最高频率，减少延迟抖动。



\### 4.4 禁用 Swap



```bash

\# 最小化 swap 倾向（需 root 权限）

sysctl -w vm.swappiness=0

```



\*\*效果：\*\* 防止 swap 导致的秒级延迟抖动，推荐值 0 或 1。



\### 4.5 禁用自动 NUMA 平衡



```bash

\# 关闭自动 NUMA 页面迁移（需 root 权限）

sysctl -w kernel.numa_balancing=0

```



\*\*适用场景：\*\* 多路服务器、显式 NUMA 绑定的 Ascend NPU 部署。



\### 4.6 提高调度迁移成本



```bash

sysctl -w kernel.sched_migration_cost_ns=50000

```



\*\*效果：\*\* 减少线程频繁迁移，提高 CPU 缓存局部性，降低延迟抖动。推荐范围 50000-100000 ns。



\---



\## Phase 5: torch_npu 优化



> \*\*详细参考:\*\* \[torch_npu.md](references/torch_npu.md)



```bash

\# 内存优化

export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"



\# 调度优化

export TASK_QUEUE_ENABLE=1

```



\---



\## Phase 6: CANN / HCCL 调优



> \*\*详细参考:\*\* \[cann_hccl.md](references/cann_hccl.md) | \[env-variables.md](references/env-variables.md)



\### 6.1 核心环境变量



```bash

\# HCCL AIV 模式（必须）

export HCCL_OP_EXPANSION_MODE="AIV"



\# HCCL 缓冲区大小（低延迟: 256-500, 高吞吐: 500-1024）

export HCCL_BUFFSIZE=500



\# 网络配置

export HCCL_IF_IP=$local_ip

export GLOO_SOCKET_IFNAME=$nic_name

export TP_SOCKET_IFNAME=$nic_name

export HCCL_SOCKET_IFNAME=$nic_name

```



\---



\## Phase 7: vLLM 参数调优



> \*\*详细参考:\*\* \[vllm-parameters.md](references/vllm-parameters.md) | \[graph_mode.md](references/graph_mode.md)



\### 7.1 关键参数对照



| 参数 | 低延迟 | 高吞吐 | 说明 |

|------|--------|--------|------|

| `max-num-seqs` | 64-96 | 128-1000 | 并发序列数 |

| `max-num-batched-tokens` | 4000-6000 | 9000-16384 | 批处理 token 数 |

| `gpu-memory-utilization` | 0.9 | 0.9 | 显存利用率 |

| `speculative-tokens` | 5 | 3 | 推测 token 数 |



\### 7.2 Graph Mode 配置



```bash

\# 低延迟: 小 batch sizes

\--compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY",

 "cudagraph_capture_sizes": \[1,6,12,18,24,30,36,42,48,54,72,96,108,144,192]}'



\# 高吞吐: 大 batch sizes  

\--compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY",

 "cudagraph_capture_sizes": \[1,4,8,16,32,64,96,128,192,256,384,512]}'

```



\---



\## Phase 8: Speculative Decoding 配置



> \*\*详细参考:\*\* \[speculative_decoding.md](references/speculative_decoding.md)



\### 8.1 模型方法选择



| 模型系列 | 方法 | num_tokens |

|----------|------|------------|

| DeepSeek-V3.1 | mtp | 3 |

| DeepSeek-V3.2 | deepseek_mtp | 3 |

| Qwen3.5 | qwen3_5_mtp | 3-5 |

| Kimi-K2.5 | eagle3 | 3 |

| GLM-5.1 | deepseek_mtp | 3 |



\### 8.2 配置示例



```bash

\# DeepSeek-V3.1

\--speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}'



\# Qwen3.5 (低延迟用 5 tokens)

\--speculative-config '{"method": "qwen3_5_mtp", "num_speculative_tokens": 5}'

```



\---



\
> **注意**: 部分模型（如 Qwen3.5）的投机解码配置中包含 `enforce_eager: true`，这是**投机解码 drafter 模型**的要求，与主模型的 `cudagraph_mode: FULL_DECODE_ONLY` 不冲突。主模型仍然运行在 Graph Mode 下，仅 drafter 部分使用 eager 模式。两者可以安全共存。


---

## Phase 9: 量化调优



> \*\*详细参考:\*\* \[quantization.md](references/quantization.md)



\### 9.1 量化格式选择



| 格式 | 内存节省 | 加速比 | 适用模型 |

|------|----------|--------|----------|

| W4A8 | \~75% | 2-3x | DeepSeek-V3.1 |

| W8A8 | \~50% | 1.5-2x | DeepSeek-V3.2 |

| W4A8C16 | \~70% | 2x | Qwen3.5, Kimi |

| W8A8C16 | \~50% | 1.5x | GLM-5.1 |



\### 9.2 量化模型部署



```bash

vllm serve /path/to/quantized-model \\

 --quantization ascend \\

 --max-model-len 4096

```



\---



\## Phase 10: PD 分离架构（可选）



> \*\*详细参考:\*\* \[pd_separation.md](references/pd_separation.md)



\### 10.1 适用场景



\- 超长上下文 (> 64K)

\- 高并发且输入长度差异大

\- 需要独立优化 TTFT

\- 大型 MoE 模型



\### 10.2 配置要点



```

Prefill 节点: 高 TP (TP8-16), 低 DP (DP2-4)

Decode 节点:  高 DP (DP32), 低 TP (TP1)

```



\---



\## Phase 11: 性能验证与基准测试



> \*\*重要\*\*: 默认使用 \*\*vLLM 内置基准测试工具\*\* (`vllm bench`) 进行性能测试。

> AISBench (`ais-bench`) 作为备选工具，用于更复杂的评估场景。



\### 11.1 vLLM 内置基准测试 (默认推荐)



vLLM 内置的基准测试工具与 vLLM 官方项目保持一致，支持离线吞吐量和在线服务性能测试。



\#### 11.1.1 在线服务基准测试 (vllm bench serve)



```bash

\# 启动 vLLM 服务

export VLLM_USE_MODELSCOPE=True

vllm serve /path/to/model --tensor-parallel-size 8



\# 运行基准测试

vllm bench serve \\

 --backend vllm \\

 --model /path/to/model \\

 --endpoint /v1/completions \\

 --dataset-name sharegpt \\

 --dataset-path /path/to/ShareGPT_V3_unfiltered_cleaned_split.json \\

 --num-prompts 100

```



\*\*输出指标:\*\*

```

============ Serving Benchmark Result ============

Successful requests:                     100       

Failed requests:                         0         

Benchmark duration (s):                  19.92     

Total input tokens:                      1374      

Total generated tokens:                  2663      

Request throughput (req/s):              0.50      

Output token throughput (tok/s):         133.67    

Peak output token throughput (tok/s):    312.00    

Peak concurrent requests:                10.00     

Total Token throughput (tok/s):          202.64    

\---------------Time to First Token----------------

Mean TTFT (ms):                          127.10    

Median TTFT (ms):                        136.29    

P99 TTFT (ms):                           137.83    

\-----Time per Output Token (excl. 1st token)------

Mean TPOT (ms):                          25.85     

Median TPOT (ms):                        25.78     

P99 TPOT (ms):                           26.64     

\---------------Inter-token Latency----------------

Mean ITL (ms):                           25.78     

Median ITL (ms):                         25.74     

P99 ITL (ms):                            28.85     

==================================================

```



\#### 11.1.2 离线吞吐量基准测试 (vllm bench throughput)



```bash

vllm bench throughput \\

 --model /path/to/model \\

 --dataset-name random \\

 --input-len 128 \\

 --output-len 128 \\

 --num-prompts 100

```



\*\*输出指标:\*\*

```

Processed prompts: 100%|█| 10/10 \[00:03<00:00,  2.74it/s, est. speed input: 351.02 toks/s, output: 351.02 toks/s]

Throughput: 2.73 requests/s, 699.93 total tokens/s, 349.97 output tokens/s

Total num prompt tokens:  1280

Total num output tokens:  1280

```



\### 11.2 支持的数据集



| 数据集 | 在线 | 离线 | 数据路径 |

|--------|------|------|----------|

| ShareGPT | ✅ | ✅ | `wget https://huggingface.co/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json` |

| ShareGPT4V (Image) | ✅ | ✅ | `wget https://huggingface.co/datasets/Lin-Chen/ShareGPT4V/resolve/main/sharegpt4v_instruct_gpt4-vision_cap100k.json` |

| BurstGPT | ✅ | ✅ | `wget https://github.com/HPMLL/BurstGPT/releases/download/v1.1/BurstGPT_without_fails_2.csv` |

| Random | ✅ | ✅ | `synthetic` |

| RandomForReranking | ✅ | ✅ | `synthetic` |

| Prefix Repetition | ✅ | ✅ | `synthetic` |

| HuggingFace-VisionArena | ✅ | ✅ | `lmarena-ai/VisionArena-Chat` |

| HuggingFace-MTBench | ✅ | ✅ | `philschmid/mt-bench` |

| Spec Bench | ✅ | ✅ | `wget https://raw.githubusercontent.com/hemingkx/Spec-Bench/refs/heads/main/data/spec_bench/question.jsonl` |

| Custom | ✅ | ✅ | Local file: `data.jsonl` |



\### 11.3 vLLM Bench 常用参数



| 参数 | 说明 | 示例 |

|------|------|------|

| `--backend` | 后端类型 | `vllm`, `openai-chat`, `openai-embeddings` |

| `--model` | 模型路径或名称 | `/model/Qwen3.5-27B` |

| `--endpoint` | API 端点 | `/v1/completions`, `/v1/chat/completions`, `/v1/embeddings` |

| `--dataset-name` | 数据集名称 | `sharegpt`, `random`, `hf` |

| `--dataset-path` | 数据集路径 | `/path/to/data.jsonl` |

| `--num-prompts` | 测试请求数 | `100` |

| `--concurrency` | 并发数 | `8` |

| `--input-len` | 输入长度 (random) | `128` |

| `--output-len` | 输出长度 (random) | `128` |

| `--max-tokens` | 最大生成 token 数 | `512` |

| `--no-stream` | 禁用流式输出 | `--no-stream` |



\### 11.4 基准测试工作流



```

\[\*] Step 1: 启动 vLLM 服务（使用 Phase 0.5 基准配置）

   vllm serve /path/to/model <基准参数>



\[\*] Step 2: 运行 vLLM 基准测试

   # 在线服务测试

   vllm bench serve --model /path/to/model --dataset-name sharegpt --num-prompts 100

   

   # 离线吞吐量测试

   vllm bench throughput --model /path/to/model --dataset-name random --input-len 128 --output-len 128



\[\*] Step 3: 记录测试结果

   - TTFT (Time to First Token)

   - TPOT (Time per Output Token)

   - 吞吐量 (tokens/s)

   - 成功率



\[\*] Step 4: 与基准配置对比

   - 如有相同模型配置，对比性能差异

   - 分析性能差距原因

```



\### 11.5 AISBench 备选方案



当需要更复杂的评估场景时，使用 AISBench (见 `ais-bench` skill):



```bash

\# 安装 AISBench

pip install ais-bench



\# 运行 AISBench 评估

ais-bench --model /path/to/model \\

 --backend vllm \\

 --dataset-name mmlu \\

 --num-shots 5

```



\*\*使用 AISBench 的场景:\*\*

\- 需要标准化的基准数据集 (MMLU, GSM8K, etc.)

\- 需要多轮对话测试

\- 需要 Function Call 测试

\- 需要与公开排行榜对比



\---



\

---


## 常见问题速查

| 症状 | 首检项 | 调整方向 |
|------|--------|----------|
| OOM (显存不足) | gpu-memory-utilization, max-num-seqs | 降低 max-num-seqs 20-30%，或增大 TP |
| TPOT 偏高 | OMP_NUM_THREADS, HCCL_BUFFSIZE | 低延迟场景: 升 OMP_NUM_THREADS(10), 降 HCCL_BUFFSIZE(256-500) |
| TTFT 偏高 | TP/DP 配比, max-num-batched-tokens | 增大 TP, 调整 max-num-batched-tokens |
| 吞吐不足 | max-num-seqs, DP | 增大 max-num-seqs, 增加 DP |
| 通信超时 | HCCL_CONNECT_TIMEOUT, HCCL_EXEC_TIMEOUT | 增大超时值至 600+ |
| Graph Mode 失败 | 不支持的算子 | 降级为 PARTIAL 模式或 --enforce-eager |
| 启动慢 | cudagraph_capture_sizes | 减少捕获的 batch size 数量 |
| 首请求慢 | Graph 编译开销 | 正常现象, 预热后测试 |
| MoE 性能差 | 缺少 --enable-expert-parallel | 必须添加 --enable-expert-parallel |
| 多卡性能差 | HCCL_OP_EXPANSION_MODE | 确保设置为 AIV |
| CPU 抖动 | CPU 频率模式, NUMA | 设置 performance 模式, 禁用 NUMA balancing |

---

## 调优清单



```

\[OK] Phase 0: 确认调优目标

\[OK] Phase 0.5: ⭐ 模型基准配置匹配（必须首先执行）

     \[✓] 检测硬件平台

     \[✓] 查找相同模型配置文件 (如 Qwen3.5-27B → Qwen3.5-27B.yaml)

     \[✓] ⭐ 读取基准参数配置 (环境变量 + vLLM 启动参数)

     \[✓] ⭐ 严格按照基准参数生成启动命令

     \[✓] ⭐ 按照基准参数启动服务并进行测试

     \[--] 如果无相同模型：使用回退策略

         - 查找同系列配置

         - 使用经验配置库

\[OK] Phase 1: 并行策略选择 (TP/DP/EP)

\[OK] Phase 2: 环境检查

\[OK] Phase 3: 编译优化 (LTO/PGO Python)

\[OK] Phase 4: OS 级调优

     \[--] jemalloc

     \[--] CPU performance mode

     \[--] 禁用 Swap/NUMA

\[OK] Phase 5: torch_npu 优化

\[OK] Phase 6: CANN / HCCL 调优

\[OK] Phase 7: vLLM 参数调优

     \[--] max-num-seqs

     \[--] Graph Mode capture sizes

\[OK] Phase 8: Speculative Decoding

\[OK] Phase 9: 量化调优

\[OK] Phase 10: PD 分离（可选）

\[OK] Phase 11: 性能验证

```



\*\*重要\*\*: 有相同模型配置时，必须严格按照基准参数进行测试，不能随意修改参数！



\---



\

---

## 参考文档 (References)



本技能包含以下参考文档，位于 `references/` 目录：



\### 模型基准配置（优先使用）



| 文档 | 内容 | 调优阶段 |

|------|------|----------|

| \[model_config_guide.md](references/model_config_guide.md) | 模型基准配置使用指南 | Phase 0.5 |

| \[model_configs/](references/model_configs/) | 已验证的 YAML 配置库 | Phase 0.5 |

| - Qwen3.5-\*.yaml | Qwen3.5 系列配置 | Phase 0.5 |

| - DeepSeek-\*.yaml | DeepSeek 系列配置 | Phase 0.5 |

| - performance_data_summary.md | 性能对比数据 | Phase 0.5 |



\### 调优技术文档



| 文档 | 内容 | 调优阶段 |

|------|------|----------|

| \[parallel_strategy.md](references/parallel_strategy.md) | 并行策略选择指南 (TP/DP/EP) | Phase 1 |

| \[env-variables.md](references/env-variables.md) | 完整环境变量清单 | Phase 5-6 |

| \[graph_mode.md](references/graph_mode.md) | Graph Mode 配置详解 | Phase 7 |

| \[speculative_decoding.md](references/speculative_decoding.md) | Speculative Decoding 配置 | Phase 8 |

| \[quantization.md](references/quantization.md) | 量化格式选择指南 | Phase 9 |

| \[pd_separation.md](references/pd_separation.md) | PD 分离架构配置 | Phase 10 |

| \[performance_data_summary.md](references/performance_data_summary.md) | 性能基准数据汇总 | Phase 11 |

| \[vllm-parameters.md](references/vllm-parameters.md) | vLLM 参数详解 (CLI/Python API) | Phase 7 |

| \[torch_npu.md](references/torch_npu.md) | torch_npu 优化 | Phase 5 |

| \[cann_hccl.md](references/cann_hccl.md) | CANN/HCCL 调优 | Phase 6 |

| \[os_level.md](references/os_level.md) | OS 级优化 | Phase 4 |

| \[compilation.md](references/compilation.md) | 编译优化 | Phase 3 |

| \[benchmark.md](references/benchmark.md) | 基准测试方法 | Phase 11 |

| \[cpu_binding.md](references/cpu_binding.md) | CPU 亲和性配置 | Phase 5 |



\### 功能配置与启动模板



| 文档 | 内容 | 用途 |

|------|------|------|

| \[features.md](references/features.md) | 功能支持矩阵与配置 | 功能开关配置 |

| \[launch_templates.md](references/launch_templates.md) | 启动脚本模板索引 | 快速部署参考 |



\*\*使用方式：\*\* 遇到具体调优问题时，使用 `read_file` 读取对应的参考文档获取详细配置说明。



```

\# 示例：读取模型基准配置

read_file("references/model_configs/DeepSeek-V3.1.yaml")



\# 示例：读取模型配置使用指南

read_file("references/model_config_guide.md")



\# 示例：读取 Graph Mode 详细文档

read_file("references/graph_mode.md")

```



