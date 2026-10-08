# dsh-plugins —— 面板共通约定

本目录下是 DSH 会话里加载的可视化面板（诊断 / 指标 / 自演进）。**每个面板的 README 讲它自己
的信息架构；本文件讲两个面板必须一致的约定**——色语、排版、文案。放着不统一的后果是实测过的：
同一界面里两个面板风格不同，读起来像两个产品。

一次改一个面板时也请读这里：这些约定是**跨面板契约**，改动要走两个面板一起改 + 回归闸门。

| 契约 | 权威实现 | 机械检查 |
|---|---|---|
| 颜色角色 | 每个 `panel-client.js` 的 `--c-*`（文字，需过 WCAG AA）/ `--acc-*`（装饰，两点面板逐色同值）/ `--fill-*`（实心徽标底）/ `--btn-*` | `python3 scripts/check_panel_tokens.py` |
| 字号与行高 | 8 档 `--t-md2 10.5` → `--t-2xl 18`（基准 `--t-base` 14.5）；行高 `--lh-tight/base/prose`（中文需 ≥1.6） | `node scripts/panel_render_check.js`（断言：声明 8 档、无硬编码 font-size、最小档 ≥10、基准档 ≥14、两面板同值域） |
| 结果复用窗口 | 每个 `panel-host.js` 的窗口常量（`VERDICT_TTL_MS` / `CACHE_TTL_MS`），client 的刷新说明照它写 | `node scripts/panel_render_check.js`（断言：窗口内复用不重跑脚本、`refresh: true` 绕过窗口、失败也能强制重跑、首屏那次不强制、两面板窗口同值且与 client 说明一致） |
| 面板文案 | 共用条目见 `docs/spec/writing-norms.md`（判定口径的权威）；面板特有的见下方「面板文案的定制条款」 | 同上（行文只有"无字面 Markdown 星号"一条可机械判） |
| 只读边界 | 面板是只读可视化 + 指令生成器；不做决策与写入 | 人审（`skills/preload-panel/SKILL.md`） |
| 依赖缺失时的退化 | 拿不到数据时给一行说明 + 可行的下一步，不占位、不拿别处的数据冒充 | `node scripts/panel_render_check.js`（退化路径一节，含 5 个缺件用例） |
| 面板包产物 | 面板源码（`dsh-plugins/<面板>/panel-host.js`、`panel-client.js`）是唯一真源，`dsh-plugins/dsh-sleuth-panels/lib/` 是生成物 | `node scripts/build_panel_bundle.js --check` |
| 面板包可加载性 | 常驻插件包适配层的 host 四样（`harness.handle` → prefix 路由、信封格式、`harness.defineTool` 的 parameters 归一化、`shell.run` → `execute` + `result()`）+ client 的 `host.call` 映射（渲染三个 tab 的首屏各验一条 RPC）+ 三处名字对齐（`package.json` / `cordis.patch.yml` / 产物 export） | `node scripts/check_panel_bundle.js` |
| 面板包外部契约 | 已安装 DSH 的五条接缝：`webServer.register(route)` 含 prefix、`connection.requestRejection`、client 沙箱的 `styles.insert`、页面产物格式 `__ModuleLoader__.load`、shell 的 `resolve` + `execute` | 同上（末段 DSH 探针；`--selftest-dsh` 自测） |

**结果复用窗口**（两个面板同一条约定）：面板取数要起 Python 子进程，而切走 tab 再切回会重新挂载
组件、重新发起同一条 RPC，所以结果按短窗口复用（切回不必等进程）。三条约束一起成立才算守住：
①窗口内复用不重跑脚本；②读者有显式出口——client 的刷新入口必须带 `refresh: true` 绕过窗口；
③**失败结果同样按窗口复用、但同样能被强制重跑**（把"体检不可用"缓存住又不给重试，读者只能干等过期）。
窗口数值只写在 host（机器落点），client 的说明与本节都以它为准；数值漂了由机械检查拦下。
复用不等于实时：界面上的时间戳照旧是脚本生成时刻，不会因为复用被刷成"现在"。

## 三条装载路（面板源码一份）

面板源码是动态插件方言的函数体，三条路读同一份，按本机 DSH 给模型哪些工具选：

| 路 | 适用 | 怎么装 | 生效范围 |
|---|---|---|---|
| 热加载 | DSH 有 `cordis_define` / `cordis_run` | 用 `dsh-plugins/loader/` 装出 `panel_from_file`，再发两个路径 | 本会话，随进程消失 |
| 常驻插件包 | DSH 没有这两件工具（新版把模型侧的动态定义入口删了），但有 `plugin_manager` | `plugin_manager install_bundle` 装 `dsh-plugins/dsh-sleuth-panels/` | 本 profile 每个会话，重启不丢 |
| 插件页安装 | 三件工具都没有（DSH Desktop 默认如此） | 在侧栏「插件」页粘贴 `dsh-plugins/dsh-sleuth-panels/` 的绝对路径 | 同上；装的是同一个包 |

第三条路换的是谁来调插件管理器：桌面版把它只接到界面上，模型侧没有这个工具。三条路装完
落在 profile 的状态相同（`dependencies` 与 `dsh.profile.bundles` 各一条、各一个 generation）。

常驻包的两个产物由 `node scripts/build_panel_bundle.js` 把面板源码原文嵌进适配层生成，
不要手改；源文件改了要重跑生成器。适配层补的是动态沙箱当年自带、常驻包没有的五样：

