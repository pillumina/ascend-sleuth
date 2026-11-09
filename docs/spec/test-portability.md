# 测试可移植性规范

## 1 管什么

本规范约束 `tests/` 下的 Python 测试（含 `tests/groom_fixtures.py` 这类共享夹具）。目标是同一份用例在 Windows、Linux、macOS 上给出同一结论，并且不依赖外网与本机运行时件。

判定口径是行为：新增或修改的用例在任一平台失败，按本规范找原因是缺陷，不当作环境问题放过。

为什么现在有这篇：CI 的单元测试只跑 ubuntu-latest。依赖平台默认编码、换行转换、路径分隔符或外网的用例在 Linux 上通过，合入后才在 Windows 上暴露。这类失败与业务回归在输出上不可区分，会把排查成本记到错误的对象上。

## 2 不管什么

- 业务脚本自身的跨平台实现（例如 `scripts/trace_transition.py` 的换行保留逻辑）：由脚本自己的单测覆盖。本规范只约束测试怎么写，不替代对脚本的测试。
- 面板前端（`dsh-plugins/**`）的渲染、文案与平台适配：由 `scripts/panel_render_check.js` 与 `scripts/check_panel_tokens.py` 管。
- Windows 上让 agent 发现 skill：见 [windows-setup.md](../guide/windows-setup.md)。
- 网络本身是否可达：本规范要求用例默认不等网络，不保证任何一台机器能连上 GitHub。

## 3 条目

R1–R6 是硬要求。机器检查（下称机检）覆盖的形态在 §5 表与 `scripts/check_test_portability.py` 头注里列全；每条「怎么判定」只写该条的主要判据与最常用的边界，要求句比判据宽的部分靠评审与 `unit-tests-windows`。R7 也是硬要求，但机器判不了，强度按原则十的三档标成约定（硬 / 半硬 / 约定）。

编号一旦发布不重用；删掉的条目留号并标注已废弃。

### R1 文本读写显式指定 UTF-8

**要求**：文本模式的 `open()`、`Path.read_text()`、`Path.write_text()`、`io.open()` 必须带 `encoding="utf-8"`。

**怎么判定**：`check_test_portability.py` 的 R1 报出。未指定时按本机 locale 解码，中文 Windows 上是 cp936，读写失败或内容乱码。检查器只判有没有显式指定（`encoding=None` 按没有指定处理）；值是不是 utf-8 靠评审与 `unit-tests-windows`。

**反例**：`path.write_text(text)`。

### R2 子进程输出显式指定 UTF-8

**要求**：`subprocess` 用 `text=True`（或 `universal_newlines=True`）时必须带 `encoding="utf-8"`。

**怎么判定**：检查器 R2 报出。子进程输出按本机 locale 解，断言里的中文与 `✓`/`✗` 会变成乱码或抛 `UnicodeDecodeError`。

**反例**：`subprocess.run([...], text=True, capture_output=True)`。

### R3 解释器路径用 sys.executable

**要求**：测试启动 Python 子进程时，命令的第一项用 `sys.executable`，不写 `"python3"`、`"python"` 或 `"py"`。

**怎么判定**：检查器 R3 报出。Windows 上 `python3` 可能不存在（安装器提供的是 `python.exe` 与 `py.exe`），用例会以「找不到命令」失败。

**反例**：`subprocess.run(["python3", "scripts/build_index.py"])`。

### R4 路径断言不写死分隔符

**要求**：断言输出路径时不用带 `/` 的字符串比较。用 `pathlib` 比较（`Path(输出).name`、`Path(输出) == 期望`），或先归一（`Path(输出).as_posix()`、`str(p).replace(os.sep, "/")`）再按 POSIX 形态比较。确属平台无关的写法按 §4 加豁免注释。

**怎么判定**：检查器 R4 报出 `endswith("/…")`、`startswith("/…")` 形态。Windows 的 `str(Path)` 用反斜杠，这类断言恒假。检查器只认单个字符串字面量；`assertEqual(str(p), "a/b")` 等其它比较形态靠评审。

**反例**：`self.assertTrue(last_line(proc).endswith("/v1.0"))`。

**正例**：`self.assertEqual(Path(last_line(proc)).name, "v1.0")`。

### R5 字节级夹具显式构造

**要求**：要断言换行、BOM 等字节形态时，用 `write_bytes()` 写出确定的字节。由 `write_text()` 产出的文件，不得再用 `read_bytes()` 的结果做 `replace(b"\n", b"\r\n")` 二次转换。

**怎么判定**：检查器 R5 报出。Windows 的 `write_text` 已按 CRLF 写盘，再替换会得到 `\r\r\n`，后续 `scripts/trace_transition.py` 的写入后校验失败并回滚（`E_IO 写入后校验失败，已回滚`）。检查器只判 `read_bytes()` 的同一个表达式；先赋变量再二次转换不判，靠评审。

**反例**：`path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))`。

**正例**：先归一再转 CRLF，例如 `raw = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")`，再 `path.write_bytes(raw.replace(b"\n", b"\r\n"))`。

### R6 平台专有 API 显式跳过

**要求**：`fcntl`、`pwd`、`grp`、`termios`、`msvcrt`、`winreg` 等只在单一平台存在的模块，与 `os.fork`、`os.symlink`、`os.chmod` 等语义因平台而异的调用，必须用 `@unittest.skipUnless(...)` 跳过不支持的平台，或在用例里显式分平台。

**怎么判定**：检查器 R6 报出导入与调用。模块顶层 `import fcntl` 在 Windows 上直接 ImportError，整个测试文件红。检查器只认列出的模块与 `os.fork` / `os.symlink` / `os.chmod`；`os.geteuid()` 等其它平台专有调用靠评审。

