 # Parallel Strategy Selection Guide

Based on production performance testing on Atlas 800I A3-560T (HBM 128G).

## Quick Reference Table

```
+------------------+------------------+------------------+------------------+
| Scenario         | Model Size       | Strategy         | Config           |
+------------------+------------------+------------------+------------------+
| Low Latency(20ms)| Large (397B)     | DP1+TP16         | EP16+TP1(MoE)    |
| Low Latency(20ms)| Medium (122B)    | DP1+TP4          | EP4+TP1(MoE)     |
| Low Latency(20ms)| Small (27B)      | DP1+TP2          | -                |
| High Throughput  | Large (397B)     | DP1+TP16         | EP16+TP1(MoE)    |
| High Throughput  | Medium (122B)    | DP1+TP4          | EP4+TP1(MoE)     |
| High Throughput  | DeepSeek series  | DP4+TP4          | +Expert-Parallel |
| Max Length       | All models       | Max TP           | Minimize DP      |
+------------------+------------------+------------------+------------------+
```

## Key Principles

### Low Latency Scenario (TTFT < 1s, TPOT ~20ms)

```
[PRIORITY] Minimize latency per request

1. Maximize TP (Tensor Parallelism)
   - Reduces communication overhead per layer
   - Lower TPOT due to parallel computation

2. Minimize DP (Data Parallelism)
   - DP1 or DP2 preferred
   - Avoid request queuing across DP groups

3. Enable Speculative Decoding
   - MTP/EAGLE for token prediction
   - num_speculative_tokens = 3-5

Example:
--data-parallel-size 2
--tensor-parallel-size 8
--speculative-config '{"num_speculative_tokens": 3, "method":"mtp"}'
```

### High Throughput Scenario (TPOT ~50ms acceptable)

```
[PRIORITY] Maximize tokens per second

1. Balance DP/TP
   - DP4+TP4 for 8-card setup
   - Allows higher concurrent requests

2. Increase batch size
   - max-num-seqs = 128-1000
   - max-num-batched-tokens = 9000-16384

3. Relax TPOT constraint
   - Target TPOT = 50ms (vs 20ms for low latency)

Example:
--data-parallel-size 4
--tensor-parallel-size 4
--max-num-seqs 128
--max-num-batched-tokens 16384
```

### MoE Model Strategy

```
[REQUIRED] Enable Expert Parallel for all MoE models

--enable-expert-parallel

MoE Parallel Strategy:
- EP (Expert Parallel) size = Total cards
- Example: 16 cards -> EP16+TP1 for MoE layers
- MLA layers use standard TP

DeepSeek-V3 Example:
  MLA: DP2+TP8
  MoE: EP8+TP1 (with enable-expert-parallel)

Qwen3.5-397B Example:
  MLA: DP1+TP16
  MoE: EP16+TP1
```

## Model-Specific Recommendations

### DeepSeek-V3 Series

| Model | Cards | MLA Strategy | MoE Strategy | Notes |
|-------|-------|--------------|--------------|-------|
| DeepSeek-V3.1 | 8 | DP2+TP8 | EP8+TP1 | Low latency |
| DeepSeek-V3.1 | 8 | DP4+TP4 | EP8+TP1 | High throughput |
| DeepSeek-V3.2 | 8 | DP2+TP8 | EP8+TP1 | W8A8 format |

### Qwen3.5 Series

| Model | Cards | MLA Strategy | MoE Strategy | Notes |
|-------|-------|--------------|--------------|-------|
| Qwen3.5-397B | 16 | DP1+TP16 | EP16+TP1 | Max length 1M |
| Qwen3.5-122B | 4 | DP1+TP4 | EP4+TP1 | Single node |
| Qwen3.5-27B | 2 | DP1+TP2 | - | Dense model |

### GLM-5.1 / Kimi-K2.5

| Model | Cards | Strategy | Notes |
|-------|-------|----------|-------|
| GLM-5.1 (PD) | 32 | P:DP4+TP8, D:DP32+TP1 | PD separation |
| Kimi-K2.5 | 16 | DP4+TP4, EP16+TP1 | High throughput |

## Calculation Formula

```
Total Cards = DP x TP

For MoE models:
  Total Cards = DP x TP (MLA) = EP (MoE)

Example: 16 cards
  - Pure TP: DP1+TP16
  - Balanced: DP4+TP4
  - MoE: DP1+TP16 (MLA) + EP16+TP1 (MoE)
```

## Common Mistakes

```
[!] DON'T: Use high DP for low latency
  - DP8+TP1 -> High queuing latency
  - FIX: Use DP2+TP4 or DP1+TP8

[!] DON'T: Ignore Expert Parallel for MoE
  - MoE without EP -> Poor performance
  - FIX: Always add --enable-expert-parallel

[!] DON'T: Set TP > card count
  - TP16 on 8 cards -> Error
  - FIX: TP <= total cards

[!] DON'T: Mismatch DP x TP != total cards
  - DP3+TP3 on 8 cards -> 1 card unused
  - FIX: DP2+TP4 or DP4+TP2
```
