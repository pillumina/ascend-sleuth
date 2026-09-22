本文件是 Tier 1 路由数据的**说明与入场判据**（人读面）；分支本体在 triage-tree.d/*.yaml。
triage-tree.yaml 是生成物（scripts/build_triage_tree.py 拼出来），**不要直接编辑它**——
加词 / 改分支请改 triage-tree.d/ 下对应那一族的文件，然后跑一次：
  python3 scripts/build_triage_tree.py
Tier 1: 症状 → namespace 路由

两个正交轴（别混）：
  轴 1（在哪查）= 训推 × 框架 → search_namespaces 指向的目录
  轴 2（什么性质）= category → 决定诊断路径 + quickly_check 形态 + 默认工具

<detected_framework>：工程师提供的框架（/diagnose 从客户提供的信息/报错判断，不跑 pip list）。
分支数 ≤ 30。框架检测失败时只用 common/。

common/：跨框架/框架未登记的共性 case 落入此处（框架无关根因）。README + ADR-0005 的"common/ 必拉"
已从设计承诺变为可消费资产；search_namespaces 中的 common/ 一项已生效（框架检测失败或首个
namespace 未命中时查它）。条数与容量现算：`python3 scripts/index_counts.py`（生成物里不写数字——写进去就会在并发合并时撞行或漂移）；新共性 case 的提炼触发条件见
skills/knowledge-groom/SKILL.md。（本文件是 Tier 1 数据，不承载运行时状态播报。）

加词/改分支的入场判据（判据本身见 scripts/trace_metrics.py 的 triage_miss_classes）：
  分支只承担两件事——**作用域路由**（症状 → search_namespaces）与**常见措辞的省一步捷径**。
  它不承担语义覆盖：含义的模糊归 agent（级联第三级），形态的模糊归正则（设计原则三）。
  故只有三种证据支持改本文件：① 输入里有 token 类信号（错误码/算子名/env 名/文件名/版本）
  而没有任何分支接住；② 加载集合错了（命中的 case 不在被路由到的 namespace 里）；
  ③ 分支误吸（本该走 A 分支的症状被 B 分支抢走）。
  **「没见过这种写法」不是证据**——多语种与换词属语义面，补词不收敛（补的是措辞，不是能力）。
  分支里已有的中文症状词按「捷径」读：它们省一次语义判定，不作为完整性判据。
