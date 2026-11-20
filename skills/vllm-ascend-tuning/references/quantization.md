# Quantization Format Selection Guide

Quantization significantly reduces memory footprint and improves throughput with acceptable accuracy loss.

## Format Comparison

```
+----------+------------------+------------------+------------------+
| Format   | Suitable Models  | Memory Usage     | Performance      |
+----------+------------------+------------------+------------------+
| W4A8     | DeepSeek-V3.1    | Minimal          | Highest throughput|
| W8A8     | DeepSeek-V3.2    | Medium           | Balanced         |
| W4A8C16  | Qwen3.5 series   | Larger           | High accuracy    |
| W8A8C16  | GLM-5.1, Kimi    | Larger           | High accuracy    |
| W8A16    | General          | Baseline         | Minimal loss     |
+----------+------------------+------------------+------------------+
```

## Model-Format Mapping

### DeepSeek Series

| Model | Format | Quantization Tool | Notes |
|-------|--------|-------------------|-------|
| DeepSeek-V3.1 | W4A8 | msmodelslim | Per-channel quantization |
| DeepSeek-V3.2 | W8A8 | msmodelslim | Native support |

```bash
# DeepSeek-V3.1 W4A8
vllm serve /path/to/DeepSeek-V3.1-w4a8-perchannel \
  --quantization ascend \
  --enable-expert-parallel

# DeepSeek-V3.2 W8A8
vllm serve /path/to/DeepSeek-V3.2-W8A8 \
  --quantization ascend \
  --enable-expert-parallel
```

### Qwen3.5 Series

| Model | Format | Quantization Tool | Notes |
|-------|--------|-------------------|-------|
| Qwen3.5-397B | W4A8C16 | msmodelslim | MoE optimized |
| Qwen3.5-122B | W4A8C16 | msmodelslim | MoE optimized |
| Qwen3.5-27B | W8A8C16 | msmodelslim | Dense model |

```bash
# Qwen3.5-397B W4A8C16
vllm serve /path/to/Qwen3.5-397B-A17B-w8a8-org \
  --quantization ascend \
  --enable-expert-parallel
```

### GLM-5.1 / Kimi

| Model | Format | Quantization Tool | Notes |
|-------|--------|-------------------|-------|
| GLM-5.1 | W8A8C16 | msmodelslim | MoE model |
| Kimi-K2.5 | W4A8C16 | msmodelslim | MoE model |

```bash
# GLM-5.1 W8A8C16
vllm serve /path/to/GLM-new-w8a8 \
  --quantization ascend \
  --enable-expert-parallel
```

## Quantization Workflow

### Step 1: Prepare Calibration Data

```python
# calibration_data.json
[
  {"prompt": "Write a story about..."},
  {"prompt": "Explain quantum computing..."},
  # ... 128-512 samples recommended
]
```

### Step 2: Run msmodelslim

```bash
# W4A8 Quantization
msmodelslim --model /path/to/original_model \
  --output_path /path/to/quantized_model \
  --quant_config W4A8 \
  --calibration_data /path/to/calibration_data.json

# W8A8 Quantization
msmodelslim --model /path/to/original_model \
  --output_path /path/to/quantized_model \
  --quant_config W8A8 \
  --calibration_data /path/to/calibration_data.json
```

### Step 3: Verify Quantized Model

```bash
# Check quantization config
cat /path/to/quantized_model/quant_model_description.json

# Test inference
vllm serve /path/to/quantized_model \
  --quantization ascend \
  --max-model-len 4096
```

## Performance Impact

### Memory Reduction

| Original Size | W4A8 | W8A8 | W4A8C16 |
|--------------|------|------|---------|
| 397B | ~100GB | ~200GB | ~120GB |
| 122B | ~30GB | ~60GB | ~40GB |
| 27B | ~8GB | ~16GB | ~12GB |

### Throughput Improvement

| Format | Relative Throughput | Accuracy Loss |
|--------|--------------------|--------------|
| FP16/BF16 | 1.0x | Baseline |
| W8A16 | 1.1-1.3x | < 1% |
| W8A8 | 1.5-2.0x | 1-3% |
| W4A8 | 2.0-3.0x | 3-5% |

## Selection Guidelines

### When to use W4A8

```
[+] High throughput is priority
[+] Can tolerate 3-5% accuracy loss
[+] Memory constrained environment
[+] Batch inference workloads

Example: API serving with high QPS requirement
```

### When to use W8A8

```
[+] Balanced accuracy and performance
[+] 1-3% accuracy loss acceptable
[+] Production deployment
[+] Mixed workloads

Example: General-purpose chatbot
```

### When to use W8A16

```
[+] Accuracy is critical
[+] < 1% accuracy loss only
[+] Reasoning tasks
[+] Enterprise applications

Example: Financial/legal document analysis
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Quantization OOM | Calibration data too large | Reduce batch size |
| Accuracy degradation | Calibration data not representative | Use diverse samples |
| Model load error | Missing quant config | Re-run msmodelslim |
| Slow inference | Not using ascend quantization | Add --quantization ascend |

## References

- msmodelslim skill: `msmodelslim`
- Quantization tool: `/usr/local/Ascend/ascend-toolkit/latest/tools/msmodelslim`
- Supported models: Qwen, DeepSeek, GLM, LLaMA, InternLM
