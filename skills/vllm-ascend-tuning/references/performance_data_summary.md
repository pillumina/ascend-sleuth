# 性能基准数据汇总

> **适用阶段:** Phase 11 - 性能验证与基准测试
>
> **关联文档:** [SKILL.md](../SKILL.md) | [model_config_guide.md](model_config_guide.md) | [model_matching_guide.md](model_matching_guide.md) | [benchmark.md](benchmark.md) | [model_configs/](model_configs/)

---

## 1. 概述

本文档汇总了 vLLM-Ascend 平台上主流大模型的性能基准测试数据，为性能调优提供参考基线。所有数据均来自实际硬件测试，覆盖低延迟和高吞吐两大场景。

### 1.1 数据来源

- **测试平台**: Atlas 800I A3-560T (HBM 128G)
- **测试工具**: vLLM 内置基准测试工具 (`vllm bench serve` / `vllm bench throughput`)
- **数据集**: ShareGPT（在线服务测试）、Random（离线吞吐量测试）
- **配置来源**: `model_configs/` 目录中已验证的 YAML 配置文件

### 1.2 测试环境

| 项目 | 规格 |
|------|------|
| 硬件平台 | Atlas 800I A3-560T |
| NPU 型号 | Ascend 910B4 (A3) |
| HBM 显存 | 128 GB / 卡 |
| NPU 数量 | 2-32 卡（视模型规模） |
| 操作系统 | Linux (aarch64) |
| 推理框架 | vLLM + vllm-ascend |
| 通信库 | HCCL (CANN) |

### 1.3 指标说明

| 指标 | 全称 | 说明 |
|------|------|------|
| TPOT | Time per Output Token | 每个输出 token 的生成时间（不含首 token），单位 ms |
| TTFT | Time to First Token | 首 token 延迟，单位 ms |
| 单卡吞吐 | Output Token Throughput per NPU | 单张 NPU 的输出 token 吞吐量，单位 tokens/s (tps) |
| 加速比 | Speedup Ratio | 优化后性能相对于基线的提升倍数 |

---

## 2. 性能参考数据

### 2.1 完整性能基准数据

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

### 2.2 数据解读

#### 低延迟场景（TPOT ~20-25ms）

低延迟场景以最小化 TPOT 为目标，适用于实时对话、交互式问答等对响应速度敏感的应用。

| 模型 | 卡数 | 单卡吞吐 | TPOT | 特点 |
|------|------|----------|------|------|
| DeepSeek-V3.1 | 8 | 95 tps | 20ms | MoE 大模型，W4A8 量化 |
| Qwen3.5-397B | 16 | 173 tps | 21ms | Dense 超大模型，需 16 卡 |
| Qwen3.5-122B | 4 | 467 tps | 23ms | Dense 中型模型，4 卡高效 |
| Qwen3.5-27B | 2 | 640 tps | 20ms | Dense 小型模型，2 卡最优 TPOT |

**低延迟场景规律:**
- 模型越小，单卡吞吐越高（27B > 122B > 397B）
- TPOT 目标统一在 20-25ms 范围
- 小模型可用更少卡数达到目标 TPOT

#### 高吞吐场景（TPOT ~38-50ms）

高吞吐场景以最大化吞吐量为目标，适用于批量处理、离线推理等对吞吐量敏感的应用。

| 模型 | 卡数 | 单卡吞吐 | TPOT | 特点 |
|------|------|----------|------|------|
| Qwen3-32B | 8 | 680 tps | 38ms | Dense 模型，v0.13.0 优化后最高吞吐 |
| DeepSeek-V3.2 | 8 | 520 tps | 42ms | MoE 模型，v0.13.0 性能提升 |
| DeepSeek-V3.1 | 8 | 457 tps | 45ms | MoE 模型，v0.13.0 基线 |
| DeepSeek-V3.1 | 8 | 280 tps | 48ms | MoE 模型，早期版本基线 |
| Kimi-K2.5 | 16 | 335 tps | 40ms | MoE 大模型，16 卡部署 |
| Qwen3 MoE 480B | 32 | 150 tps | 50ms | 超大 MoE 模型，32 卡多机部署 |

