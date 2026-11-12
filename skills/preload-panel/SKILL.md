---
name: preload-panel
description: >
  在 DSH 会话中加载 ascend-sleuth 面板，并处理「装了但 tab 不出现」。先按本机给模型的工具与桌面版
  自带的东西选装载路：有 cordis_define / cordis_run 在会话内热加载；有 plugin_manager 就装常驻插件
  包；DSH Desktop 用安装目录自带的 dsh 命令行把 dsh-plugins/dsh-sleuth-panels/ 装进 profile（拿不到
  地址与 token 时这是主路）；另有 scripts/panel_install.js --all 经 /api 通路一次装面板、vllm-kb、
  诊断状态条与诊断画布四个包、以及在侧栏「插件」页粘贴路径两条备用路。面板包的界面分三块：会话里一个
  「诊断」tab、左侧栏一个「Ascend Sleuth」整页（「知识库」「指标」「自演进」）、侧栏页脚一个「诊断记录」入口
  （列出诊断会话，可按时间或按价值排序，点一行切过去）；另有独立的状态条包，一块：输入框上方的
  诊断状态条（可单独装卸）；另有独立的诊断画布包，左侧栏一个「诊断画布」图标、主区一整页，离线渲染
  `traces/`（可单独装卸）。热加载路径没有整页容器、页脚入口、状态条与画布，仍是三个 tab（诊断 / 指标 / 自演进）。
  日常同步代码后不用调用本 skill（随仓库装的重启 DSH 生效，插件页装的重装后再重启）；只在首次装载或「装了但 tab 不出现」时用。
  仅 DSH 可用
  ——依赖 conversation.view / main / sidebar.panellist / sidebar.footer.action / shell.overlay /
  conversation.input.dock / conversation.input.right 插槽；
  其他 agent（Claude Code / Codex / pi）无此机制。
---

# Preload Panel

DSH 会话中加载可视化面板、诊断状态条与诊断画布。常驻包把界面分成四处：会话里一个「诊断」tab
（`conversation.view`，读这一单）；全库读数在整页「Ascend Sleuth」（`main` 的 keyed 条目 +
`sidebar.panellist` 图标，「知识库」「指标」「自演进」三个子页，默认落在
「知识库」）；另有一个独立的 `dsh-sleuth-copilot` 包，把状态条
放在输入框上方（`conversation.input.dock`）、入口放在输入区工具条（`conversation.input.right`）、
全库动作放在浮层（`shell.overlay`），可单独装卸；另有一个独立的 `dsh-sleuth-canvas` 包，把诊断旅程
画布放进整页（`main` 的 keyed 条目 + `sidebar.panellist` 图标），可单独装卸。热加载路径没有整页容器、
状态条与画布，退回三个 `conversation.view` tab。

面板代码只有一份：`dsh-plugins/<面板>/panel-host.js` 与 `panel-client.js`（动态插件方言的函数体）。
诊断画布包不同：`host/index.js` 是 ESM，`client-src/*.js` 拼成生成物 `lib/client.js`。
装法有五条。**DSH Desktop（官方与社区发行版）按第 0 步现状检查的三件事选路**：有安装目录自带的
命令行走路由三；命令行不在、
日志里有带 token 的地址走路由四；都没有走路由五。其余形态的细节见文末附录。先跑第 0 步的现状检查
判本机走哪条。
除热加载外，装完都要**重启宿主进程**：host 半的接口路由在进程启动时装载，刷新页面只换浏览器那一半。

## 第 0 步：判本机走哪条路

先跑一条只读的现状检查（下称快检）：

```
node scripts/panel_status.js
```

它一次报清四件事：DSH_HOME 与当前 profile 名、安装目录里的 dsh 命令行在不在、四个包在 profile 里
怎么登记（`dependencies` / `dsh.profile.bundles` / 快照安装（插件页或插件管理器把包复制到
`.generations/live`）的 `pnpm.overrides` 与 `generationProjection`）、实际加载的版本与仓库版本差在哪。

**profile 名与 DSH_HOME 都不要按默认值猜**：桌面版的 profile 名随发行版变（`desktop`、`web` 都见过），
DSH_HOME 在桌面版是 `<userData>/harness`，独立命令行才在 `~/.dsh`。按默认值找会对着错目录报"未装"。

官方发行版与社区发行版（例如 `dsh-desktop`）都是 DSH 的 Electron 外壳，装载机制是同一个：把包登记进
DSH profile 的 `dependencies` + `dsh.profile.bundles`，或走同一个插件管理器服务。差异只在宿主侧：
DSH_HOME 位置、profile 名、命令行是否随包、token 是否落日志、插件页是 link 还是快照投影。快检按
实际发现报，不按发行版名写死。

判路：

| 本机条件 | 走哪条 |
|---|---|
| DSH Desktop（官方或社区发行版；模型侧没有 `cordis_define` / `cordis_run`，也没有 `plugin_manager`） | 有快检报的 dsh 命令行 → 路由三；没有命令行但日志里有带 token 的地址 → 路由四；都没有 → 路由五 |
| 有 `cordis_define` / `cordis_run` | 路由一：热加载（只在本会话生效，见附录） |
| 没有上面两件、但有 `plugin_manager` | 路由二：常驻插件包（见附录） |
| 要在装之前确认包能加载，或界面不可用 | 路由四：HTTP 脚本安装（先要有日志地址与 token） |