**反例**：测试文件顶部 `import fcntl`。

**正例**：`@unittest.skipUnless(os.name == "posix", "fcntl 只在 POSIX 可用")`。

### R7 不依赖外部环境

**要求**：分两条。

- 会访问本机外网络的用例默认跳过，只在环境变量 `ASCEND_SLEUTH_NETWORK_TESTS=1` 时运行；skip 理由写清为什么默认跳过。CI 的 Linux 单测 job 设该变量，Windows 单测 job 不设。
- 用例不读主检出的运行时件（`traces/`、`metrics/skill-exec-log.yaml`、真实 DSH 会话），要测就造临时夹具。用例不假设文件名大小写可区分，不使用 Windows 保留名（`CON`、`PRN`、`NUL` 等），不依赖超过 260 字符的路径。

**怎么判定**：评审，加上在无网机器（或断网）与 `git clone` 后的干净检出上各跑一遍 `python3 -m unittest discover tests`：不能挂住，且不能因为缺 `traces/`、缺 exec-log 而红。检查器不覆盖 R7。

**反例**：测试直接 `git ls-remote https://github.com/...`，内网机器上 TCP 被黑洞丢弃时挂住数十分钟；测试读取 `traces/` 下真实诊断会话。

**正例**：模块级 `NETWORK = os.environ.get("ASCEND_SLEUTH_NETWORK_TESTS") == "1"`，加 `@unittest.skipUnless(NETWORK, "需要外网：设 ASCEND_SLEUTH_NETWORK_TESTS=1 才跑")`。

## 4 有意保留的例外

- 专测平台行为的用例可以只在一个平台跑，但必须带 skip 标记与具体理由。
- 行内豁免注释 `# portability-check: allow <理由>`：该行违规确属平台无关时使用（例如 `git show` 的输出在 Windows 上也用 `/`）。理由要具体到为什么这里不会失真；空理由不算豁免。豁免只对所在行生效。
- 提示文案、文档、被测脚本输出里的 `python3 scripts/...`：那是给人复制的命令，不是测试启动的子进程，按原值保留。
- 测试数据字符串里的 `/tmp/...`：只要没有传给真实文件系统调用，不要求改写。

## 5 哪几条能机检

已进 CI：`scripts/check_test_portability.py`（job `test-portability`）只判 R1–R6 的下列形态。要求句比判据宽的部分靠评审与 `unit-tests-windows`。

| 规则 | 检查器覆盖的形态 | 检查器不覆盖（靠评审与 Windows 单测） |
|---|---|---|
| R1 | 文本 IO 调用没有 `encoding=`（含 `encoding=None`） | 指定的值不是 utf-8；`open()` 用位置参数传 encoding；`Path.open()` 这类非模块级调用 |
| R2 | `subprocess` 以 `text=True` / `universal_newlines=True` 调用但没有 `encoding=` | `text` 不是字面量 True 的调用 |
| R3 | 子进程命令首项、argv 列表首项、或带 `*args` 转发的调用参数是解释器字面量（普通数据列表与 `print("python3", *names)` 这类调用会误报，用豁免） | 经变量拼接、helper 间接传递的解释器名；`shell=True` 的整串命令 |
| R4 | `startswith` / `endswith` 的单个字符串字面量以 `/` 开头 | `assertEqual(str(p), "a/b")` 等其它字符串比较形态 |
| R5 | `read_bytes()` 同一表达式里直接 `replace(b"\n", b"\r\n")` | 先赋变量再二次转换 |
| R6 | 列出的平台专有模块导入与 `os.fork` / `os.symlink` / `os.chmod` 调用，未被 skip 装饰器或平台分支覆盖 | 其它平台专有调用（如 `os.geteuid()`）；`try/except ImportError` 降级与 monkeypatch 掉模块的写法；skip 条件方向写反（检查器只看装饰器名） |

`tests/test_subprocess_encoding.py` 已在 `scripts/` 与 `tests/` 两面钉住 R2 的编码不变量；本检查器在 `tests/` 面补 R1、R3–R6（R2 与它重复覆盖）。R7 不在机检范围。完整形态边界以检查器头注为准。

能写但没进：R7 的「网络用例必须带 skip」可以扫描模块里的 `urlopen`、`git clone` 调用，但用 monkeypatch 打桩网络调用的用例会被误报，未进 CI。

只能人审：R7 全部；上表「检查器不覆盖」列；每条豁免的理由是否成立；skip 理由是否写对。

CI 覆盖的平台是 Linux 与 Windows 两个。macOS 没有独立 job，R1–R7 在 macOS 上靠同一套规则与提交前实跑。

## 6 与相邻规范的关系

- 文本怎么写的词句层判定在 [writing-norms.md](writing-norms.md)；本规范管测试行为，两类判定各自独立。
- 提交前要跑的命令以 `.github/workflows/kb-checks.yml` 为准，本规范不复制命令清单。
- 设计依据：原则二（不变量写进结构）要求把「跨平台」写成机检与 CI；原则六（闸门硬度与错误代价匹配）要求硬门只设在机械可判处；原则十（诚实退化）要求把机检覆盖不到的项标成约定并写明。

## 7 引用

规范性引用：

- `.github/workflows/kb-checks.yml`（`test-portability`、`unit-tests-windows` 两个 job）
- `scripts/check_test_portability.py`（R1–R6 的判定实现）

资料性引用：

- [design-principles.md](design-principles.md)
- [windows-setup.md](../guide/windows-setup.md)
