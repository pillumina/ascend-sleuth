# skill 改动评估（golden-case 回归套件）

> 改 KB 有指标反馈（confidence/命中率/误诊率）；改 skill 本身（流程措辞、步骤、输出格式）没有。
> 这套件是给 skill 改动补一个"改前/改后别回归"的检查——别把原来能查的查坏了。

## 机制

每条已解决的 Tier-2 命中 case = 一个测试夹具（见 `eval/golden/`）。改 skill 前/后各跑一遍 `/diagnose`（replay 模式：喂固定 input、不交互），对照 `expected`：

- 路由到对不对的 namespace？
- 匹配到对不对的 case？
- fix 包含期望值吗？

## 数据策略（关键）

| 用什么 | 为什么 |
|---|---|
| **骨干：真实数据（脱敏）** | 保真度——真实日志有噪声、措辞各异、信号混杂；构造数据太干净会 false confidence。**有意义的是输入真实**（真实日志片段/症状措辞），不是期望输出真实 |
| **补充：构造的边缘 case** | 覆盖真实数据没踩到的路径：优雅退化触发、框架歧义、precision vs interrupt 混淆、空库 |
| **公开仓：只构造** | 真实客户数据不能上公开仓（§部署公私分离）。公开仓的 eval/ 是格式示例，不是真正的回归防线 |

**真实 fixture 不用手工造**：它是已解决 postmortem 的投影（症状+日志片段+root cause+fix 都在 postmortem 里）。groom 半自动生成（v1.5）；脱敏复用 redact()。

## 怎么跑（v1 手动）

1. 改 skill **前**，跑一遍 `eval/golden/*.yaml`（喂 input 给 /diagnose），记录基线——哪些 pass
2. 改 skill
3. 改**后**再跑一遍，对照——**不能让原来 pass 的变 fail**（回归）
4. 把改前/改后报告附在变更摘要里交 owner 审

## 注意

- **LLM 非确定性**：同一 fixture 跑两次可能路由不同。跑 N 次取多数，或断言"top-3 命中"而非"必须第一"。
- **套件测的是固定输入下的路由+匹配+fix**，测不了交互质量（有没有问对问题）、测不了新 case 处理——那部分人工审。
- **小 N**：只能抓回归和大改动，抓不了微调的提升。

## v1.5 路线

- groom 从已解决 postmortem 自动生成 `eval/golden/` 真实 fixture（脱敏）
- `/skill-eval` 自动编排 replay + LLM-judge 比对 expected，产出改前/改后报告