**默认装四个包**：面板包 `dsh-sleuth-panels`、`dsh-sleuth-vllm-kb`（设置页左侧栏的「vllm-kb」一栏，
四个 `vllm_kb_*` 工具默认关）、独立的 `dsh-sleuth-copilot`（输入框上方的诊断状态条与诊断总览）、
独立的 `dsh-sleuth-canvas`（左侧栏「诊断画布」整页，离线渲染 `traces/`）。路由三对后三个包各再跑一次
`add`；路由五在插件页粘贴四次；路由四用 `--all` 一次装齐；路由二用 `install_bundle` 装四次。四个包
分开登记：装面板不会带上另外三个。状态条与诊断画布都是独立包，卸掉它们不影响面板。

桌面版落在第一行，原因有两条：发行版把插件管理器那条模型工具标成 `disabled: true`
（`@deepseek-ai/dsh-base/cordis.patch.yml`、`@deepseek-ai/dsh-web-app/cordis.patch.yml` 各一处），
模型侧没有 `plugin_manager`；较新的版本又从模型侧撤掉了 `cordis_define` / `cordis_run`。
界面「插件」页调的是同一个插件管理器服务，模型够不着。桌面版在安装目录里可能带一条 `dsh` 命令行
（见路由三）；有的发行版不带，那就看日志地址能不能走路由四，再不行走路由五。

**Windows 的 shell 是 PowerShell**：跑这些脚本时原样执行、下一行读 `$LASTEXITCODE`，不要把 stderr
用 `2>&1` 并进管道再 `Out-String`——PowerShell 5.1 会把每行 stderr 包成 ErrorRecord，
`$ErrorActionPreference` 为 `Stop` 时整条命令中止，退出码也可能被带成 1。有的脚本成功时也会写
stderr（面板包冒烟会打 `RPC 路由已注册`），以退出码为准；失败时再去掉重定向重跑一次看 stderr。

## 路由三：桌面版自带的命令行（DSH Desktop 的主路）

桌面版不在 PATH 上装 `dsh`。安装目录里可能带一份，位置随发行版与安装位置变：

- Windows：`<安装目录>\resources\runtime\cli\bin\dsh.cmd`
- macOS：应用包内 `<应用名>.app/Contents/Resources/runtime/cli/bin/dsh`（有的发行版不带）

**位置以第 0 步快检为准**。它给出实际路径；没有就说明这个发行版没带命令行，转路由四（日志里有
带 token 的地址时）或路由五。不要把 `%LOCALAPPDATA%` 当唯一位置：安装时可以选盘符，快检会从
运行中的程序反查安装目录，再兜底默认位置。

1. **装**（`<profile>` 与 `<dsh>` 都用快检报的值，别写死）：

   ```
   <dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-panels"
   <dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
   <dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-copilot"
   <dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-canvas"
   ```

   四条都要跑：第一条装面板，第二条装 vllm-kb（设置页左侧栏那一栏），第三条装诊断状态条
   （输入框上方的交互层），第四条装诊断画布（左侧栏图标 + 主区整页）。
   命令做三件事：在 profile 目录跑包管理器、把依赖写成 `link:<仓库路径>`、把包名加进
   `dsh.profile.bundles`。最后一项决定启动时加载它——只写了依赖没进 bundles，等于没装。
   输出里的 `Already up to date` 只说明包管理器没搬文件，装没装看下一行的 `dependencies:`。

   **先看 profile 的 `pnpm.overrides`**：插件页装过的包会留一条指向 `.generations/live` 的覆盖，
   它压过 `dependencies` 里的 link。有这条的包继续用插件页更新（见「更新已装的面板」），不要用
   路由三的 link 覆盖它。

2. **读结果**：profile 的 `package.json` 两处都在才算登记完成——`dependencies` 里一条
   `dsh-sleuth-panels: link:<仓库路径>`，`dsh.profile.bundles` 里一项 `dsh-sleuth-panels`。
   界面「插件」页显示已安装不能当证据：它读的是登记，不是加载结果。第 0 步的快检已经报过这两处，
   装完再跑一次即可。

3. **profile 受保护的部分**：发行版把 `desktop` 这个名字留给 Electron 应用，`--dump-config` 无条件
   拒绝它（报 `error: profile "desktop" is managed exclusively by the Electron application`）。
   `plugin` 子命令能不能管 `desktop` 取决于启动器：桌面版自带的那条命令行以 `manageDesktopProfile`
   放行，从 PATH 另装的通用 `dsh` 仍会被拒。当前 profile 不叫 `desktop` 时，`--dump-config` 可以直接
   跑；叫 `desktop` 要看配置能不能拼出来，用「无 token 时的验证」里的临时副本。

