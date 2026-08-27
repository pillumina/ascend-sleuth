# Platform Dispatch（A2 / A3 / A5 字段级差异）

平台差异是**字段级**，不是 case 级——大量共享规则加少量平台特定差异。一个 case 可有多组 `diagnosis`，按检测到的平台选分支。

agent 在加载 Tier 2 候选时，同时加载匹配平台的 `knowledge/platforms/<platform>.md`，自动选对应 `diagnosis` 分支。

## 示例：HCCL 行为的平台差异

```yaml
diagnosis:
  - platforms: ["A5-950", "A3-910C"]
    steps:
      - command_template: "env | grep HCCL_BUFFSIZE"
        expected: ">= 4194304"
        fix_on_mismatch: "export HCCL_BUFFSIZE=4194304"
        rollback: "unset HCCL_BUFFSIZE"

  - platforms: ["A2-910B"]
    steps:
      - command_template: "cat /proc/driver/npu/version"
        expected: ">= 23.0"
        note: "A2 上不存在 HCCL_BUFFSIZE 参数。检查 NPU 驱动版本"
```

## 平台速记（详见各 platforms/*.md）

> ⚠️ **以下三条均标记 `[unverified]`**——`knowledge/platforms/{a2,a3,a5}.md` 没有引用任何外部源（白皮书 / 官方手册 / issue 验证），全部为作者声明。agent 在诊断输出中引用这些事实时，**必须保留 unverified 标记或改写为假设**，不允许以中性陈述方式复述。验证通道（ADR-0007）是 open work item。

| 平台 | 芯片 | 关键差异 |
|---|---|---|
| A2 | 910B | `[unverified]` HCCL 行为与 A3/A5 完全不同；无 `HCCL_BUFFSIZE`；FP8 不支持 |
| A3 | 910C | `[unverified]` HCCL 与 A5 近似；BF16 主力 |
| A5 | 950 | `[unverified]` FP8 精度问题只在 A5 出现；大规模 EP 通信瓶颈 |

## 检测当前平台

```bash
npu-smi info | grep -i '910\|950'    # 910B / 910C / 950
```

检测结果填入 case 的 `platforms` 匹配逻辑。无平台字段的 case 视为全平台通用。
