---
name: preload-panel
description: >
  在 DSH 会话中加载 ascend-sleuth 面板，并处理「装了但 tab 不出现」。先按本机给模型的工具与桌面版
  自带的东西选装载路：有 cordis_define / cordis_run 在会话内热加载；有 plugin_manager 就装常驻插件
  包；DSH Desktop 用安装目录自带的 dsh 命令行把 dsh-plugins/dsh-sleuth-panels/ 装进 profile（拿不到
  地址与 token 时这是主路）；另有 scripts/panel_install.js --all 经 /api 通路一次装面板与 vllm-kb
  两个包、以及在侧栏「插件」页粘贴路径两条备用路。常驻包里的界面是三块：会话里一个「诊断」tab、
  左侧栏一个「Ascend Sleuth」整页（指标 / 自演进）、侧栏页脚一个「诊断记录」入口（列出诊断会话，
  可按时间或按价值排序，点一行切过去）；热加载路径没有整页容器与页脚入口，仍是三个 tab（诊断 / 指标 / 自演进）。
  仅 DSH 可用
  ——依赖 conversation.view / main / sidebar.panellist / sidebar.footer.action / shell.overlay 插槽；
  其他 agent（Claude Code / Codex / pi）无此机制。
---

# Preload Panel

DSH 会话中加载可视化面板。常驻包把界面分成两块：会话里一个「诊断」tab（`conversation.view`，读这一单），
全库读数在整页「Ascend Sleuth」（`main` 的 keyed 条目 + `sidebar.panellist` 图标，指标 / 自演进两个子页）。
热加载路径没有整页容器，退回三个 `conversation.view` tab。

面板代码只有一份：`dsh-plugins/<面板>/panel-host.js` 与 `panel-client.js`（动态插件方言的函数体）。
装法有五条，先按「第 0 步」判本机走哪条。除热加载外，装完都要**重启宿主进程**：host 半的接口路由
在进程启动时装载，刷新页面只换浏览器那一半。

## 第 0 步：判本机走哪条路

先看会话里有哪几件工具，再看本机有没有安装目录自带的命令行。

| 本机条件 | 走哪条 |
|---|---|
| 有 `cordis_define` / `cordis_run` | 路由一：热加载（只在本会话生效） |
| 没有上面两件、但有 `plugin_manager` | 路由二：常驻插件包 |
| 两件都没有（DSH Desktop 默认），且有 `<安装目录>/resources/runtime/cli/bin/dsh[.cmd]` | 路由三：桌面版自带的命令行 |
| 命令行不在，或要装进别的 profile，或用户能操作界面 | 路由五：侧栏「插件」页粘贴路径 |
| 要在装之前确认包能加载，或界面不可用 | 路由四：HTTP 脚本安装（先要有地址与 token） |

**默认装两个包**：面板包 `dsh-sleuth-panels`，以及 `dsh-sleuth-vllm-kb`（设置页左侧栏的
「vllm-kb」一栏，四个 `vllm_kb_*` 工具默认关）。路由四用 `--all` 一次装齐；路由三对 vllm-kb 再跑
一次 `add`；路由二用 `install_bundle` 装两次；路由五在插件页粘贴两次。
两个包分开登记：装面板不会带上 vllm-kb。

桌面版多半落在第三行，原因有两条：发行版把插件管理器那条模型工具标成 `disabled: true`
（`@deepseek-ai/dsh-base/cordis.patch.yml`、`@deepseek-ai/dsh-web-app/cordis.patch.yml` 各一处），
模型侧没有 `plugin_manager`；较新的版本又从模型侧撤掉了 `cordis_define` / `cordis_run`。
界面「插件」页调的是同一个插件管理器服务，模型够不着；桌面版在安装目录里带了一条 `dsh` 命令行，
它的 `plugin` 子命令对桌面 profile 开放（见路由三）。

## 路由一：热加载（会话里有 `cordis_define` / `cordis_run`）

1. **确保 `panel_from_file` 工具可用**：先查它在不在（它按进程全局注册，通常已在；
   DSH 重启后第一次才缺）。缺则装 loader：
   1. `read dsh-plugins/loader/panel-from-file.js`（全文）
   2. `cordis_define`：kind: new，idPrefix `ldr`，`code.host` ← 刚读到的全文
   3. `cordis_run`（mode: run）——host-only 包，免审批

   loader 只用 `harness.registerTool` 与 `ctx.get('dynamicCordisRunner')` 两个公开机制。
   若本机 `cordis_define` 的参数表里有 `codeFile`，可省掉第 1 步，直接用它指向该文件。

