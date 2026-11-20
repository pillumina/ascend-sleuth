# Performance Benchmark Guide

Guide for benchmarking vLLM-Ascend performance.

## 1. vLLM Built-in Benchmark

### Offline Benchmark

```bash
# Throughput benchmark
python benchmarks/benchmark_throughput.py \
  --model Qwen/Qwen2.5-7B-Instruct \
  --backend vllm \
  --num-prompts 1000 \
  --input-len 128 \
  --output-len 128

# Latency benchmark
python benchmarks/benchmark_latency.py \
  --model Qwen/Qwen2.5-7B-Instruct \
  --input-len 128 \
  --output-len 128
```

### Online Benchmark (Serving)

```bash
# Start server
vllm serve Qwen/Qwen2.5-7B-Instruct --port 8000

# Benchmark with vllm bench serve
vllm bench serve \
  --model Qwen/Qwen2.5-7B-Instruct \
  --backend vllm \
  --endpoint /v1/completions \
  --num-prompts 1000 \
  --request-rate 10
```

## 2. Key Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| TTFT | Time to First Token | Lower is better |
| TPOT | Time Per Output Token | Lower is better |
| Throughput | Tokens/second | Higher is better |
| P99 Latency | 99th percentile latency | Lower is better |
| Success Rate | Request success rate | Should be 100% |

## 3. Benchmark Scenarios

### Scenario 1: Low Latency
```bash
# Small batch, short sequences
--num-prompts 100 --input-len 32 --output-len 32 --request-rate 1
```

### Scenario 2: High Throughput
```bash
# Large batch, moderate sequences
--num-prompts 1000 --input-len 512 --output-len 128 --request-rate 50
```

### Scenario 3: Long Context
```bash
# Long input sequences
--num-prompts 100 --input-len 4096 --output-len 256
```

## 4. Performance Baseline Recording

Before and after tuning, record:

```yaml
# benchmark_record.yaml
model: Qwen/Qwen2.5-7B-Instruct
hardware:
  npu: 8x Ascend 910B
  cpu: 128 cores
  memory: 512GB

config:
  tensor_parallel_size: 8
  max_model_len: 4096
  max_num_seqs: 256

metrics:
  ttft_ms: 45.2
  tpot_ms: 12.5
  throughput_tokens_per_sec: 12500
  p99_latency_ms: 120.5

environment:
  cann_version: 8.0.0
  vllm_version: 0.18.0
  torch_npu_version: 2.1.0
```

## 5. Common Benchmark Tools

```bash
# Using vllm-bench-serve skill for comprehensive benchmark
# See: vllm-bench-serve skill

# Custom benchmark script
python -c "
import time
import requests

start = time.time()
response = requests.post(
    'http://localhost:8000/v1/completions',
    json={'prompt': 'Hello', 'max_tokens': 100}
)
latency = time.time() - start
print(f'Latency: {latency*1000:.2f}ms')
"
```

## 6. Tuning Validation Workflow

```
1. Record baseline performance
2. Apply one optimization
3. Run benchmark
4. Compare with baseline
5. Keep or revert optimization
6. Repeat for next optimization
```

## Notes

- Warm up the model before benchmarking (graph compilation)
- Run multiple iterations and average results
- Monitor NPU utilization during benchmark
- Ensure consistent test conditions (no other workloads)