4. **验证**：按这个顺序，有结论就停。重启指完全退出 DSH Desktop 进程，关窗口不算。

   1. 先重启一次。装、换版本、补登记都要；host 半只在进程启动时装载，刷新页面换不到它。
   2. 重启后：工具在，说明 host 半加载了这次的面板包；刷新页面，诊断 tab 在且版本串等于包版本，
      安装完成。版本串是构建时注入 `lib/client.js` 的 `PANEL_VERSION`，与包版本是否一致由
      `node scripts/build_panel_bundle.js --check` 判定。装诊断画布的话看侧栏有没有「诊断画布」图标，
      页面右下脚注的版本串等于 `dsh-plugins/dsh-sleuth-canvas/package.json` 的版本。
   3. 重启后工具不在 → host 半没加载，读「装上了但 tab 不出现」，重点查包能不能加载。
   4. 要定位是哪一半没加载，跑 `node scripts/verify_panel_desktop.js --profile <profile>`
      （见「无 token 时的验证」）。

   工具在只说明进程里有某份面板 host 半（可能是上一版，也可能是热加载装的那份），不证明是这次装的
   版本；版本串是 host 从已加载的包里发给浏览器的产物版本，只说明浏览器半，浏览器缓存会让它旧，
   有客户端热重载（HMR）的开发部署也可能让它先变。host 半换了没有，以重启后的工具与 RPC 为准。

## 路由四：HTTP 脚本安装（日志地址可用时）

1. **装**：`node scripts/panel_install.js --all`。四个包各自判版本：与仓库一致就按安装方式说明要不要
   重启，不一致才换装（换装后要重启，见「更新已装的面板」）；只想装其中一个时用 `--spec <包目录>`。
2. **核对**：`node scripts/panel_install.js --all --check`，四个包的版本号都应与仓库里的一致。

`node scripts/panel_install.js` 走的是界面同一条通路：先 `GET <base>/?token=<token>` 换会话 cookie，
再 `POST <base>/api/pluginManager/<方法>`，信封是
`{type:'client-request', rpcId, method:'pluginManager/<方法>', payload:{args:{…}}}`。先 `inspect`
（spec 传字符串）：认了且没装就调 `installBundle(spec, {enabled:true})`；回 `already-installed`
（这条 refused 不带包名）就从本地 `package.json` 读包名，按版本判要不要换装（见「更新已装的面板」），
版本一致时再调 `setBundleEnabled(name, true)`；spec 不是本地路径时读不到包名，脚本以退出码 1 收场。

- `--check` 只查状态，只对能定到包名的目标给判断（定不到包名或目标没装都退 1）。
- `--sync` 在版本一致时按安装方式给结论；配 `--all` 才对四个包都生效，单跑只处理面板包。
- `--remove` 卸载；`--spec <spec>` 换目标（包名、Git 地址、tarball 或本地绝对路径）；
  `--all` 处理面板包、vllm-kb 接入插件、诊断状态条与诊断画布四个包；`--force` 跳过版本判断强制换装。
- 地址与 token 的取法同 `panel_rpc_probe.js`：先扫日志里的 `dsh web: …/?token=…` 行，取不到再传
  `--url` / `--token` / `--log`。
- 退出码：0 = 操作完成（`application` 可能是 `restart-required`，要重启才加载新版本）｜2 = 拿不到
  地址与 token，或地址取到了但连不上，或 `/api` 没有认领端点、未授权｜1 = 其他失败。

**桌面版上这条路看快检的「日志地址」那一行**：有的 Windows 桌面版把 `dsh web:` 那一行写进自己接管的
管道，磁盘上找不到（`--no-open` 只跳过开浏览器，那一行照常打印）；日志目录里也没有；token 由宿主
经进程间通道交给界面，不落文件。有的 macOS 桌面版会把带 token 的地址写进
`~/Library/Logs/<产品名>/harness.log`，这条路能通。拿不到就改用路由三或路由五，不要反复试。

**一台机器上可能同时跑着两个 DSH 实例**，各有自己的 `DSH_HOME`、`profiles` 与监听地址。快检只认与
本会话 `DSH_WEB_URL` 地址一致的那份日志。对不上时它报「取不到」，写明哪份日志因为地址不一致没采用。
照被排除那份日志里的地址装，才会装进另一份 profile。

## 路由五：插件页粘贴（命令行不可用，或用户能操作界面时）

