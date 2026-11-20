# Speculative Decoding Guide

Speculative decoding improves inter-token latency in memory-bound LLM inference by predicting tokens ahead of time.

## Method Selection by Model

```
+------------------+------------------+------------------+
| Model Series     | Method           | Config           |
+------------------+------------------+------------------+
| DeepSeek-V3.1    | mtp              | num_tokens: 3    |
| DeepSeek-V3.2    | deepseek_mtp     | num_tokens: 3    |
| Qwen3.5 series   | qwen3_5_mtp      | num_tokens: 3-5  |
| Kimi-K2.5        | eagle3           | num_tokens: 3    |
| GLM-5.1          | deepseek_mtp/mtp | num_tokens: 3    |
| LLaMA series     | eagle/ngram      | num_tokens: 2-5  |
+------------------+------------------+------------------+
```

## Model-Specific Configurations

### DeepSeek-V3.1

```bash
vllm serve /path/to/DeepSeek-V3.1-w4a8 \
  --speculative-config '{
    "num_speculative_tokens": 3,
    "method": "mtp",
    "disable_padded_drafter_batch": false
  }'
```

### DeepSeek-V3.2

```bash
vllm serve /path/to/DeepSeek-V3.2-W8A8 \
  --speculative-config '{
    "num_speculative_tokens": 3,
    "method": "deepseek_mtp"
  }'
```

### Qwen3.5 Series

```bash
# Low Latency: 5 tokens
vllm serve /path/to/Qwen3.5-397B \
  --speculative-config '{
    "method": "qwen3_5_mtp",
    "num_speculative_tokens": 5,
    "enforce_eager": true
  }'

# High Throughput: 3 tokens
vllm serve /path/to/Qwen3.5-122B \
  --speculative-config '{
    "method": "qwen3_5_mtp",
    "num_speculative_tokens": 3,
    "enforce_eager": true
  }'
```

### Kimi-K2.5 (EAGLE3)

```bash
vllm serve /path/to/kimi25_w4a8 \
  --speculative-config '{
    "method": "eagle3",
    "model": "/path/to/lightseekorg_kimi-k2.5-eagle3",
    "num_speculative_tokens": 3
  }'
```

### GLM-5.1

```bash
vllm serve /path/to/GLM-new-w8a8 \
  --speculative-config '{
    "num_speculative_tokens": 3,
    "method": "deepseek_mtp"
  }'
```

## 1. N-gram Speculative Decoding

Generate proposals by matching n-grams in the prompt.

```python
from vllm import LLM, SamplingParams

prompts = ["The future of AI is"]
sampling_params = SamplingParams(temperature=0.8, top_p=0.95)

llm = LLM(
    model="meta-llama/Meta-Llama-3.1-8B-Instruct",
    tensor_parallel_size=1,
    speculative_config={
        "method": "ngram",
        "num_speculative_tokens": 5,
        "prompt_lookup_max": 4,
    },
)
outputs = llm.generate(prompts, sampling_params)
```

## 2. EAGLE Speculative Decoding

Use EAGLE-based draft models for speculation.

```python
from vllm import LLM, SamplingParams

prompts = ["The future of AI is"]
sampling_params = SamplingParams(temperature=0.8, top_p=0.95)

llm = LLM(
    model="meta-llama/Meta-Llama-3.1-8B-Instruct",
    tensor_parallel_size=4,
    distributed_executor_backend="mp",
    enforce_eager=True,
    async_scheduling=True,
    speculative_config={
        "method": "eagle",
        "model": "yuhuili/EAGLE-LLaMA3.1-Instruct-8B",
        "draft_tensor_parallel_size": 1,
        "num_speculative_tokens": 2,
    },
)
outputs = llm.generate(prompts, sampling_params)
```

## EAGLE Configuration Notes

1. **Draft model**: Use EAGLE models from [HF repository](https://huggingface.co/yuhuili)
2. **Tensor parallelism**: EAGLE draft models need to run without tensor parallelism (`draft_tensor_parallel_size=1`)
3. **Async scheduling**: Enable with `async_scheduling=True` for better performance
4. **Eager mode**: EAGLE requires `enforce_eager=True`

## Token Count Selection

| Scenario | num_speculative_tokens | Reason |
|----------|------------------------|--------|
| Low Latency | 5 | Maximize acceptance rate |
| High Throughput | 3 | Balance overhead vs gain |
| Memory Bound | 3-5 | Best improvement |
| Compute Bound | 1-2 | Limited benefit |

## Configuration Options

| Option | Description | Typical Value |
|--------|-------------|---------------|
| `method` | Speculation method | See table above |
| `num_speculative_tokens` | Number of tokens to speculate | 2-5 |
| `prompt_lookup_max` | Max n-gram size (ngram only) | 4 |
| `model` | Draft model path (eagle only) | EAGLE model path |
| `draft_tensor_parallel_size` | TP size for draft model | 1 |
| `enforce_eager` | Force eager mode (Qwen3.5) | true |

## Performance Impact

| Model | Without Spec | With Spec | Speedup |
|-------|--------------|-----------|---------|
| DeepSeek-V3.1 | 20ms TPOT | 15ms | 1.3x |
| Qwen3.5-397B | 25ms TPOT | 18ms | 1.4x |
| Kimi-K2.5 | 40ms TPOT | 28ms | 1.4x |

## Performance Tips

- N-gram: Simple, no extra model needed, good for repetitive prompts
- EAGLE: Higher acceptance rate, requires draft model and eager mode
- MTP: Model-specific, best integration with DeepSeek/Qwen
- Best for memory-bound scenarios (small batch, long sequences)
- May not help for compute-bound scenarios
