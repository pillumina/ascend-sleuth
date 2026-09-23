本文件是 Tier 1 路由数据的**说明与入场判据**（人读面）；侧与性质两层本体在 triage-tree.d/*.yaml。
triage-tree.yaml 是生成物（scripts/build_triage_tree.py 拼出来），**不要直接编辑它**——
改侧或改词请改 triage-tree.d/ 下的对应文件，然后跑一次：
  python3 scripts/build_triage_tree.py
Tier 1: 症状 → namespace 路由

路由分两步，**侧与性质互不竞争**：

  侧（在哪一侧查）= training / inference —— **由工程师的事实确定，不由症状词判**：
    他贴的材料里写着（训练中 / 推理请求中 / 服务命令）→ 直接用；
    没写 → 在诊断第 1 步问一句（他一定知道）；
    他顺手给了框架名 → 按库里目录对（knowledge/training/<fw>/ 或 knowledge/inference/<fw>/）；
    他一时不答 → 侧未知：两侧都查，trace 标 side: unknown（保底，不阻塞诊断）；
    中途证据与他说法相反 → 以证据为准，回一句「你说训练、日志是 vllm serve，我按推理走」。
    规模在每侧内部的框架上扩张（新框架 = 该侧目录下加一层），侧本身不因新框架而增加。

  性质（什么性质）= interrupt / precision / performance —— **在侧内按症状判**：
    决定诊断路径 + quickly_check 形态 + 默认工具。三个性质各一份词表、**训推共用**：
    同一个宽词（`\btimeout\b`、`\bOOM\b`、`RuntimeError`）只写一次，不再出现
    「同一正则写在两个分支里、靠分支顺序决定谁先接住」。
    性质判不了 → 该侧三个性质的索引一起加载（优雅退化）。

组合出检索面：`knowledge/<侧>/<框架>/<性质>/`，外加框架无关的 `knowledge/common/`（必拉）。

<detected_framework>：工程师提供的框架（/diagnose 从客户提供的信息/报错判断，不跑 pip list）。
common/：跨框架/框架未登记的共性 case 落入此处（框架无关根因）。README + ADR-0005 的"common/ 必拉"
已从设计承诺变为可消费资产；search_namespaces 中的 common/ 一项已生效（框架检测失败或首个
namespace 未命中时查它）。条数与容量现算：`python3 scripts/index_counts.py`（生成物里不写数字——写进去就会在并发合并时撞行或漂移）；新共性 case 的提炼触发条件见
skills/knowledge-groom/SKILL.md。（本文件是 Tier 1 数据，不承载运行时状态播报。）

加词/改词/改分支的入场判据（判据本身见 scripts/trace_metrics.py 的 triage_miss_classes）：
  分支只承担两件事——**作用域路由**（侧 × 性质 → search_namespaces）与**常见措辞的省一步捷径**。
  它不承担语义覆盖：含义的模糊归 agent（级联第三级），形态的模糊归正则（设计原则三）。
  故只有三种证据支持改本文件：① 输入里有 token 类信号（错误码/算子名/env 名/文件名/版本）
  而没有任何分支接住；② 加载集合错了（命中的 case 不在被路由到的 namespace 里）；
  ③ 分支误吸（本该走 A 分支的症状被 B 分支抢走）。
  **「没见过这种写法」不是证据**——多语种与换词属语义面，补词不收敛（补的是措辞，不是能力）。
  分支里已有的中文症状词按「捷径」读：它们省一次语义判定，不作为完整性判据。

  性质词表**训推共用**，所以加词时多一条判据：**token 类的侧专属词可以进，措辞类的侧专属词不行**。
  token 类（`build_train_valid_test_data`、`recv_forward`、`tpot`、`accept_len` 这类函数名/字段名/
  配置名）只在那一侧的输入文本里出现，留在共用词表不会误吸别侧的 case；
  措辞类（`vllm serve`、`训练无法启动` 这类按某一侧的说法写的句式）会——另一侧的同性质 case
  会掉到别的性质或没命中，而**这种错不会报错**（占位都在、门全绿），只能靠人判断。
  拿不准是哪一类就标 `needs-review` 交人定。

sources:                       # 源文件清单（顺序 = 生成物里的拼接顺序，也是诊断时性质之间的匹配顺序）
  - file: 10-interrupt.yaml
    nature: interrupt
  - file: 20-precision.yaml
    nature: precision
  - file: 30-performance.yaml
    nature: performance

sides:                         # 侧层：合法侧、各自的目录面与检索顺序（侧的单一来源是工程师的事实）
  - id: training
    label: 训练
    namespaces:                # 按顺序搜索，最多加载 3 个
      - training/<detected_framework>/
      - common/
    fallback: Tier 3
  - id: inference
    label: 推理
    namespaces:
      - inference/<detected_framework>/
      - common/
    fallback: Tier 3