**高吞吐场景规律:**
- v0.13.0 版本性能显著提升（DeepSeek-V3.1: 280 → 457 tps，提升 63%）
- Dense 模型（Qwen3-32B）在高吞吐场景表现优于 MoE 模型
- MoE 超大模型（480B）需要多机部署，单卡吞吐较低

### 2.3 版本性能对比

v0.13.0 版本带来了显著的性能提升：

| 模型 | 版本 | 单卡吞吐 | 提升幅度 |
|------|------|----------|----------|
| DeepSeek-V3.1 | 早期版本 | 280 tps | 基线 |
| DeepSeek-V3.1 | v0.13.0 | 457 tps | +63% |
| DeepSeek-V3.2 | v0.13.0 | 520 tps | +86% (vs V3.1 早期) |

---

## 3. 投机解码性能提升对比

投机解码（Speculative Decoding）通过预测后续 token 来减少推理轮次，显著降低 TPOT。

### 3.1 投机解码效果对比

| 模型 | 无投机解码 | 有投机解码 | 加速比 |
|------|-----------|-----------|--------|
| DeepSeek-V3.1 | 20ms TPOT | 15ms | 1.3x |
| Qwen3.5-397B | 25ms TPOT | 18ms | 1.4x |
| Kimi-K2.5 | 40ms TPOT | 28ms | 1.4x |

### 3.2 投机解码分析

**加速效果:**
- 平均加速比: 1.3x - 1.4x
- TPOT 降低: 25%-30%
- 对低延迟场景提升尤为明显

**各模型投机解码方法:**

| 模型 | 投机解码方法 | num_speculative_tokens | 加速比 |
|------|------------|----------------------|--------|
| DeepSeek-V3.1 | mtp | 3 | 1.3x |
| DeepSeek-V3.2 | deepseek_mtp | 3 | ~1.3x |
| Qwen3.5-397B | qwen3_5_mtp | 3-5 | 1.4x |
| Kimi-K2.5 | eagle3 | 3 | 1.4x |
| GLM-5.1 | deepseek_mtp | 3 | ~1.3x |

**投机解码配置建议:**
- 低延迟场景: `num_speculative_tokens` 设为 5，最大化加速效果
- 高吞吐场景: `num_speculative_tokens` 设为 3，平衡加速和计算开销
- 投机解码方法必须与模型匹配，详见 [speculative_decoding.md](speculative_decoding.md)

---

## 4. 量化格式性能对比

量化通过降低权重和/或激活值的精度来减少显存占用和计算量，从而提升吞吐量。

### 4.1 量化格式对比

| 格式 | 相对吞吐 | 精度损失 | 适用场景 |
|------|---------|---------|---------|
| FP16/BF16 | 1.0x | 基线 | 精度优先 |
| W8A16 | 1.1-1.3x | <1% | 企业应用 |
| W8A8 | 1.5-2.0x | 1-3% | 生产部署 |
| W4A8 | 2.0-3.0x | 3-5% | 高吞吐 |

### 4.2 量化格式说明

#### FP16/BF16（基线）
- **精度**: 全精度浮点
- **显存占用**: 最高
- **吞吐量**: 基线 (1.0x)
- **精度损失**: 无
- **适用场景**: 对精度要求极高的场景，如科研、评测

#### W8A16（权重8位量化）
- **精度**: 权重 8-bit，激活 16-bit
- **显存节省**: ~50%
- **吞吐量提升**: 10%-30%
- **精度损失**: <1%
- **适用场景**: 企业应用，精度敏感但可接受轻微量化

#### W8A8（权重8位+激活8位量化）
- **精度**: 权重 8-bit，激活 8-bit
- **显存节省**: ~50%
- **吞吐量提升**: 50%-100%
- **精度损失**: 1%-3%
- **适用场景**: 生产部署，性能与精度的平衡点

#### W4A8（权重4位+激活8位量化）
- **精度**: 权重 4-bit，激活 8-bit
- **显存节省**: ~75%
- **吞吐量提升**: 100%-200%
- **精度损失**: 3%-5%
- **适用场景**: 高吞吐场景，对精度有一定容忍度

### 4.3 各模型推荐量化格式