1. 让用户在侧栏「插件」页的添加入口粘贴 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-panels`，
   再用同一条路径把 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb` 与
   `<仓库绝对路径>/dsh-plugins/dsh-sleuth-copilot` 与 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-canvas`
   各粘一次。
   该入口接受包名、Git 地址、压缩包或本地绝对路径。粘的是这个包目录，不是面板源目录
   `dsh-plugins/ascend-panel/`——后者没有 `package.json`，入口会拒。
2. **读结果**：界面不给模型可读的 `application` / `warnings`，改读 profile 的 `package.json`
   （`dependencies` 与 `dsh.profile.bundles` 两处都要有；第 0 步的快检会报），以及界面自己报的成功
   或失败。带快照机制的发行版会在 `package.json` 里多一个 `dsh.desktop.generationProjection` 字段，
   并在 `dirname($DSH_PROFILE_DIR)/.generations/live/` 下放一份包快照；没有这两个东西的发行版，
   装完就是前两处记录。按机器上实际有的那套读，别按另一套找。
3. **验证**：先跑 `node scripts/panel_rpc_probe.js`（有 token 打 RPC，没有就只验 host 半：0 = RPC 通，
   3 = 只证到 host 半、端点与取数没验，2 = 拿不到地址或路由没注册／带 token 时未授权，1 = 其它失败）；
   再让用户刷新页面，浏览器代码在页面启动时装载。tab 在且版本串等于包版本，浏览器半才算换到；
   host 半有没有加载看工具与 RPC。状态条包另外看三处席位：`conversation.input.dock` 的
   `sleuth-copilot`、`conversation.input.right` 的 `sleuth-copilot-toolbar`、`shell.overlay` 的
   `sleuth-copilot-palette`。诊断画布没有 tab，看侧栏「诊断画布」图标与页面右下脚注的版本串。
4. **卸载**：在插件页里移除该包。

## 装不上：`dsh plugin add` 报 registry 元数据拉取失败

触发条件：profile 已带 registry 依赖（如既有插件包），或 add 的 spec 是包名。只 add 本地绝对
路径的 link 依赖时 pnpm 不联网，不报这类错。

症状：`dsh plugin add` 报元数据拉取失败。node 系 pnpm（DSH Desktop 捆绑版）报
`ERR_PNPM_META_FETCH_FAIL` / `ERR_PNPM_PING_ERROR`；Rust 原生 pnpm 12 报
`ERR_PNPM_PACKAGE_MANAGER_ADD_RESOLVE_LATEST` 或 `Failed to fetch metadata` 字样。
现象：node / curl 直连同一 registry URL 返回 200，pnpm 的拉取却失败。
原因：pnpm 的 fetch 走了不可达的代理。

代理来源：`~/.npmrc` 的 `proxy` / `https-proxy`，或环境变量 `HTTP_PROXY` / `HTTPS_PROXY`。
`pnpm config get proxy` 显示 undefined 不等于没走代理，以实际连接目标为准。

按顺序查：

1. 看 pnpm 实际连到哪。node 系 pnpm（DSH Desktop 捆绑版）用
   `$env:NODE_DEBUG="net"; <dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/<包名>"`
   或 bash 的 `NODE_DEBUG=net <dsh> plugin ...`，stderr 出现
   `connect: attempting to connect to <地址>:<端口>`：代理在生效。
   Rust 原生 pnpm 12 不发 node 的 NET 日志行，跳过本步直接验代理。
2. 跑 `node -e "fetch('<registry URL>').then(r=>console.log(r.status))"`。
   直连返回 200 而 pnpm 失败：代理是原因。

修法按代理来源：

- npmrc 来源（`~/.npmrc` 有 proxy 行）：profile 目录的 `.npmrc` 追加空值覆盖，不碰用户级
  `~/.npmrc`：

  ```
  proxy=
  https-proxy=
  ```

- env 来源（环境变量有 HTTP_PROXY）：`.npmrc` 空值覆盖压不住 env，要清变量再跑。
  PowerShell 只列大写名（env 大小写不敏感，重复列出会报找不到路径）：
  `Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY`；
  bash 用 `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY`。
  只影响当前会话，不改持久配置。

再跑 `<dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/<包名>"`。
代理地址是本机环境事实，修环境，不写进 skill。

`offline=true` 的 profile 另报离线解析失败：本地 pnpm 缓存缺该包元数据，报错带缺的
jsonl 路径。错误码随 pnpm 版本变，node 系是 `ERR_PNPM_NO_OFFLINE_META`。这不是代理
问题。让 pnpm 在线拉一次再切回离线。

## 装上了但 tab 不出现

按这个顺序查，一步一个证据。

1. **看宿主启动输出**：装完第一次启动时，stderr 会打出没加载成的插件行，形如
   `1 entry did not activate` 与 `failed to import: …`。有这两行，问题在包，不在界面。
2. **包静态 import 了 `@deepseek-ai/*`**。装进 profile 的包按自己的真实路径解析模块，到不了安装处的
   `node_modules`。有的发行版在启动时注册模块回退（macOS 桌面版的
   `<安装目录>/Resources/host-module-fallback.mjs`），有的没有。没有回退时报错原文是
   `Cannot find package '@deepseek-ai/dsh-tools'`，表现是：插件页显示已安装、tab 一个都没有、
   面板接口回 405。修法在包这一侧，不在 profile：把那句 import 改成能解析到就用、解析不到用包内的
   最小实现（`dsh-plugins/dsh-sleuth-panels` 现在这么做），再重建产物、重启。
