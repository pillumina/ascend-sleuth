 # vLLM Parameters Reference

vLLM command-line parameters and Python API arguments for Ascend NPU deployment.

## Quick Navigation

- [Required Parameters](#required-parameters)
- [Performance Parameters](#performance-parameters)
- [Parallelism Parameters](#parallelism-parameters)
- [Quantization Parameters](#quantization-parameters)
- [Scheduling Parameters](#scheduling-parameters)
- [Additional Configuration](#additional-configuration)
- [Sampling Parameters](#sampling-parameters)
- [Tuning Strategy by Scenario](#tuning-strategy-by-scenario)

---

## Required Parameters

| Parameter | CLI | Python | Description |
|-----------|-----|--------|-------------|
| Model path | `--model /path/to/model` | `model="/path/to/model"` | Path to model weights |
| Host | `--host 0.0.0.0` | N/A | Server bind address |
| Port | `--port 8000` | N/A | Server port |

---

## Performance Parameters

### Memory and Batching

| Parameter | CLI | Python | Default | Description |
|-----------|-----|--------|---------|-------------|
| `max_model_len` | `--max-model-len 32768` | `max_model_len=32768` | Model default | Maximum sequence length |
| `max_num_seqs` | `--max-num-seqs 256` | `max_num_seqs=256` | 256 | Maximum concurrent sequences |
| `max_num_batched_tokens` | `--max-num-batched-tokens 4096` | `max_num_batched_tokens=4096` | Auto | Maximum batched tokens |
| `block_size` | `--block-size 128` | `block_size=128` | 16 | KV cache block size |
| `gpu_memory_utilization` | `--gpu-memory-utilization 0.9` | `gpu_memory_utilization=0.9` | 0.9 | GPU/NPU memory fraction |

### Parameter Details

| Parameter | Description | Tuning Guide |
|-----------|-------------|--------------|
| `max_model_len` | Max model sequence length | Set based on actual needs; larger = more memory |
| `max_num_seqs` | Max concurrent sequences | Increase for throughput, decrease for latency |
| `gpu_memory_utilization` | GPU memory utilization (0-1) | Default 0.9; lower to leave room for KV cache |

### Scenario Recommendations

| Scenario | max_model_len | max_num_seqs | max_num_batched_tokens |
|----------|--------------|--------------|------------------------|
| Standard | 32768 | 256 | 4096 |
| Long context | 65536 | 128 | 4096 |
| High throughput | 16384 | 512 | 8192 |
| Memory limited | 16384 | 128 | 2048 |
| Low latency | 4096 | 64 | 2048 |

### Memory-Related Examples

```bash
# Limit max sequence length to reduce memory
--max-model-len 4096

# Adjust memory utilization
--gpu-memory-utilization 0.85

# Enable prefix caching for repeated prompts
--enable-prefix-caching
```
---

## Parallelism Parameters

### Tensor Parallelism

| Parameter | CLI | Python | Description |
|-----------|-----|--------|-------------|
| `tensor_parallel_size` | `--tensor-parallel-size 2` | `tensor_parallel_size=2` | Number of NPU cards |
| `distributed_executor_backend` | `--distributed-executor-backend mp` | N/A | Backend: `mp` or `ray` |

### Pipeline Parallelism

| Parameter | CLI | Python | Description |
|-----------|-----|--------|-------------|
| `pipeline_parallel_size` | `--pipeline-parallel-size 2` | `pipeline_parallel_size=2` | For multi-node deployment |

### Backend Selection

| Backend | When to Use |
|---------|-------------|
| `mp` (multiprocessing) | TP <= 4, single node |
| `ray` | TP > 4, multi-node, advanced features |

### Parallelism Examples

```bash
# Single node, 8 cards
--tensor-parallel-size 8

# Multi-node (e.g., 2 nodes x 8 cards)
--tensor-parallel-size 8 --pipeline-parallel-size 2

# Model size recommendations
# <=14B: TP=1
# 14B-70B: TP=2-4
# >70B: TP=4-8
```

---

## Quantization Parameters

| Parameter | CLI | Python | Description |
|-----------|-----|--------|-------------|
| `quantization` | `--quantization ascend` | `quantization="ascend"` | Ascend quantization |

### Ascend Quantization Types

| Format | Description | Memory Reduction | Throughput Gain |
|--------|-------------|------------------|-----------------|
| **W8A8** | 8-bit weights, 8-bit activations | ~50% | 1.5-2x |
| **W4A8** | 4-bit weights, 8-bit activations | ~75% | 2-3x |
| **MXFP8** | MX floating point 8-bit | ~50% | 1.5x |
| **W8A16** | 8-bit weights, 16-bit activations | ~50% | Minimal loss |

### Quantization Usage

```bash
# For quantized models
vllm serve /path/to/quantized_model \
  --quantization ascend \
  --enable-expert-parallel  # For MoE models
```

---

## Scheduling Parameters

| Parameter | CLI | Python | Description |
|-----------|-----|--------|-------------|
| `async_scheduling` | `--async-scheduling` | `async_scheduling=True` | Enable async scheduling |
| `enable_prefix_caching` | `--enable-prefix-caching` | `enable_prefix_caching=True` | Cache prefixes |
| `no_enable_prefix_caching` | `--no-enable-prefix-caching` | `enable_prefix_caching=False` | Disable prefix caching |
| `enforce_eager` | `--enforce-eager` | `enforce_eager=True` | Disable graph mode |
| `no_enforce_eager` | `--no-enforce-eager` | `enforce_eager=False` | Enable graph mode |

### Scheduling Recommendations

| Scenario | async_scheduling | prefix_caching | enforce_eager |
|----------|-----------------|----------------|---------------|
| Standard | true | false | false |
| Repeated prompts | true | true | false |
| Debugging | true | false | true |

### Parameter Details

| Parameter | Description | Tuning Guide |
|-----------|-------------|--------------|
| `enable_prefix_caching` | Enable prefix caching | Enable for repeated prompt scenarios |
| `enforce_eager` | Force eager mode | Debug only; production should use graph mode |

---

## Additional Configuration

### --additional-config

JSON configuration for vLLM-Ascend specific advanced settings:

```bash
--additional-config '{"enable_cpu_binding":true}'
```

### Supported Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_cpu_binding` | bool | True | CPU binding for ARM+Ascend |
| `enable_shared_expert_dp` | bool | False | DP for shared experts (DeepSeek) |
| `multistream_overlap_shared_expert` | bool | False | Multi-stream for shared experts |
| `enable_async_exponential` | bool | False | Async exponential overlap |
| `enable_kv_nz` | bool | False | KV cache NZ layout (DeepSeek MLA) |
| `enable_npugraph_ex` | bool | False | Extended NPU graph support |
| `fuse_muls_add` | bool | False | Fuse mul and add operations |
| `recompute_scheduler_enable` | bool | False | Enable recompute scheduler |
| `layer_sharding` | list | [] | Layers to shard (e.g., ["q_b_proj", "o_proj"]) |

### DeepSeek Optimization Example

```bash
# Enable all DeepSeek optimizations
vllm serve deepseek-ai/DeepSeek-V3 \
  --additional-config='{
    "enable_shared_expert_dp": true,
    "multistream_overlap_shared_expert": true,
    "enable_kv_nz": true
  }'
```

---

## Sampling Parameters

For offline inference, use `SamplingParams`:

```python
from vllm import SamplingParams

# Low latency (less sampling overhead)
params = SamplingParams(
    max_tokens=128,
    temperature=0,  # Greedy
)

# High quality (more sampling overhead)
params = SamplingParams(
    max_tokens=256,
    temperature=0.8,
    top_p=0.95,
    top_k=50,
)

# Balanced
params = SamplingParams(
    max_tokens=512,
    temperature=0.7,
    top_p=0.9,
)
```

---

## Tuning Strategy by Scenario

### Low Latency (TTFT focus, TPOT ~20ms)

```bash
# Key adjustments
--max-num-seqs 64-96           # Reduce concurrent sequences
--max-num-batched-tokens 4000-6000
--enable-prefix-caching        # Enable for repeated prompts
--max-model-len 4096-8192      # Use smaller context

# Additional config
--additional-config '{"enable_cpu_binding": true}'
```

**Principles:**
- Reduce `max_num_seqs` to minimize queuing
- Enable prefix caching for repeated prompts
- Use smaller `max_model_len` to reduce memory pressure

### High Throughput (TPOT ~50ms acceptable)

```bash
# Key adjustments
--max-num-seqs 128-1000        # Increase concurrent sequences
--max-num-batched-tokens 9000-16384
--gpu-memory-utilization 0.9
--tensor-parallel-size 4-8     # Use tensor parallelism

# Additional config
--additional-config '{"enable_cpu_binding": true}'
```

**Principles:**
- Increase `max_num_seqs` for higher concurrency
- Increase `gpu_memory_utilization` to use more memory
- Use tensor parallelism for larger models

### Memory Constrained

```bash
# Key adjustments
--max-model-len 4096-8192      # Reduce context length
--max-num-seqs 64-128          # Reduce concurrent sequences
--gpu-memory-utilization 0.8   # Lower memory usage
--quantization ascend          # Use quantization
```

**Principles:**
- Reduce `max_model_len` significantly
- Reduce `max_num_seqs`
- Lower `gpu_memory_utilization`
- Use quantization to reduce memory footprint

### Long Context (> 64K tokens)

```bash
# Key adjustments
--max-model-len 131072-262144  # Very long context
--max-num-seqs 1-32            # Very few concurrent sequences
--max-num-batched-tokens 8192-16384
--gpu-memory-utilization 0.95  # Maximize memory usage
```

**Principles:**
- Maximize `max_model_len` as needed
- Minimize `max_num_seqs` to fit long sequences
- May require more NPU cards (higher TP)

---

## Quick Reference Table

| Scenario | max_model_len | max_num_seqs | max_batched_tokens | gpu_mem_util | Notes |
|----------|--------------|--------------|-------------------|--------------|-------|
| Low Latency | 4096-8192 | 64-96 | 4000-6000 | 0.9 | Minimize TPOT |
| High Throughput | 16384 | 256-1000 | 9000-16384 | 0.9 | Maximize TPS |
| Long Context | 65536-262144 | 1-32 | 4096-16384 | 0.95 | Memory intensive |
| Memory Limited | 4096-8192 | 64-128 | 2048-4096 | 0.8 | Use quantization |
| Standard | 32768 | 256 | 4096 | 0.9 | Balanced |
