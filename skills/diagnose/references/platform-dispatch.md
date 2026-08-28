# Platform Dispatch（case 的 platforms 字段分发机制）

平台差异是**字段级**，不是 case 级——大量共享规则加少量平台特定差异。一个 case 可有多组 `diagnosis`，按检测到的平台选分支。

> 本文档只描述 case schema 的 `platforms` 字段分发机制。平台背景知识文档（`knowledge/platforms/*.md`）已按 [ADR-0008](../../../docs/adr/0008-prior-knowledge-framework.md) 废弃（agent 生成、零外部源）；平台事实的承载位置是 reference 层（`references/platform-facts/`，经 to-reference 从真实来源沉淀）。reference 层有内容之前，**诊断上下文不注入任何平台先验**——每个 case 携带自己的平台证据（`platforms` 键控的 `diagnosis` 分支）。

## 示例：同一 case 的平台分支（构造演示，只演示结构；完整 canonical sample 见 `examples/sample-case.yaml`）

```yaml
diagnosis:
  - platforms: ["A5-950", "A3-910C"]     # 该分支适用于这两个平台
    steps:
      - command_template: "env | grep HCCL_BUFFSIZE"
        expected: ">= 4194304"

  - platforms: ["A2-910B"]               # 平台特定差异走独立分支
    steps:
      - command_template: "<该平台的等价检查>"
        expected: "..."
```

分支内的检查内容由该 case 自己的证据决定（来自 issue 验证 / 官方文档），**不预设"某平台一定有/没有某参数"**——那是 reference 层（`platform-fact`）的职责，且必须带来源。

## 检测当前平台

```bash
npu-smi info | grep -i '910\|950'    # 910B / 910C / 950
```

检测结果填入 case 的 `platforms` 匹配逻辑。无平台字段的 case 视为全平台通用。