3. **host 半挂没挂的旁证**：面板包看会话工具列表里的 `ascend_trace_status`（由 host 半注册），
   或跑 `node scripts/panel_rpc_probe.js --host-only`。状态条包看 `/sleuth-copilot` 前缀路由：
   `GET` 回 405 且 `Allow: POST` 说明路由在，未授权的 `POST` 回 401。都没有就先查第 1、2 步。
   工具或路由在也不等于这次装的包已加载（可能是上一版）；版本串只看浏览器半，host 半在重启后再看
   工具与 RPC。状态条没有模型侧工具，别用工具清单判它。
4. **只有浏览器那一半没换**：tab 在、版本串是旧的 → 刷新页面；仍旧就关浏览器缓存
   （DevTools 勾 Disable cache）。
5. **接口 401 或 405**：先看请求方法。`POST` 回 401 = 路由在、请求没带会话 cookie，用带 token 的
   地址进过一次页面即可；`POST` 回 405 = 路由没注册（host 半没加载）。`GET` 反过来：405 = 路由在
   （handler 只接 POST），404 = 没注册。带 token 的探针打 `POST`，不带 token 的 host 半判定看
   `GET`，别把两种数混着读。

**诊断画布没有 tab，侧栏图标不出现时**：它是独立整页包，症状是侧栏少一个「诊断画布」图标，不是少
tab。host 半注册了 `/sleuth-canvas` 的 prefix 路由时，`GET <base>/sleuth-canvas/list` 回 405、
未授权的 POST 回 401，对比未知路径的 404 可判路由在不在。页面右下脚注的版本串（`v<version>`）
只说明浏览器半。

## 无 token 时的验证（桌面版）

桌面版不一定把 `dsh web:` 那一行留给磁盘：Windows 桌面版上脚本常常取不到地址与 token；
有的 macOS 桌面版会把带 token 的地址写进 `harness.log`。地址不用猜：会话环境里的 `DSH_WEB_URL`
就是本实例地址，只差 token。所以先跑一次探针：

```
node scripts/panel_rpc_probe.js
```

有 token 时它按线协议打一条 RPC；取不到 token 时它退到 host 半判定，只打三条不带 cookie 的请求：

- `GET <base>/ascend-sleuth-panels/__probe__` 回 405 且 `Allow: POST`：路由在，host 半已加载。
  这条 405 由面板 handler 的方法闸回，`Allow` 写的是 `POST`；静态层的通用 405 写的是 `GET, HEAD`。
- `GET <base>/__dsh_probe_unknown__` 回 404：对照，说明 404 才是「没这个路径」。
- `POST <base>/ascend-sleuth-panels/__probe__` 回 401：鉴权门在，请求只是没带会话 cookie。

退出码：0 = RPC 通；3 = 只证到 host 半（路由在、鉴权门在），端点与取数没验；2 = 拿不到地址，
或路由没注册（host 半没加载），或带 token 时未授权；1 = 其它失败（连不上、信封不合法、面板侧降级）。
只看路由那一层时加 `--host-only`。

要证明「端点真能取数」「加载的是这一版」，才用下面的临时实例。

临时实例用一条命令（`<profile>` 用第 0 步报的值）：

```
node scripts/verify_panel_desktop.js --profile <profile>
```

它在系统临时目录建一个临时 DSH_HOME 和一份临时 profile（默认最小组合：`@deepseek-ai/dsh-base` +
`@deepseek-ai/dsh-web-app` + 已登记的包，profile 级与 home 级 patch 都置空），把 `node_modules`
联接指回原 profile，然后：

1. `dsh --profile <临时名> --dump-config`：每个已登记的包各有一段 `# == <包名>`。
2. `dsh --profile <临时名> --no-open --host 127.0.0.1 --port 0`：读它打印的 `dsh web:` 地址。
3. 换会话 cookie、读页面清单、打一条 `ascend-traces-list`。
4. 停实例、删临时 DSH_HOME。

退出码：0 = 全通；1 = 有一条判据失败（输出里点名是哪一步，含"依赖有、bundles 没有"的登记
不完整）；2 = 前置缺失（找不到 dsh 命令行、DSH_HOME、profile，profile 不是 web 形态，或已登记的包
一个都没有），先看日志地址能不能走路由四，再不行路由五，别反复试。

默认的最小组合只回答"这个包在当前安装里能不能加载"，profile 里其它插件的全局锁与端口不会带进来。
要复现"与其它插件同场"的问题加 `--full`，用配置层完整副本（仍只复制配置文件，不复制
`node_modules`）；同机再起实例时，那些插件可能互相抢锁，第二个实例就起不来。

整个过程在临时 DSH_HOME 里跑：真实 home 只读，验证实例的日志、缓存、sessions 都落在临时目录，
跑完删掉。`--keep` 保留临时 DSH_HOME 现场。

手工做同样的验证时，两个坑：

- 临时 profile 的目录名必须与 `--profile` 参数完全一致。CLI 按名字到
  `<DSH_HOME>/profiles/<名字>/` 找目录，多一个字少一个字都报 `profile "xxx" does not exist`。
- 改 `package.json` 的 `name` 要用无 BOM 的 UTF-8 写回。Windows PowerShell 的
  `Set-Content -Encoding UTF8` 会写 BOM，`JSON.parse` 直接报 `Unexpected token`。

