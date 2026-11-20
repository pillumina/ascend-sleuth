 # Graph Mode Configuration Guide

Graph Mode compiles computation graphs for optimization, significantly improving inference performance.

## Overview

From v0.9.1rc1 with V1 Engine, vLLM Ascend runs models in graph mode by default.

Two graph modes are supported:
- **ACLGraph**: Default, well-tested for Qwen and DeepSeek series
- **XliteGraph**: OpenEuler Xlite graph mode, supports Llama, Qwen dense/MoE, Qwen3-VL

## Graph Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `FULL_DECODE_ONLY` | Full graph for decode only | Production (recommended) |
| `FULL` | Full graph for all stages | Maximum performance |
| `PIECEWISE` | Partial graph | Debugging |

## cudagraph_capture_sizes Configuration

The `cudagraph_capture_sizes` parameter defines which batch sizes get optimized graph compilation.

### Low Latency Configuration

```bash
# Small batch sizes for low latency
--compilation-config '{
  "cudagraph_mode": "FULL_DECODE_ONLY",
  "cudagraph_capture_sizes": [1, 6, 12, 18, 24, 30, 36, 42, 48, 54, 72, 78, 84, 90, 96, 102, 108, 144, 192]
}'
```

**Why:** Low latency scenarios have fewer concurrent requests, so smaller batch sizes are more frequently used.

### High Throughput Configuration

```bash
# Large batch sizes for high throughput
--compilation-config '{
  "cudagraph_mode": "FULL_DECODE_ONLY",
  "cudagraph_capture_sizes": [1, 4, 8, 12, 16, 24, 32, 48, 56, 64, 72, 84, 96, 108, 112, 128, 160, 172, 196, 200, 212, 232, 256, 272, 288, 312, 328, 344, 360, 384, 400, 416, 432, 448, 480, 512]
}'
```

**Why:** High throughput scenarios have many concurrent requests, requiring larger batch sizes.

### Fixed Batch Configuration

```bash
# Specific batch sizes only
--compilation-config '{
  "cudagraph_mode": "FULL_DECODE_ONLY",
  "cudagraph_capture_sizes": [4, 32, 64, 112, 128]
}'
```

**Why:** When you know the exact concurrency pattern, compile only those sizes to save startup time.

## Model-Specific Recommendations

### DeepSeek-V3 Series

```bash
# Low Latency
--compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY"}'

# High Throughput
--compilation-config '{
  "cudagraph_mode": "FULL_DECODE_ONLY",
  "cudagraph_capture_sizes": [4, 32, 64, 112, 128]
}'
```

### Qwen3.5 Series

```bash
# Low Latency
--compilation-config '{
  "cudagraph_mode": "FULL_DECODE_ONLY",
  "cudagraph_capture_sizes": [1, 6, 12, 18, 24, 30, 36, 42, 48, 54, 72, 78, 84, 90, 96, 102, 108, 144, 192]
}'

# High Throughput
--compilation-config '{
  "cudagraph_mode": "FULL_DECODE_ONLY",
  "cudagraph_capture_sizes": [1, 4, 8, 12, 16, 24, 32, 48, 56, 64, 72, 84, 96, 108, 112, 128, 160, 172, 196, 200, 212, 232, 256, 272, 288, 312, 328, 344, 360, 384, 400, 416, 432, 448, 480, 512]
}'
```

### Kimi-K2.5

```bash
# High Throughput
--compilation-config '{
  "cudagraph_mode": "FULL_DECODE_ONLY",
  "cudagraph_capture_sizes": [48, 64, 80, 96, 112, 128]
}'
```

## Using ACLGraph (Default)

ACLGraph is enabled by default with V1 Engine.

**Online example:**
```bash
vllm serve Qwen/Qwen2-7B-Instruct
```

**Offline example:**
```python
from vllm import LLM

model = LLM(model="path/to/Qwen2-7B-Instruct")
outputs = model.generate("Hello, how are you?")
```

## Using XliteGraph

```bash
pip install xlite
```

**Online example:**
```bash
vllm serve path/to/Qwen3-32B --tensor-parallel-size 8 \
  --additional-config='{"xlite_graph_config": {"enabled": true, "full_mode": true}}'
```

**XliteGraph config options:**
| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | False | Enable Xlite graph mode |
| `full_mode` | False | Enable for both prefill and decode stages |

## Choosing Capture Sizes Strategy

### Strategy 1: Cover Common Batch Sizes

```
Rule: Include sizes that cover 80% of your traffic

Example: If most requests have concurrency 20-100
  -> [1, 4, 8, 16, 24, 32, 48, 64, 80, 96, 112, 128]
```

### Strategy 2: Arithmetic Progression

```
Small batches: step = 6
  -> [1, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, ...]

Large batches: step = 16-32
  -> [128, 160, 192, 224, 256, 288, 320, ...]
```

### Strategy 3: Match max-num-seqs

```
If max-num-seqs = 128
  -> Include sizes up to 128

If max-num-seqs = 1000
  -> Include sizes up to 512-1000
```

## Performance Impact

| Configuration | Startup Time | Runtime Performance |
|--------------|--------------|---------------------|
| No capture sizes | Fast | Falls back to eager for uncompiled |
| Few sizes (5-10) | Medium | Good for specific patterns |
| Many sizes (30+) | Slow | Optimal for all batch sizes |

## Fallback to Eager Mode

If graph mode fails, fall back to eager mode:

**Online:**
```bash
vllm serve someother_model_weight --enforce-eager
```

**Offline:**
```python
from vllm import LLM

model = LLM(model="someother_model_weight", enforce_eager=True)
outputs = model.generate("Hello, how are you?")
```

## Limitations

- NPU soft partitioning + `CUDAGraphMode.PIECEWISE` is not supported
- Context parallel scenario with `cudagraph_mode=FULL` is not fully supported
- First run has compilation overhead, subsequent calls are faster
- Multi-modal models may need special graph capture configuration

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Long startup | Too many capture sizes | Reduce to essential sizes |
| Graph capture fails | Unsupported operator | Use --enforce-eager |
| Slow first request | Graph compilation | Normal, warmup before benchmark |
| Batch size not optimized | Size not in capture list | Add to cudagraph_capture_sizes |
| Memory OOM during capture | Large capture sizes | Reduce max capture size |

## Best Practices

1. Use graph mode for production (default)
2. Use eager mode for debugging only
3. Warm up the model after startup to compile graphs
4. Monitor first-request latency for compilation impact
5. Match capture sizes with actual concurrency patterns