2. **加载面板**：调 `panel_from_file`（不要用 `cordis_define` 转写源码）：

   ```
   panel_from_file(
     host:   dsh-plugins/<面板>/panel-host.js,
     client: dsh-plugins/<面板>/panel-client.js,
     idPrefix: ascend-panel 用 sleu / ev-panel 用 evbd,
     name, purpose)
   ```

   它读盘 → `dynamicCordisRunner.define()` → `run()`，源码原样进不可变 Package。
   返回 awaiting-approval 时告知用户在 UI 允许（Client 半需授权）；授权后 tab 出现。
   两个文件合计约 84 KB（ev-panel）与 265 KB（ascend-panel），发路径即可，别把全文重新输出一遍。

3. **验证**：确认插件 running 且无 waitingFor；对话视图出现对应 tab（热加载路径没有整页「Ascend Sleuth」，
   按「面板清单」热加载那两行的 id 核对）。自演进看板首次打开会调 `scripts/ev_board_data.py` 汇总数据，
   确认数据区渲染。
改完面板代码再调一次同一条 `panel_from_file` 即重载（同 `idPrefix` 复用本会话的插件，
返回 `reused: true`，不会堆出重复 tab）。

## 路由二：常驻插件包（会话里有 `plugin_manager`）

1. **确认包与产物存在**：`dsh-plugins/dsh-sleuth-panels/`，含 `package.json`、`cordis.patch.yml`、
   `lib/index.js`、`lib/client.js`。两个 `lib/` 文件是生成物：面板源码改了就跑
   `node scripts/build_panel_bundle.js`，用 `node scripts/build_panel_bundle.js --check` 核对产物与
   源文件一致，`node scripts/check_panel_bundle.js` 做一次可加载性冒烟（路由、端点、工具、一个 tab +
   整页 + 侧栏图标三个注册面、样式标签、卸载），并核对三处名字对齐（`package.json` / `cordis.patch.yml` / 产物 export）。
   **不要手改 `lib/`**。同一条命令还会判本机 DSH 走哪条装载路，并核对常驻包依赖的五个外部契约
   （`webServer` 的 prefix 路由声明、`connection.requestRejection`、client 沙箱的 `styles.insert`、
   页面产物格式 `__ModuleLoader__.load`、shell 的 `resolve` + `execute`）还在不在——**装之前跑它**。
   找不到 DSH 时这一项按本地桩校验工具定义（桌面版把 DSH 装在 `app.asar` 内，探针到不了）。
   `--selftest-dsh` 用临时假 DSH 自测这条判据，`--dsh-root <目录>` 指到别的安装处。