| 模型 | 推荐量化格式 | 显存节省 | 吞吐提升 |
|------|------------|----------|----------|
| DeepSeek-V3.1 | W4A8 | ~75% | 2-3x |
| DeepSeek-V3.2 | W8A8 | ~50% | 1.5-2x |
| Qwen3.5 系列 | W8A8C16 | ~50% | 1.5x |
| Kimi-K2.5 | W4A8C16 | ~70% | 2x |
| GLM-5.1 | W8A8C16 | ~50% | 1.5x |

### 4.4 量化选择建议

```
精度优先 → FP16/BF16
  |
  可接受 <1% 损失 → W8A16
    |
    可接受 1-3% 损失 → W8A8 (推荐生产部署)
      |
      可接受 3-5% 损失 → W4A8 (最大吞吐)
```

---

## 5. 数据来源说明

### 5.1 测试平台

所有性能数据均来自以下标准测试环境：

- **平台**: Atlas 800I A3-560T (HBM 128G)
- **NPU**: Ascend 910B4
- **显存**: 128 GB HBM / 卡
- **网络**: RoCE/RDMA 高速互联

### 5.2 测试方法

- **在线服务测试**: `vllm bench serve --dataset-name sharegpt --num-prompts 100`
- **离线吞吐量测试**: `vllm bench throughput --dataset-name random --input-len 128 --output-len 128`
- **测试工具**: vLLM 内置基准测试工具
- **备选工具**: AISBench（用于更复杂的评估场景）

### 5.3 配置文件来源

每条性能数据均对应 `model_configs/` 目录中的一个配置文件：

| 数据来源 | 配置文件 | 说明 |
|----------|----------|------|
| DeepSeek-V3.1.yaml | DeepSeek-V3.1 配置 | 低延迟/高吞吐/ v0.13.0 基线 |
| DeepSeek-V3.2.yaml | DeepSeek-V3.2 配置 | v0.13.0 高吞吐基线 |
| Qwen3-32B.yaml | Qwen3-32B 配置 | v0.13.0 高吞吐基线 |
| Qwen3-MoE-480B.yaml | Qwen3 MoE 480B 配置 | v0.13.0 多机基线 |
| Qwen3.5-397B.yaml | Qwen3.5-397B 配置 | 低延迟场景 |
| Qwen3.5-122B.yaml | Qwen3.5-122B 配置 | 低延迟场景 |
| Qwen3.5-27B.yaml | Qwen3.5-27B 配置 | 低延迟场景 |
| Kimi-K2.5.yaml | Kimi-K2.5 配置 | 高吞吐场景 |

---

## 6. 注意事项

### 6.1 数据适用性

> **实际性能受多种因素影响，建议以实测为准。**

性能基准数据是在特定环境下测试得到的参考值，实际部署中的性能可能因以下因素而异：

- **硬件差异**: NPU 批次、散热条件、网络拓扑
- **软件版本**: vLLM/vllm-ascend/CANN 版本差异
- **模型权重**: 量化模型的具体量化方案和校准数据
- **工作负载**: 输入/输出长度分布、并发模式、请求到达率
- **系统负载**: 其他进程占用、内存碎片、温度降频

### 6.2 性能对比建议

- 对比性能时，确保测试环境（硬件、软件版本、数据集）一致
- 使用相同的测试工具和参数（`num-prompts`、`dataset` 等）
- 建议测试多次取中位数，排除异常值
- 关注 P99 指标而非仅看平均值，评估尾延迟稳定性

### 6.3 数据更新

- 性能数据会随 vLLM-Ascend 版本更新而变化
- v0.13.0 及以后版本的数据标注版本号
- 新版本发布后会补充更新性能数据
- 旧版本数据保留用于版本对比

### 6.4 相关文档

| 文档 | 内容 | 用途 |
|------|------|------|
| [model_config_guide.md](model_config_guide.md) | 模型基准配置使用指南 | 配置文件结构和字段说明 |
| [model_matching_guide.md](model_matching_guide.md) | 模型匹配指南 | 无精确匹配时的回退策略 |
| [benchmark.md](benchmark.md) | 基准测试方法 | 测试工具使用和参数说明 |
| [speculative_decoding.md](speculative_decoding.md) | 投机解码配置 | 投机解码方法和配置 |
| [quantization.md](quantization.md) | 量化格式选择指南 | 量化方案详细说明 |
