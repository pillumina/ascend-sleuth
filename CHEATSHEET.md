# ascend-sleuth CHEATSHEET

> **路径 B 的主诊断入口**——无法跑 `/skill:diagnose`（网页版/手工）时查这个。
> 案例段由 `/skill:knowledge-groom` 自动重生成，按 `namespace × category` 分段。
> **紧急恢复**段人工维护，挂在顶部。
>
> 当前是模板——案例段为空，等真实 case 灌入后由 groom 填充。

---

## 🚨 紧急恢复（生产中断时先看这个）

1. **最近 24h 变了什么？** config / image / driver / firmware / 数据
2. **基础链路通不通？** `npu-smi info`、`hccl top`、网络
3. **日志最后一段报什么？** 栈尾、第一个 ERROR
4. **能不能降级恢复？** 关 EP / 降 batch / 回滚 checkpoint

| 动作 | risk |
|---|---|
| `npu-smi info` / `hccl top` / 查日志栈尾 | safe |
| 重启 HCCL daemon | caution（通信中断 ~30s） |
| 回滚到上个 checkpoint | caution（可能丢训练进度） |

---

<!-- 以下案例段由 /skill:knowledge-groom 按 knowledge/ 实际内容生成。 -->
<!-- 格式示例（真实数据灌入后替换）：                                  -->
<!--                                                                  -->
<!-- ## training/mindspeed-llm / interrupt                            -->
<!--                                                                  -->
<!-- ### EP Hang                                                       -->
<!--                                                                  -->
<!-- | 检查命令 | 期望值 | 修复方式 | 平台 |                           -->
<!-- |----------|--------|---------|------|                           -->
<!-- | `env \| grep HCCL_BUFFSIZE` | >= 4194304 | `export ...` | A5,A3 | -->
<!--                                                                  -->
<!-- 注意投影保真：平台条件分支不能压平成一行。                         -->