2. **装**：`plugin_manager install_bundle(target: <仓库绝对路径>/dsh-plugins/dsh-sleuth-panels)`；
   对 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb` 再装一次。

3. **读安装结果**（`application` 与 `warnings` 决定是否已生效，不要拿日志或进程列表代替）：
   - `applied` → 已生效。
   - `restart-required` → 运行时把先前的模块路径钉住了，要重启 DSH Desktop 才加载新版本；
     替换已装包时通常是这个。
   - `failed` → 读诊断；`webServer` 一类的报错说明路由没注册成功。

4. **验证**：先跑 `node scripts/panel_rpc_probe.js`（退出码 2 = 拿不到地址，或路由没在服务／未授权）；
   再用 `cordis_inspect_query`（client, `Slots`, `listSubTree`, root 下三处）看注册是否在占位列表里：
   `conversation.view` 的 `ascend-diagnose`、`main` 的 key `ascend-sleuth-console`、`sidebar.panellist` 的同一个 id。
   插槽占位与 RPC 都通了也不等于看着对，最后请用户点开一页确认渲染。

5. **卸载**：`plugin_manager remove_bundle(target: 'dsh-sleuth-panels')`。

## 路由三：桌面版自带的命令行（DSH Desktop 的主路）

桌面版不在 PATH 上装 `dsh`，但安装目录里带了一份：

- Windows：`%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd`
- macOS：应用包内 `Resources/runtime/cli/bin/dsh`

它支持 `plugin` 子命令，桌面 profile 对它开放（见第 3 条）。

1. **装**：

   ```
   dsh.cmd plugin --profile desktop add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-panels"
   dsh.cmd plugin --profile desktop add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
   ```

   两条都要跑：第一条装面板，第二条装 vllm-kb（设置页左侧栏那一栏）。
   命令做三件事：在 profile 目录跑包管理器、把依赖写成 `link:<仓库路径>`、把包名加进
   `dsh.profile.bundles`。最后一项决定启动时加载它——只写了依赖没进 bundles，等于没装。
   输出里的 `Already up to date` 只说明包管理器没搬文件，装没装看下一行的 `dependencies:`。

2. **读结果**：profile 的 `package.json` 两处都在才算登记完成——`dependencies` 里一条
   `dsh-sleuth-panels: link:<仓库路径>`，`dsh.profile.bundles` 里一项 `dsh-sleuth-panels`。
   界面「插件」页显示已安装不能当证据：它读的是登记，不是加载结果。

3. **profile 受保护的部分**：桌面 profile 的 `--dump-config` 会被拒，报
   `error: profile "desktop" is managed exclusively by the Electron application`；`plugin` 子命令
   允许。要看配置能不能拼出来，用「无 token 时的验证」里的临时副本。

4. **重启 DSH Desktop**（完全退出进程，关窗口不算）。

5. **验证**：先读「装上了但 tab 不出现」，再按「无 token 时的验证」跑一遍。

## 路由四：HTTP 脚本安装（要有地址与 token）

1. **装**：`node scripts/panel_install.js --all`。两个包各自判版本：与仓库一致就跳过，不一致才换装
   （换装后要重启，见「更新已装的面板」）；只想装其中一个时用 `--spec <包目录>`。
2. **核对**：`node scripts/panel_install.js --all --check`，两个包的版本号都应与仓库里的一致。

`node scripts/panel_install.js` 走的是界面同一条通路：先 `GET <base>/?token=<token>` 换会话 cookie，
再 `POST <base>/api/pluginManager/<方法>`，信封是
`{type:'client-request', rpcId, method:'pluginManager/<方法>', payload:{args:{…}}}`。先 `inspect`
（spec 传字符串）：认了且没装就调 `installBundle(spec, {enabled:true})`；回 `already-installed`
（这条 refused 不带包名）就从本地 `package.json` 读包名再调 `setBundleEnabled(name, true)`，spec 不是
本地路径时读不到包名，脚本以退出码 1 收场。

- `--check` 只查状态，只对能定到包名的目标给判断（定不到包名或目标没装都退 1）。
- `--remove` 卸载；`--spec <spec>` 换目标（包名、Git 地址、tarball 或本地绝对路径）；
  `--all` 处理面板包与 vllm-kb 接入插件两个包；`--force` 跳过版本判断强制换装。
- 地址与 token 的取法同 `panel_rpc_probe.js`：先扫日志里的 `dsh web: …/?token=…` 行，取不到再传
  `--url` / `--token` / `--log`。
- 退出码：0 = 操作完成（`application` 可能是 `restart-required`，要重启才加载新版本）｜2 = 拿不到
  地址与 token，或地址取到了但连不上，或 `/api` 没有认领端点、未授权｜1 = 其他失败。

**桌面版上这条路多半不通**：宿主把 `dsh web:` 那一行写进自己接管的管道，磁盘上找不到（`--no-open`
只跳过开浏览器，那一行照常打印）；Windows 的日志目录
`%APPDATA%\@deepseek-ai\dsh-desktop\logs` 是空的；token 由宿主经进程间通道交给界面，不落文件。
拿不到就改用路由三或路由五，不要反复试。

## 路由五：插件页粘贴（命令行不可用，或用户能操作界面时）

1. 让用户在侧栏「插件」页的添加入口粘贴 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-panels`，
   再用同一条路径把 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb` 粘一次。
   该入口接受包名、Git 地址、压缩包或本地绝对路径。粘的是这个包目录，不是面板源目录
   `dsh-plugins/ascend-panel/`——后者没有 `package.json`，入口会拒。
2. **读结果**：界面不给模型可读的 `application` / `warnings`，改读 profile 的 `package.json`
   （`dependencies` 与 `dsh.profile.bundles` 两处都要有），以及界面自己报的成功或失败。
   带快照机制的发行版会在 `package.json` 里多一个 `dsh.desktop.generationProjection` 字段，并在
   `dirname($DSH_PROFILE_DIR)/.generations/live/` 下放一份包快照；没有这两个东西的发行版，装完就是
   前两处记录。按机器上实际有的那套读，别按另一套找。
3. **验证**：先跑 `node scripts/panel_rpc_probe.js`（退出码 2 = 拿不到地址，或路由没在服务／未授权）；
   再让用户刷新页面，浏览器代码在页面启动时装载。
4. **卸载**：在插件页里移除该包。

## 装上了但 tab 不出现

按这个顺序查，一步一个证据。

1. **看宿主启动输出**：装完第一次启动时，stderr 会打出没加载成的插件行，形如
   `1 entry did not activate` 与 `failed to import: …`。有这两行，问题在包，不在界面。
2. **包静态 import 了 `@deepseek-ai/*`**。装进 profile 的包按自己的真实路径解析模块，到不了安装处的
   `node_modules`；这个发行版的 `resources/` 下没有模块回退文件。报错原文是
   `Cannot find package '@deepseek-ai/dsh-tools'`。表现是：插件页显示已安装、tab 一个都没有、
   面板接口回 405。修法在包这一侧，不在 profile：把那句 import 改成能解析到就用、解析不到用包内的
   最小实现（`dsh-plugins/dsh-sleuth-panels` 现在这么做），再重建产物、重启。
3. **host 半挂没挂的旁证**：会话工具列表里有 `ascend_trace_status`（由 host 半注册）。没有它，
   host 半没起来，先查第 1、2 步。
4. **只有浏览器那一半没换**：tab 在、版本串是旧的 → 刷新页面；仍旧就关浏览器缓存
   （DevTools 勾 Disable cache）。
5. **接口 401 或 405**：405 = 路由没注册（host 半没加载）；401 = 请求没带会话 cookie，
   用带 token 的地址进过一次页面即可。

## 无 token 时的验证（桌面版）

桌面版不打印 `dsh web:` 行，磁盘上也没有 token，`panel_install.js` 与 `panel_rpc_probe.js` 都取不到
地址。要验证就临时起一个自己的实例，验证完停掉。

**看配置能不能拼出来**

1. 复制一份 profile 到临时名字：`package.json`、`cordis.patch.yml`、`cordis.yml`、
   `pnpm-workspace.yaml`，把 `package.json` 的 `name` 改成临时名。
2. 给它一个 `node_modules` 目录联接，指回原 profile：
   `cmd /c mklink /J <临时>\node_modules <原 profile>\node_modules`。少了这一步，包解析不到。
3. `dsh --profile <临时名> --dump-config`：输出里应有 `# == dsh-sleuth-panels` 一段，退出码 0。
4. 删临时 profile：先 `cmd /c rmdir <临时>\node_modules` 断开联接，再删目录。直接递归删会跟着
   联接进原 profile。

**看 host 半真挂没挂**

1. `dsh --profile <临时名> --no-open --host 127.0.0.1 --port 0`。它会自己打印
   `dsh web: http://127.0.0.1:<端口>/?token=<token>`——新建的进程自己打印，磁盘上没有第二份这样的
   凭据。
2. 用这个地址换会话 cookie：`GET <base>/?token=<token>`，带 `redirect: manual`，取 `set-cookie`。
3. 打开 `GET <base>/`：页面加载清单里应有 `<包名>/client.js`，说明浏览器端会被加载。
4. `POST <base>/ascend-sleuth-panels/ascend-traces-list`，body 是
   `{"type":"client-request","rpcId":"…","method":"ascend-traces-list","payload":{}}`，带上第 2 步的
   cookie：回 `{"type":"server-response","result":{"ok":true,…}}` 说明 host 半与取数路径都通。
5. 停掉进程、删临时 profile。这是验证实例，不是用户界面：它占一个端口，别留在后台。

## 更新已装的面板

先判装法，两种的更新动作不同。拉完代码先跑 `node scripts/panel_install.js --sync`：两个包各自判
版本，一致就什么都不做，不一致就换装并说明要不要重启。它与 `--all` 用同一套版本判定。

- **link 安装**（路由三，`node_modules` 里是指回仓库的链接）：改完源码跑
  `node scripts/build_panel_bundle.js` 重建产物，再重启宿主进程。不用重装，也不用改版本号。
- **快照安装**（路由二、四、五，插件管理器按 name+version 判「已装」）：同版本重装返回
  `changed=false`、产物不换。要换版本：把 `dsh-plugins/dsh-sleuth-panels/package.json` 的 version
  加一、重建产物，再按原路装一次；或 `node scripts/panel_install.js --force` 强制换装。
- 两种都改不到"用户手上那个 tab"：改完必须重启宿主进程，host 半才会加载新代码。
  版本串在诊断 tab 右上角，用来判断页面拿到的是哪一版。

改面板源码的人有三件事同一提交：重建产物、bump 版本、再跑一次生成器（版本号在构建时注入
`lib/client.js` 的 `PANEL_VERSION`）。不 bump 时，路由二、五不会替换老版本。

## 面板清单

**常驻包（`dsh-sleuth-panels`）**：会话里一个 tab，全库读数在整页「Ascend Sleuth」。

| 界面 | 目录 | 注册点 | 视图 |
|---|---|---|---|
| 诊断 tab | `dsh-plugins/ascend-panel/` | `conversation.view` id `ascend-diagnose`(20) | 会话列表/轨迹/证据；每张卡可「打开会话」，列表可切「按价值」排序 |
| 诊断记录 | `dsh-plugins/ascend-panel/` | `sidebar.footer.action` id `sleu-ledger-entry`(30) + `shell.overlay` id `sleu-ledger-overlay`(40) | 诊断会话清单，可按时间或按价值排序（默认按时间），点一行切过去（只读 + 导航） |
| Ascend Sleuth · 指标 | `dsh-plugins/ascend-panel/` | 视图登记表 `SLEUTH_VIEWS.metrics`，整页按 id 取 | 指标闭环判决（判据→结论/证据/下一步）/容量逐格/趋势 |
| Ascend Sleuth · 自演进 | `dsh-plugins/ev-panel/` | 视图登记表 `SLEUTH_VIEWS.evolve`，整页按 id 取 | 首屏是体检判决（要处理的判据 + 下一步动作）与触及面 |
| Ascend Sleuth 外壳 | `dsh-plugins/sleuth-console/` | `main` key `ascend-sleuth-console` + `sidebar.panellist` 同 id | 两个子页的切换与侧栏图标（`icon.svg`） |

侧栏另有**会话行的「待回报」标记**（`sidebar.session.row.leading` / `.hover`，同一个 id）：只标
`traces/` 里 `feedback.outcome: pending` 的会话，没有轨迹的会话不显示。**按轨迹的
`harness_session` 匹配侧栏行**（轨迹的 `session_id` 是诊断名，两套 id 不通）；没写这一项的轨迹
标不出来。行首小点只在空闲且已读的行渲染（运行中/未读让位给 DSH 自己的状态点），悬停卡里有一行
欠账说明。数据走瘦 RPC `ascend-session-marks`，所有行共用一次取数。

**热加载（逐面板）**：没有整页容器，三个视图各占一个 `conversation.view` tab。

| 面板 | 目录 | tab id / label |
|---|---|---|
| 诊断 | `dsh-plugins/ascend-panel/` | `ascend-diagnose`(20) / 诊断 |
| 指标 | `dsh-plugins/ascend-panel/` | `ascend-metrics`(21) / 指标 |
| 自演进 | `dsh-plugins/ev-panel/` | `ascend-evolve`(22) / 自演进 |

## 非面板包：vllm-kb 接入插件

`dsh-plugins/dsh-sleuth-vllm-kb` 不是面板。它给设置页加左侧栏一项「vllm-kb」（配端点、启停、测
连通），并注册四个 `vllm_kb_*` 工具。它默认随面板一起装（路由四的 `--all`、路由三的第二条
`add`）；只有要单独补装时才用下面这两条：

```
node scripts/panel_install.js --spec "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
dsh.cmd plugin --profile desktop add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
```

第一条要地址与 token，第二条不要。换装要重启才加载。装完在设置页左侧栏看到「vllm-kb」；
工具行 `vllm-kb-tools` 与 `vllm-kb-ocr` 默认关，在插件页单独打开。

## 依赖预检（激活前跑）

面板 host 已做优雅退化（自演进 JSON 不截断、无 `traces/` 显示空态、缺 PyYAML 给提示），
装载前跑一次预检，把"依赖缺失"改成主动告知：

- **通用**：确认会话工作区是 ascend-sleuth 仓库（Host 从 `session.header.cwd` 解析数据目录）。
- **自演进看板**：确认 Python 3 + PyYAML 可用。面板 host 自动探测解释器
  （`python3` → `python` → `py -3`，取第一个能打印 Python 3.x 的；Windows 上 `python3` 常是应用商店
  的空壳，不打印任何东西）：

  ```
  python -c "import yaml; print('pyyaml ok')"   # 失败 → 试 py -3；再失败 → pip install pyyaml
  ```

  失败就告诉用户"自演进看板需要 PyYAML，请 `pip install pyyaml`"，再决定是否仍加载。
- **诊断面板**：`traces/` 可能不存在（gitignored、按需生成），host 把"目录不存在"当空态处理；
  用户预期有历史诊断却显示为空时，提示运行 `/skill:diagnose` 生成 `traces/`。Ascend Sleuth的指标子页需要 Python 3
  + PyYAML：「闭环判决」跑 `scripts/metrics_health.py --json`（判据读 `metrics/gates.yaml`），
  「实时计算」跑 `scripts/trace_metrics.py`；缺依赖时面板显示「体检不可用」并给出可执行提示，
  所以预检失败仍可加载，只是首屏没有判决条。

## 回退（热加载的版本差异）

- **loader 注册不了工具**（`harness.registerTool` 缺失）→ 内联面板本身：读两个文件全文，
  `code.host` / `code.client` 原样粘贴。文件是函数体形态（`return { apply(ctx) {...} }`），别改形态
  ——动态插件不经过打包器，`export default` / `import` 等 ESM 语法无法加载。
- **热加载整条不可用**（没有 `cordis_define`）→ 按第 0 步走其余四条。

## 交互原则

- **热加载跨 session**：工具 `panel_from_file` 是进程全局的，新 session 不必再装 loader（重复装载会
  撞名但不报错，工具照常可用）；面板插件是 per-session 的，新 session 认领不了旧 session 的插件，
  会新建一个同 tab id 的插件覆盖显示，旧插件仍在跑。要清理就重启 DSH，或在各 session 内对自己的
  插件 `cordis_stop`。
- **其余四条路跨 session**：插件装在 profile 层，每个会话共用一份，重启不丢；换版本按「更新已装的
  面板」处理。
- 面板是只读可视化加指令生成器：展示状态、生成续接/沉淀指令供用户触发，面板自身不做决策与写入
  （唯一例外：诊断面板的沉淀状态标记由用户在面板确认后更新）。自演进看板纯只读：展示卡状态与演进
  信号，产卡/验证走 agent 与攒批。

## 依赖

- DSH 会话。热加载另需 `cordis_define` / `cordis_run` / `cordis_inspect_self` 工具；常驻插件包另需
  `plugin_manager` 工具；桌面版命令行另需安装目录下的 `dsh` / `dsh.cmd`（不在 PATH 上，用绝对路径）；
  HTTP 脚本安装另需日志里有 `dsh web:` 行，或能传 `--url` / `--token`；插件页粘贴另需用户能操作侧栏
  「插件」页并刷新页面。
- 工作区为 ascend-sleuth 仓库（Host 从 `session.header.cwd` 解析数据目录）。
- Host 服务：`fs` / `sessions` / `shell` / `connection`。
- **自演进看板**：Python 3 + PyYAML，两个脚本 `scripts/ev_board_data.py`（卡库/触及面/现场聚合）与
  `scripts/evolution_health.py --json`（体检判决，判据在 `proposals/gates.yaml`）。判决是一次独立
  调用：它失败时面板不渲染结论条，其余区块照常。
- **诊断面板（指标）**：`shell` + Python 3 + PyYAML：「闭环判决」跑 `scripts/metrics_health.py --json`、
  「实时计算」跑 `scripts/trace_metrics.py`；缺依赖时判决条退化为「体检不可用」加可执行提示。
- 诊断「打开证据 / 打开报告」按方言阶梯探测：Windows 先试 `Start-Process`，再 `open`、`xdg-open`、
  `explorer.exe`，按退出码判定并回报用了哪一路（Windows 上 `ctx.shell` 接的是 PowerShell，不是 bash）。
  四种都不行时界面给原因。
- 「看报告」不需要外部程序：报告正文由 host 只读读入后在面板内渲染（章节跳转 + 复制全文），
  「打开文件」才依赖上面的阶梯。

## 说明

- 仓库内 `dsh-plugins/<面板>/` 是代码的权威版本（含各面板 README）；`dsh-plugins/loader/` 是热加载的
  入口；`dsh-plugins/dsh-sleuth-panels/` 是常驻插件包（`lib/` 为生成物）。跨面板的颜色、字号、
  复用窗口与文案约定见 `dsh-plugins/README.md`。
- 热加载的动态定义只存在于当前 DSH 进程，重启后需重新加载；其余四条路装在 profile 层，重启后仍在。
- 路由三装的是 link 依赖，指向仓库里那份代码。仓库换位置或 worktree 被清掉，这条链接就断了，面板
  随之加载失败（启动输出里是 `failed to import`，不是界面提示）；那时按原命令重装一次。
- 改面板代码走仓库，装载走本 skill；两份产物由生成器保持一致。
