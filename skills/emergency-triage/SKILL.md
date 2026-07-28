---
name: emergency-triage
description: >
  昇腾生产中断时的紧急排查。跳过诊断流程，直接给风险标注的人类可读排查清单。
  不改配置、不记 postmortem——事后用 /skill:to-postmortem 补。
  当客户明确说"生产中断/紧急/先恢复服务"时用这个，而不是 /skill:diagnose。
disable-model-invocation: true
---

# Emergency Triage

生产挂了，没人想走 15-30 分钟的完整诊断流程。这个 skill 承认这一点：**先恢复，再分析**。

## 流程

1. **跳过**症状分类和 Tier 2 匹配（不改任何配置）
2. 加载 `CHEATSHEET.md` 的"紧急恢复"段（人工维护，挂在速查表顶部）
3. 输出人类可读排查清单，每项标注 `risk`：
   - `[safe]` 只读检查——查最近 24h 变更（配置/镜像/驱动）、`npu-smi`、`hccl top`、日志最后一段报错
   - `[caution]` 会中断服务——重启 HCCL daemon、回滚到上个 checkpoint、降配重试
4. **不记录 postmortem**——等事后手动跑 `/skill:to-postmortem`

## 终点

服务恢复。事后知识沉淀是**异步**的，不阻塞恢复——这和 `/to-postmortem` 的哲学一致。

## 紧急排查的典型路径（经验顺序）

```
1. 最近变了什么？  (config / image / driver / firmware / 数据)
2. 基础链路通不通？ (npu-smi 健康？hccl 拓扑？网络？)
3. 日志最后一段报什么？ (栈尾、第一个 ERROR)
4. 能不能降级恢复？ (关 EP、降 batch、回滚 checkpoint)
```

这条路径人凭经验走，但 CHEATSHEET 的"紧急恢复"段给它一个 agent 可读的速查格式。