## 更新已装的面板

日常同步代码不用调本 skill。拉完代码后，先看诊断 tab 顶部有没有「面板有新版」提示；它由仓库里的
包版本与宿主已加载的版本比对得出。有提示就重启 DSH：加载新版本后提示消失；重启后仍在，从插件页
装的要用同一路径重装，随仓库装的检查产物是否重建（`node scripts/build_panel_bundle.js`）。这个
提示从带它的版本开始才有：本次升级到它之前装的旧面板不会给提示，合并后重启一次即可。

**link 安装**（profile 的 `dependencies` 是指向仓库的 `link:<仓库路径>`）：不用重装，重启 DSH 即加载
新代码。热加载路（附录路由一）没有这个提示，修改后要用 `panel_from_file` 重载。

**快照安装**（插件页或插件管理器复制进 profile 的快照）：重启不会换版本。要用同一路径重装一次，
再重启。桌面版插件页装过的包会在 profile 的 `pnpm.overrides` 里留一条指向 `.generations/live` 的
覆盖，实际加载的是那一份快照；这类包继续走插件页更新，路由三的 link 不会替换它。

`node scripts/panel_install.js --all --sync` 只对快照安装有意义：四个包各自比版本，不一致就换装，
换装后要重启。link 安装下它比的是同一份磁盘版本，判不出 host 半新旧；结论按安装方式给。
`--all` 决定处理哪几个包；不加时只处理面板包。

**开发者改面板源码**：先 bump `dsh-plugins/dsh-sleuth-panels/package.json` 的 version，再跑
`node scripts/build_panel_bundle.js` 重建产物（版本号在构建时注入 `lib/client.js` 的
`PANEL_VERSION`），同一提交提交。不 bump 时，快照安装不会替换老版本。

**诊断画布**是独立包，产物用 `node dsh-plugins/dsh-sleuth-canvas/build.mjs` 重建：改 `client-src/`
后跑它，刷新页面即可；改了 `host/index.js` 要重启。版本号在
`dsh-plugins/dsh-sleuth-canvas/package.json`，由构建写进 `lib/client.js`；bump 后按原路重装。
页面右下脚注的版本串（`v<version>`）只说明浏览器半。

**状态条包**没有生成器：直接改 `dsh-plugins/dsh-sleuth-copilot/lib/` 下的源码，`package.json` 的
version 与 `lib/client.js` 的 `PLUGIN_VERSION` 一起改，再按原路重装。

## 面板清单

**常驻包（`dsh-sleuth-panels`）**：会话里一个 tab，全库读数在整页「Ascend Sleuth」。

| 界面 | 目录 | 注册点 | 视图 |
|---|---|---|---|
| 诊断 tab | `dsh-plugins/ascend-panel/` | `conversation.view` id `ascend-diagnose`(20) | 会话列表/轨迹/证据；每张卡可「打开会话」，列表可切「按价值」排序 |
| 诊断记录 | `dsh-plugins/ascend-panel/` | `sidebar.footer.action` id `sleu-ledger-entry`(30) + `shell.overlay` id `sleu-ledger-overlay`(40) | 诊断会话清单，可按时间或按价值排序（默认按时间），点一行切过去（只读 + 导航） |
| Ascend Sleuth · 指标 | `dsh-plugins/ascend-panel/` | 视图登记表 `SLEUTH_VIEWS.metrics`，整页按 id 取 | 指标闭环判决（判据→结论/证据/下一步）/容量逐格/趋势 |
| Ascend Sleuth · 自演进 | `dsh-plugins/ev-panel/` | 视图登记表 `SLEUTH_VIEWS.evolve`，整页按 id 取 | 首屏是体检判决（要处理的判据 + 下一步动作）与触及面 |
| Ascend Sleuth 外壳 | `dsh-plugins/sleuth-console/` | `main` key `ascend-sleuth-console` + `sidebar.panellist` 同 id | 三个子页的切换（默认「知识库」）与侧栏图标（`icon.svg`） |

侧栏另有**会话行的「待回报」标记**（`sidebar.session.row.leading` / `.hover`，同一个 id）：只标
`traces/` 里 `feedback.outcome: pending` 的会话，没有轨迹的会话不显示。**按轨迹的
`harness_session` 匹配侧栏行**（轨迹的 `session_id` 是诊断名，两套 id 不通）；没写这一项的轨迹
标不出来。行首小点只在空闲且已读的行渲染（运行中/未读让位给 DSH 自己的状态点），悬停卡里有一行
欠账说明。数据走瘦 RPC `ascend-session-marks`，所有行共用一次取数。

**诊断状态条（`dsh-sleuth-copilot`，独立包）**：不占 `conversation.view` tab，也不进整页外壳。

| 界面 | 目录 | 注册点 |
|---|---|---|
| 状态条 | `dsh-plugins/dsh-sleuth-copilot/` | `conversation.input.dock` id `sleuth-copilot`(55) |
| 输入区入口 | 同上 | `conversation.input.right` id `sleuth-copilot-toolbar`(5) |
| 诊断总览 | 同上 | `shell.overlay` id `sleuth-copilot-palette`(60) |

