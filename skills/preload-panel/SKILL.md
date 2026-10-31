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

它一次报清四件事：DSH_HOME 与当前 profile 名、安装目录里的 dsh 命令行在不在、两个包在 profile 里
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

**默认装两个包**：面板包 `dsh-sleuth-panels`，以及 `dsh-sleuth-vllm-kb`（设置页左侧栏的
「vllm-kb」一栏，四个 `vllm_kb_*` 工具默认关）。路由三对 vllm-kb 再跑一次 `add`；路由五在插件页
粘贴两次；路由四用 `--all` 一次装齐；路由二用 `install_bundle` 装两次。两个包分开登记：装面板不会
带上 vllm-kb。

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
- macOS：应用包内 `Resources/runtime/cli/bin/dsh`（有的发行版不带）

**位置以第 0 步快检为准**。它给出实际路径；没有就说明这个发行版没带命令行，转路由四（日志里有
带 token 的地址时）或路由五。不要把 `%LOCALAPPDATA%` 当唯一位置：安装时可以选盘符，快检会从
运行中的程序反查安装目录，再兜底默认位置。

1. **装**（`<profile>` 与 `<dsh>` 都用快检报的值，别写死）：

   ```
   <dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-panels"
   <dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
   ```

   两条都要跑：第一条装面板，第二条装 vllm-kb（设置页左侧栏那一栏）。
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
      `node scripts/build_panel_bundle.js --check` 判定。
   3. 重启后工具不在 → host 半没加载，读「装上了但 tab 不出现」，重点查包能不能加载。
   4. 要定位是哪一半没加载，跑 `node scripts/verify_panel_desktop.js --profile <profile>`
      （见「无 token 时的验证」）。

   工具在只说明进程里有某份面板 host 半（可能是上一版，也可能是热加载装的那份），不证明是这次装的
   版本；版本串是 host 从已加载的包里发给浏览器的产物版本，只说明浏览器半，浏览器缓存会让它旧，
   有客户端热重载（HMR）的开发部署也可能让它先变。host 半换了没有，以重启后的工具与 RPC 为准。

## 路由四：HTTP 脚本安装（日志地址可用时）

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

**桌面版上这条路看快检的「日志地址」那一行**：有的 Windows 桌面版把 `dsh web:` 那一行写进自己接管的
管道，磁盘上找不到（`--no-open` 只跳过开浏览器，那一行照常打印）；日志目录里也没有；token 由宿主
经进程间通道交给界面，不落文件。有的 macOS 桌面版会把带 token 的地址写进
`~/Library/Logs/<产品名>/harness.log`，这条路能通。拿不到就改用路由三或路由五，不要反复试。

## 路由五：插件页粘贴（命令行不可用，或用户能操作界面时）

1. 让用户在侧栏「插件」页的添加入口粘贴 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-panels`，
   再用同一条路径把 `<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb` 粘一次。
   该入口接受包名、Git 地址、压缩包或本地绝对路径。粘的是这个包目录，不是面板源目录
   `dsh-plugins/ascend-panel/`——后者没有 `package.json`，入口会拒。
2. **读结果**：界面不给模型可读的 `application` / `warnings`，改读 profile 的 `package.json`
   （`dependencies` 与 `dsh.profile.bundles` 两处都要有；第 0 步的快检会报），以及界面自己报的成功
   或失败。带快照机制的发行版会在 `package.json` 里多一个 `dsh.desktop.generationProjection` 字段，
   并在 `dirname($DSH_PROFILE_DIR)/.generations/live/` 下放一份包快照；没有这两个东西的发行版，
   装完就是前两处记录。按机器上实际有的那套读，别按另一套找。
3. **验证**：先跑 `node scripts/panel_rpc_probe.js`（退出码 2 = 拿不到地址，或路由没在服务／未授权）；
   再让用户刷新页面，浏览器代码在页面启动时装载。tab 在且版本串等于包版本，浏览器半才算换到；
   host 半有没有加载看工具与 RPC。
4. **卸载**：在插件页里移除该包。

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
3. **host 半挂没挂的旁证**：会话工具列表里有 `ascend_trace_status`（由 host 半注册）。没有它，
   host 半没起来，先查第 1、2 步。有它也不等于这次装的包已加载（可能是上一版或热加载那份）；
   版本串只看浏览器半，host 半在重启后再看工具与 RPC。
4. **只有浏览器那一半没换**：tab 在、版本串是旧的 → 刷新页面；仍旧就关浏览器缓存
   （DevTools 勾 Disable cache）。
5. **接口 401 或 405**：405 = 路由没注册（host 半没加载）；401 = 请求没带会话 cookie，
   用带 token 的地址进过一次页面即可。

## 无 token 时的验证（桌面版）

桌面版不一定把 `dsh web:` 那一行留给磁盘：Windows 桌面版上脚本常常取不到地址与 token；
有的 macOS 桌面版会把带 token 的地址写进 `harness.log`。所以先跑一次探针，能通就不用临时实例：

```
node scripts/panel_rpc_probe.js
```

退出码 0 = host 半与取数路径都通。退出码 2 要看它打印的原因：说「拿不到地址与 token」才用下面的
临时实例；说「路由没在服务」是 host 半没加载，先按「装上了但 tab 不出现」查。

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
不完整）；2 = 前置缺失（找不到 dsh 命令行、DSH_HOME、profile，profile 不是 web 形态，或两个包都
没登记），先看日志地址能不能走路由四，再不行路由五，别反复试。

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

先判装法，两种的更新动作不同。拉完代码先跑 `node scripts/panel_install.js --sync`：两个包各自判
版本，一致就什么都不做，不一致就换装并说明要不要重启。它与 `--all` 用同一套版本判定。

- **link 安装**（路由三，`node_modules` 里是指回仓库的链接）：改完源码跑
  `node scripts/build_panel_bundle.js` 重建产物，再重启宿主进程。不用重装，也不用改版本号。
- **快照安装**（路由二、四、五，插件管理器按 name+version 判「已装」）：同版本重装返回
  `changed=false`、产物不换。要换版本：把 `dsh-plugins/dsh-sleuth-panels/package.json` 的 version
  加一、重建产物，再按原路装一次；或 `node scripts/panel_install.js --force` 强制换装。
  桌面版插件页装过的包还会在 profile 的 `pnpm.overrides` 里留一条指向 `.generations/live` 的覆盖，
  实际加载的是那一份快照；这类包继续走插件页更新，路由三的 link 不会替换它。
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
连通），并注册四个 `vllm_kb_*` 工具。它默认随面板一起装（路由三的第二条 `add`、路由四的 `--all`、
路由五的第二次粘贴）；只有要单独补装时才用下面这两条：

```
node scripts/panel_install.js --spec "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
<dsh> plugin --profile <profile> add "<仓库绝对路径>/dsh-plugins/dsh-sleuth-vllm-kb"
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

## 依赖

- DSH 会话。热加载另需 `cordis_define` / `cordis_run` / `cordis_inspect_self` 工具；常驻插件包另需
  `plugin_manager` 工具；桌面版命令行另需安装目录下的 `dsh` / `dsh.cmd`（不在 PATH 上，用绝对路径；
  有的发行版不带，走插件页粘贴）；HTTP 脚本安装另需日志里有 `dsh web:` 行，或能传 `--url` / `--token`；
  插件页粘贴另需用户能操作侧栏「插件」页并刷新页面。
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
