# Diagnosis Procedure（核心循环的入口）

`/diagnose` 的 SKILL.md 写六步骨架；每一步的展开在 `steps/` 下，按步骤一个文件。本文件只做入口：**按当前走到哪一步打开那一份，不整组读**——快路需要步骤 1 / 2 / 3 / 4 / 6 五份，全路再加 5。

| 步骤 | 文件 | 何时读 |
|---|---|---|
| 1 收集症状 | [`steps/1-collect.md`](steps/1-collect.md) | 每次诊断（必读） |
| 2 路由与先验查询 | [`steps/2-route.md`](steps/2-route.md) | 每次诊断（必读） |
| 3 两阶段加载 case | [`steps/3-cases.md`](steps/3-cases.md) | 每次诊断（必读） |
| 4 验证 diagnosis checks | [`steps/4-verify.md`](steps/4-verify.md) | 候选加载后 |
| 5 深度排查 | [`steps/5-deep-dive.md`](steps/5-deep-dive.md) | 候选全部未命中时（必读）；命中后的判读缺口也可取流程 |
| 6 产出 | [`steps/6-deliver.md`](steps/6-deliver.md) | 要交付结论或收尾时（必读） |
| 误诊归因 | [`steps/attribution.md`](steps/attribution.md) | 回报 `not_resolved` / `partial` 时 |

每个文件开头有「何时读 / 完成判据 / 本步产出」三行；分支路径另有两个入口：紧急情况见 [`emergency.md`](emergency.md)，先验消费点与数据资产探询见 [`reference-gaps.md`](reference-gaps.md)。

旧引用里的「步骤 N」按上表对应到新文件；某节拆进多个文件时，以目标文件里的同名小节为准。