它只读 `traces/`（Host 半跑 `lib/copilot_state.py`）；状态修改只在用户点开表单、确认提交后经
`scripts/trace_transition.py` 写回，带内容指纹做并发保护。上游查证不发网络请求：菜单按
`gh` 是否可用给出提示，再生成 prompt 让 agent 走 `scripts/verify_upstream_outcomes.py` 幂等落账（同一结局不重复累加）。
它没有模型侧工具，不是面板，也不依赖面板包。

**诊断画布（`dsh-sleuth-canvas`，独立包）**：不占 `conversation.view`，没有 tab；左侧栏一个
「诊断画布」图标，主区一整页。

| 项 | 内容 |
|---|---|
| 目录 | `dsh-plugins/dsh-sleuth-canvas/`（`client-src/` 是源码，`lib/client.js` 是生成物，`host/index.js` 是 host 半） |
| 注册点 | `main` 的 key `sleuth-canvas` + `sidebar.panellist` 同 id（order 40）；图标 `icon.svg` |
| 数据来源 | 只读本机 `traces/`（按会话工作区或最近一次 DSH 会话的 cwd 找仓库检出）；不联网、不起子进程、不写仓库 |
| 产物 | `node dsh-plugins/dsh-sleuth-canvas/build.mjs` 把 `client-src/*.js` 拼成 `lib/client.js`；`--check` 判产物是否最新。与 `scripts/build_panel_bundle.js` 无关 |

**热加载（逐面板）**：没有整页容器，三个视图各占一个 `conversation.view` tab。

| 面板 | 目录 | tab id / label |
|---|---|---|
| 诊断 | `dsh-plugins/ascend-panel/` | `ascend-diagnose`(20) / 诊断 |
| 指标 | `dsh-plugins/ascend-panel/` | `ascend-metrics`(21) / 指标 |
| 自演进 | `dsh-plugins/ev-panel/` | `ascend-evolve`(22) / 自演进 |

## 非面板包：vllm-kb 接入插件

`dsh-plugins/dsh-sleuth-vllm-kb` 不是面板。它给设置页加左侧栏一项「vllm-kb」（配端点、启停、测
连通），并注册四个 `vllm_kb_*` 工具。它默认随面板一起装（路由三的第二条 `add`、路由四的 `--all`、
路由五的第二次粘贴；诊断状态条是第三条 `add` / 第三次粘贴，诊断画布是第四条 `add` / 第四次粘贴）；
只有要单独补装时才用下面这两条：

```
node scripts/panel_install.js --spec "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
<dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
```

第一条要地址与 token，第二条不要。换装要重启才加载。装完在设置页左侧栏看到「vllm-kb」；
工具行 `vllm-kb-tools` 与 `vllm-kb-ocr` 默认关，在插件页单独打开。

## 依赖预检（激活前跑）

面板 host 已做优雅退化（自演进 JSON 不截断、无 `traces/` 显示空态、缺 PyYAML 给提示），
装载前跑一次预检，把"依赖缺失"改成主动告知：

- **通用**：确认会话工作区是 ascend-sleuth 仓库（Host 先从 `session.header.cwd` 解析数据目录；
  拿不到、或那个目录不是本仓检出时，按会话列表挑一个有 `scripts/metrics_health.py` 的）。
- **自演进看板**：确认 Python 3 + PyYAML 可用。面板 host 自动探测解释器
  （`python3` → `python` → `py -3`，取第一个能打印 Python 3.x 的；Windows 上 `python3` 常是应用商店
  的空壳，不打印任何东西）：

  ```
  python -c "import yaml; print('pyyaml ok')"   # 失败 → 试 py -3；再失败 → pip install pyyaml
  ```

  失败就告诉用户"自演进看板需要 PyYAML，请 `pip install pyyaml`"，再决定是否仍加载。
- **诊断状态条**：需要 Python 3（Host 半跑 `lib/copilot_state.py`，它调用 `scripts/_trace_state.py` 的投影），不需要 PyYAML 以外的包；
  `gh` 未安装或未登录只影响「查 case 上游状态」的提示，不挡状态条加载。
- **诊断画布**：Host 的 `fs` / `sessions` / `webServer`，不依赖 Python。只读 `traces/`；画布用浏览器原生
  Canvas 2D，没有第三方运行时依赖。
- **诊断面板**：`traces/` 可能不存在（gitignored、按需生成），host 把"目录不存在"当空态处理；
  用户预期有历史诊断却显示为空时，提示运行 `/skill:diagnose` 生成 `traces/`。Ascend Sleuth 的指标子页需要 Python 3
  + PyYAML：「闭环判决」跑 `scripts/metrics_health.py --json`（判据读 `metrics/gates.yaml`），
  「实时计算」跑 `scripts/trace_metrics.py`；缺依赖时面板显示「体检不可用」并给出可执行提示，
  所以预检失败仍可加载，只是首屏没有判决条。

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
- 诊断状态条同样以只读为主：状态修改仅在用户点开表单并提交后经 `scripts/trace_transition.py` 写回
  `traces/`；「回报结果」与各类生成指令只写输入框草稿，发送与否由用户按 Enter 决定。