- `harness.handle` → 一条 **webServer 的 prefix 路由**（`/ascend-sleuth-panels`），信封与客户端的
  `connection.rpc.call` 对齐：`POST <channel>/<endpoint>`（body 是页面发的那份
  `{type:'client-request', rpcId, method, payload}`），应答 `{type:'server-response', rpcId, result}`，
  `result` 是 `{ok, value}` 或 `{ok:false, error}`（失败分支的 `error` 要带 `code`/`message`/`details`，
  客户端会逐个校验）。
  不用 `connection.rpc.handle`：它把 owner 绑到 connection 服务自己的 ctx，注册时读
  `owner.webServer` 就会抛（in-app 的 dsh-ppt 也把这一步包在 try/catch 里，真正干活的是它自己注册的路由）。
- `host.call` → 调同一个 channel；失败抛错（面板各处的 `.catch` 就是照这个写的）。
  它只在组件挂载时才发生，所以靠**渲染**来验：`check_panel_bundle.js` 用 mock React（effect 同步跑、
  `createElement` 递归调用函数组件）把三个 tab 的首屏各渲染一次，断言它们分别真的发出了
  `ascend-traces-list` / `ascend-metrics-verdict` / `ev-board-load`，且渲染期无异常；真机那一次
  仍归 `panel_rpc_probe.js`（同一条线协议）。
- `styles.insert` → 自建 style 标签（client 沙箱给每个包注入的那个）。
- `harness.defineTool` 的 `parameters` → dsh 自带的 `defineTool` 只认 DSL
  （`{ 字段: schema, required: true }`），动态沙箱则会把面板用的 JSON-Schema 包装
  （`type` / `properties` / `required`）归一化掉。漏了这一步会在面板自身的 try/catch 之外抛，
  整个 host 半挂不上、RPC 一个都不注册。
- `shell.run(spec)` → dsh 的 shell 服务只有 `execute(spec) → ShellExecution`（句柄），完成信息在
  `await execution.result()` 上（`ShellRunResult`：`exitCode` / `timedOut` / `aborted` / `stdout.text`）。
  面板源码用的是前者、并直接读 `exitCode` 与 `stdout.text`，两边形状不同；面板那段又把异常吞成
  「未找到可用的 Python 3 解释器」，所以在传给面板的 ctx 上补一层：真服务已有 `run` 就原样透传
  （旧 DSH 行为不变），没有就映射到 `execute` + `result()`。这条不补，指标与自演进两个 tab 的
  Python 取数会一律退化成"体检不可用"。

装载流程见 `skills/preload-panel/SKILL.md`。适配层依赖的是已安装 DSH 的五个外部契约，所以有了判据：

- `node scripts/check_panel_bundle.js` —— 判本机 DSH 走哪条装载路，并逐条核对那五个契约
  （`webServer` 的 prefix 路由声明、`connection.requestRejection`、client 沙箱的 `styles.insert`、
  页面产物格式 `__ModuleLoader__.load`、shell 的 `resolve` + `execute`）；找不到 DSH 时如实跳过。
  `--selftest-dsh` 用临时假 DSH 自测这条判据（含两条"去掉某个契约必报红"的用例）；
  `--dsh-root <目录>` 指到别的安装处。
- `node scripts/panel_rpc_probe.js` —— 不经 GUI，按页面的线协议打一条面板 RPC，直接看 host 半挂没挂、
  会话工作区解析得出、数据取到几条。退出码 2 = 路由没在服务**或未授权**（装了还没重启时就是前者）。
  它证明不了 React 那层的渲染，那一层只能看页面。

## 面板文案的定制条款

行文规范的**共用条目**与**必须保留的原值**（枚举、路径、命令、证据原值）写在
[`docs/spec/writing-norms.md`](../docs/spec/writing-norms.md)——那是唯一权威，本文件不复制。
**不复写条数**：那份文件的条目会被增补（实测从八条涨到二十二条），手写的数字只会腐烂。

面板额外要守的是下面四条，它们都由同一个事实决定：**面板的读者只看界面，不看正文。**

1. **内部标识符不上屏**：`state: ok`、`capability_readout`、枚举名 `metrics_compare` 都要换成中文名；
   正文里也不拿 `soft_cap`、`routed_accuracy` 当普通词用。
2. **命令与路径原样给出，其余一律中文**：`scripts/metrics_health.py`、`python3 scripts/...` 照抄，可复制即其价值。
3. **判据的标题与解释是数据**（`proposals/gates.yaml`、`metrics/gates.yaml`），改文案不必动代码；
   带数值的读数模板留在脚本里（格式化贴着维度定义）。
4. **文案改了要同步改钉它的断言**：`panel_render_check` 大量断言直接匹配文案，只改一边的后果是要么闸门红、
   要么断言悄悄失去意义（假绿）。实测一次措辞重写牵连 18 条断言。

专有名词用术语而非修辞：说"零否决记录""外部验证停滞""引用路径失效"，不说"从未说过不""自证过多"
"依据已消失"——后者读着顺口，但没法当判据名引用，也容易被读成价值判断。

**哪些规则能硬化**：见 `docs/spec/writing-norms.md` 的「哪些能硬化」一节。面板侧实测的结论是：全部条目里只有
"无字面 Markdown 星号"一条合格，其余留人审——不为"AI 味"造硬门（原则六）。
