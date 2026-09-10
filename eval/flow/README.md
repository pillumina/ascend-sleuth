# eval/flow/ —— 流程类先验知识的评测池

用途：评估「加载**哪条**流程 / 加载**多深**」对诊断结论的影响。
对应决策卡 [EV-2026-038](../../proposals/ideas/EV-2026-038.yaml)；实验结论见
`proposals/experiments/flow-form/SCORE.md`（第一轮：形态无关）与 `SCORE-2.md`（第二轮：加载深度决定性）。

与 `eval/s2/` 的区别：S2 的 ground truth 是 issue 的 resolution（PR 号），
本池的 ground truth 是**对应 KB case 的 root_cause**——因为要判的不是"找到哪个修复 PR"，
而是"有没有按方法定到正确的根因"。

## 池结构

每条样本 = **一个真实上游 issue 的首帖**（输入）+ **对应 case 的根因**（标准答案）：

```yaml
- id: FLOW-2026-001
  source_issue: 10524            # 上游 issue 号（可回溯）
  category: precision
  namespace: inference/vllm-ascend/precision/
  held_out_case: VLLM-ASC-10524  # 本轮检索必须排除的 case
  flow_relevant: <ref-id|null>   # 有对应流程 → 可测流程价值；null → 覆盖缺口
  leakage: clean
  input:
    symptoms: |                  # 上游首帖正文（不含标题）
    truncated: false
  expected:
    root_cause_summary: ...
    root_cause_keywords: [...]   # 打分用（不提供给被测 agent）
    leak_critical: [...]         # 泄露扫描用
    resolution: ...
```

## 构造纪律（三条，缺一不可）

1. **输入不含标题**。issue 标题经常直接写根因（如「X 把 K RMSNorm variance 错误计算为 0」），
   只取首帖正文。
2. **held_out_case 必须排除**。样本对应的 case 就在 `knowledge/` 里，不排除则直接命中，
   测不到方法价值。当前 diagnose 检索没有排除开关 → 回放时用"只给材料、不给 KB"的方式实现
   （同第一/二轮实验），长期指标需要的 `--exclude` 是**未落地的前置**。
3. **泄露扫描必须过**。口径：
   `leak_critical` = case `root_cause` 的决定性词 − case `symptoms` 里出现过的词。
   症状词是观察量（输入里出现正常）；隐藏机制词出现才是泄题。

## 校验与使用

```bash
python3 scripts/flow_pool.py --stats        # 池统计（category / 流程覆盖 / 泄露状态）
python3 scripts/flow_pool.py --leak-scan    # 泄露扫描（新增样本必跑；发现泄露非零退出）
python3 scripts/flow_pool.py --prepare      # 产回放输入 → .flow-replay/<id>.md
python3 scripts/flow_pool.py --prepare --with-flow   # 附上流程词条全文（对照臂）
```

## 当前池（2026-09-10）

13 条（precision 7 / performance 6），全部 `leakage: clean`。
其中 **7 条有对应流程**（4 条 MTP/投机、2 条乱码/权重、1 条通信瓶颈），
**6 条无流程覆盖**——这 6 条同时是流程层的**覆盖缺口信号**：

| 缺口样本 | 现象类别 |
|---|---|
| VLLM-ASC-5725 | embedding 二次请求向量不一致（prefix cache 路由） |
| VLLM-ASC-10524 | 图捕获 slot_mapping 未填充 |
| VLLM-ASC-10710 | prefix cache 命中率恒 0（混合压缩 KV） |
| VLLM-ASC-10876 | chunked prefill 偶发超长（triton kernel constexpr） |
| VLLM-ASC-10970 | MTP/hybrid KV 下 prefix hit rate 低 |
| VLLM-ASC-12030 | 流式 tool-call 字符重复（parser） |

## 待补

- **扩量**：本轮 24 个候选里 13 条通过泄露扫描；其余可用"裁剪泄露段落"或换上游源补。
- **held-out 检索开关**：长期指标（跟随后 resolve 率）需要 diagnose 支持排除指定 case。
- **跨框架**：目前只有 vllm-ascend；mindspeed / verl / msprof(COMMON-*) 类需另建源。
- **脱敏**：本池已对内网 IP（→ `<内网IP>`）与个人家目录（→ `/home/<user>`）做替换；
  `127.0.0.1` / `0.0.0.0` 保留（非敏感）。注意 `eval/s2/` 与 `eval/golden/` 现存文件未做此处理——
  属历史状态，不在本池范围内修。
