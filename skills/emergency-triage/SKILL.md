---
name: emergency-triage
description: >
  昇腾生产中断时的紧急排查。跳过完整诊断流程，按经验顺序输出带风险标注的
  人类可读排查清单。不改配置、不记录 postmortem——事后用 /skill:to-postmortem 补。
  当客户明确说"生产中断/紧急/先恢复服务"时用这个，而不是 /skill:diagnose。
disable-model-invocation: true
---

# Emergency Triage

生产挂了，没人想走 15-30 分钟的完整诊断流程。这个 skill 承认这一点：**先恢复，再分析**。

## 流程

1. **跳过**症状分类和 Tier 2 匹配（不改任何配置）
2. 按下面的经验顺序输出排查清单，每项标注 `risk`
3. **不记录 postmortem**——等事后手动跑 `/skill:to-postmortem`

## 紧急排查的经验顺序

```
1. 最近 24h 变了什么？   config / image / driver / firmware / 数据
2. 基础链路通不通？     npu-smi info / hccl top / 网络
3. 日志最后一段报什么？  栈尾、第一个 ERROR
4. 能不能降级恢复？     关 EP / 降 batch / 回滚 checkpoint
```

紧急场景通常不是"某个 case 能匹配"——是"先查最近变更、再查基础链路、再查日志最后报错、最后看能否降级恢复"。这条路径人凭经验走，本 skill 把它固化成 agent 可读的清单。

## 风险标注

| 动作 | risk |
|---|---|
| `npu-smi info` / `hccl top` / 查日志栈尾 | safe |
| 重启 HCCL daemon | caution（通信中断 ~30s） |
| 回滚到上个 checkpoint | caution（可能丢训练进度） |
| 降配重试（关 EP / 降 batch） | caution（可能影响精度或吞吐） |

## 终点

服务恢复。事后知识沉淀是**异步**的，不阻塞恢复——这和 `/to-postmortem` 的哲学一致：定位完无论用什么方式查的，都去那里沉淀。