## 依赖

- DSH 会话。热加载另需 `cordis_define` / `cordis_run` / `cordis_inspect_self` 工具；常驻插件包另需
  `plugin_manager` 工具；桌面版命令行另需安装目录下的 `dsh` / `dsh.cmd`（不在 PATH 上，用绝对路径；
  有的发行版不带，走插件页粘贴）；HTTP 脚本安装另需日志里有 `dsh web:` 行，或能传 `--url` / `--token`；
  插件页粘贴另需用户能操作侧栏「插件」页并刷新页面。
- 诊断状态条：Python 3（状态投影）；可选 `gh`（菜单里显示上游查证的准备情况，缺失不挡加载）。
- 诊断画布：Host 的 `fs` / `sessions` / `webServer`，不依赖 Python；只读 `traces/`，没有第三方运行时依赖。
- 工作区为 ascend-sleuth 仓库（Host 先从 `session.header.cwd` 解析数据目录；拿不到、或那个目录不是
  本仓检出时，按会话列表挑一个有 `scripts/metrics_health.py` 的）。
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
  入口；`dsh-plugins/dsh-sleuth-panels/` 是常驻插件包（`lib/` 为生成物）；`dsh-plugins/dsh-sleuth-canvas/`
  是独立整页包（`lib/client.js` 为生成物，构建走它自己的 `build.mjs`）。跨面板的颜色、字号、
  复用窗口与文案约定见 `dsh-plugins/README.md`。
- 热加载的动态定义只存在于当前 DSH 进程，重启后需重新加载；其余四条路装在 profile 层，重启后仍在。
- 路由三装的是 link 依赖，指向仓库里那份代码。仓库换位置或 worktree 被清掉，这条链接就断了，面板
  随之加载失败（启动输出里是 `failed to import`，不是界面提示）；那时按原命令重装一次。
- 改面板代码走仓库；首次装载与换快照版本时看本 skill，日常同步代码不用调它。两份产物由生成器
  保持一致。诊断画布的产物由 `node dsh-plugins/dsh-sleuth-canvas/build.mjs` 保持与 `client-src/` 一致。

## 附录：其他形态 DSH 的装载路

DSH Desktop（官方与社区发行版）主要用路由三/四/五；这一节是路由一、路由二与热加载回退，只给其他形态 DSH（命令行版、
自带插件管理器的发行版）。这两条不是桌面版主路，保留给仍暴露 `cordis_define` / `plugin_manager` 的 DSH 形态，
以及仓库自己的热加载开发；桌面版会话里不出现这两件工具时不会读到。先按第 0 步判路，再按需读。

### 路由一：热加载（会话里有 `cordis_define` / `cordis_run`）

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

### 热加载回退（版本差异）

- **loader 注册不了工具**（`harness.registerTool` 缺失）→ 内联面板本身：读两个文件全文，
  `code.host` / `code.client` 原样粘贴。文件是函数体形态（`return { apply(ctx) {...} }`），别改形态
  ——动态插件不经过打包器，`export default` / `import` 等 ESM 语法无法加载。
- **热加载整条不可用**（没有 `cordis_define`）→ 按第 0 步走其余四条。

### 路由二：常驻插件包（会话里有 `plugin_manager`）

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
   诊断画布的产物用 `node dsh-plugins/dsh-sleuth-canvas/build.mjs --check` 核对，与上面这条命令无关。

2. **装**：`plugin_manager install_bundle(target: <仓库绝对路径>/dsh-plugins/dsh-sleuth-panels)`；
   对 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb`、`.../dsh-sleuth-copilot` 与
   `.../dsh-sleuth-canvas` 各再装一次。

3. **读安装结果**（`application` 与 `warnings` 决定是否已生效，不要拿日志或进程列表代替）：
   - `applied` → 已生效。
   - `restart-required` → 运行时把先前的模块路径钉住了，要重启 DSH Desktop 才加载新版本；
     替换已装包时通常是这个。
   - `failed` → 读诊断；`webServer` 一类的报错说明路由没注册成功。

4. **验证**：先跑 `node scripts/panel_rpc_probe.js`（0 = RPC 通，3 = 只证到 host 半、端点与取数没验，
   2 = 拿不到地址或路由没注册／带 token 时未授权，1 = 其它失败）；
   再用 `cordis_inspect_query`（client, `Slots`, `listSubTree`, root 下三处）看注册是否在占位列表里：
   `conversation.view` 的 `ascend-diagnose`、`main` 的 key `ascend-sleuth-console`、`sidebar.panellist` 的同一个 id。
   插槽占位与 RPC 都通了也不等于看着对，最后请用户点开一页确认渲染。诊断画布装了就再看 `main` 的
   key `sleuth-canvas` 与 `sidebar.panellist` 同 id。

5. **卸载**：`plugin_manager remove_bundle(target: 'dsh-sleuth-panels')`。
