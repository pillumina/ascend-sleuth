#!/usr/bin/env python3
"""doctor.py —— 本机环境体检：这台机器上哪些流程能跑、哪些会降级。

## 为什么需要

依赖缺了不在开单时报，而在任务中途以一句 traceback 出现。实测：缺 PyYAML 的机器上点「导出交接包」，
面板只回一句「导出脚本没有给出 JSON 结果」，根因在 traceback 的最后一行，读者要自己认。同类事故还有
Windows 上没有 `python3`（面板探活退到 `python` / `py -3`，挑中的解释器未必是装了包的那个）。
体检器的职责一条：**动工之前把"这台机器缺什么、缺了哪条流程不能用"说清**。

## 三条设计约束

1. **依赖清单不硬编码**。第三方包从 `scripts/**/*.py` 的 import 现算（ast + 解释器探测），
   新增一个第三方包自动被发现。写死清单会有第二份真相，且必然腐烂。
2. **只报不修**。体检器不做 `pip install`：装法是人的决定，内网机器上通常是离线 wheel，
   联网安装在这里失败会报得比原来更难读。
3. **可重复**：结论只由本机状态决定，不写数据面（`knowledge/`、`traces/`、`metrics/`）。
   唯一的写入是本机 `.local/` 下两个运行时件：settings 里的「已接受不修」由人写，
   `doctor-last.json` 记上次结论只为「与上次比」那一行。两次跑结论相同，差异行如实反映变化。

## 与相邻脚本的分工（不要在这里重实现它们）

    metrics_health.py          知识库指标的闭环判据（容量 / 新鲜度 / 可解读性）
    verify_*.py                各类内容的结构校验
    rehearse_evolve_loop.py    端到端演练，把 CI 的命令清单逐条复跑

体检器**不抄 CI 的命令清单**（权威处是 `.github/workflows/kb-checks.yml`），只在「下一步」里指出该跑哪一条。

用法：
  python3 scripts/doctor.py            # 人读五段：结论 / 能力 / 检查了什么 / 有问题 / 下一步
  python3 scripts/doctor.py --json     # 机器读（面板与脚本用）
  python3 scripts/doctor.py --root <检出>
  python3 scripts/doctor.py --no-record # 不读也不写 .local/doctor-last.json

退出码：0 = 无阻断；2 = 有阻断项；3 = 不在检出里；4 = 命令行参数不合法。
"""
import argparse
import ast
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from _cli import main_entry

SCRIPTS_DIR = Path(__file__).resolve().parent

# import 名与发行包名不同的几个。**只登记差异**，同名的不写——写全表就是第二份依赖清单。
# 名称不在表里的包按 import 名作 pip 名尝试，装法文案里写明这一层假定。
PIP_NAME = {"yaml": "pyyaml", "PIL": "pillow", "cv2": "opencv-python"}
# 显示名（只登记大小写与缩写差异；pip 名仍取 PIP_NAME）
DISPLAY = {"yaml": "PyYAML"}

# 能力 → 它要求的检查项。「哪些流程能跑」这句结论不能从 import 图推出来：它是一条接线事实
# （导出走 export_trace.py；批量导 issue 走 gh）。这一张表是本文件里唯一写死的东西。
# 检查项 id：工具是命令名（python / git / node / gh），第三方包是**模块名**（yaml，不是 pip 名 pyyaml），
# 数据面是 traces / index。表里写错 id 不会静默通过——`check_capability_table` 会报出来。
CAPABILITIES = [
    ("诊断与知识沉淀", ["python", "yaml", "git", "gh"]),
    ("导出 / 导入交接包", ["python", "yaml", "traces"]),
    ("面板 · 诊断 tab", ["python", "yaml"]),
    ("面板 · 指标 tab", ["python", "yaml"]),
    ("面板安装 / 构建 / CI 检查", ["node"]),
    ("批量导入上游 issue（GitHub）", ["python", "yaml", "gh"]),
    ("批量导入上游 issue（GitCode）", ["python", "yaml", "gitcode"]),
    ("诊断 token 与工具记账", ["node"]),
    ("沉淀队列与 PR 状态", ["python", "yaml", "git", "pr-platforms"]),
    ("知识库同步", ["python", "git", "kb-sync"]),
]

BLOCK, DEGRADE, OK = "blocked", "degraded", "ok"

# 检查项之间的真实前置：装 / 用 B 之前得先有 A。只登记「没有 A 就装不上或判不出」的关系，
# 不写「建议先修哪个」——那是「下一步」按影响面排序的事。
DEPENDS_ON = {
    "gitcode": ["node"],        # 装 GitCode CLI 走 npx
    "kb-sync": ["git"],         # 同步判定按本机已有的 git 远端 ref
    "pr-platforms": ["python"], # 清单脚本用当前解释器跑
}

# 上次结论快照：只为本机「与上次比」这一行服务，不进 git（`.local/` 已忽略）。
LAST_SCHEMA = "ascend-sleuth-doctor-last/1"
LAST_REL = Path(".local") / "doctor-last.json"
STATE_TEXT = {OK: "正常", DEGRADE: "降级", BLOCK: "阻断"}


_STDLIB_NAMES = getattr(sys, "stdlib_module_names", None)
_BUILTIN = set(sys.builtin_module_names)
_STDLIB_DIRS = tuple(str(Path(p).resolve()) for p in
                     {sysconfig.get_paths().get("stdlib"), sysconfig.get_paths().get("platstdlib")} if p)


def is_stdlib(name: str, spec) -> bool:
    """标准库判定。3.10+ 用权威名单；更老的解释器退回路径推断。

    老解释器上 spec 拿不到时判「不是标准库」：把真缺的包判成标准库会导致「无阻断项」的假绿，
    代价高于多报一个平台专属模块（那些模块在仓库里都以 try/except ImportError 导入）。
    """
    if name in _BUILTIN:
        return True
    if _STDLIB_NAMES is not None:
        return name in _STDLIB_NAMES
    if spec is None:
        return False
    if spec.origin in (None, "built-in", "frozen"):
        return True
    origin = str(Path(spec.origin).resolve())
    if "site-packages" in origin or "dist-packages" in origin:
        return False
    return origin.startswith(_STDLIB_DIRS)


def local_module_dirs():
    """本仓写着自己模块的两个地方：`scripts/` 与插件的 `dsh-plugins/*/lib/`。

    脚本的 `import` 有两类都指向本仓文件，都不该按待装包处理：`scripts/` 里的同级模块，
    以及插件 `lib/` 里的模块（`bench_sediment_queue.py` 先把 `lib` 插进 `sys.path`，
    再 `import sediment_state`）。只认 `scripts/` 时后者会被判成缺包，并给出一条
    `pip install sediment_state`——那条命令装不到东西，PyPI 上没有这个包。
    """
    dirs = [SCRIPTS_DIR]
    plugins = SCRIPTS_DIR.parent / "dsh-plugins"
    if plugins.is_dir():
        dirs += [p / "lib" for p in sorted(plugins.iterdir()) if (p / "lib").is_dir()]
    return tuple(dirs)


def local_module_names():
    """`local_module_dirs()` 里的模块名（`.py` 文件的 stem）。"""
    return {p.stem for d in local_module_dirs() for p in d.glob("*.py")}


def resolve_spec(name: str):
    """该模块在当前解释器里解析得到吗。用 find_spec 而不是 import：不执行模块、无副作用。

    `local_module_dirs()` 加进 sys.path，本仓自己的模块（`_yaml`、`kb_rev`、插件 `lib`
    里的 `sediment_state` 等）才不会误报成缺失的第三方包。
    """
    saved = list(sys.path)
    sys.path[:0] = [str(d) for d in local_module_dirs()]
    try:
        return importlib.util.find_spec(name)
    except (ImportError, ValueError, AttributeError):
        return None
    finally:
        sys.path[:] = saved


def _imports_under(nodes) -> set:
    names = set()
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                names.update(a.name.split(".")[0] for a in sub.names)
            elif isinstance(sub, ast.ImportFrom) and sub.level == 0 and sub.module:
                names.add(sub.module.split(".")[0])
    return names


def _is_platform_test(node) -> bool:
    """`if sys.platform == ...:` / `os.name` / `platform.system()` / `sys.version_info` —— 平台与版本条件。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in ("platform", "name", "system", "version_info"):
            base = sub.value
            if isinstance(base, ast.Name) and base.id in ("sys", "os", "platform"):
                return True
    return False


def conditional_imports(tree) -> set:
    """平台/版本条件里的 import → 本平台可能根本不需要它，缺席不算缺包。"""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_platform_test(node.test):
            out |= _imports_under(node.body)
    return out


def guarded_imports(tree) -> set:
    """写在 `try` 里的 import → 作者留了另一条路（`except ImportError` 与 `except Exception` 都算）。

    只在任何 try 之外 import 的才算「无条件依赖」。报成「阻断」会让体检器自己制造假红：
    平台专属模块与「有就快一点、没有就走慢路」的可选包都写在 try 里。
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.handlers:
            out |= _imports_under(node.body)
    return out


def module_importers():
    """扫本仓脚本的 import → {模块名: {"files": [...], "hard": {文件名}}}。

    hard = 无条件 import 它的文件；files 里其余的是在 try/except 或平台条件里用的（缺席时脚本自己退化）。
    只收非标准库、非本仓模块（本仓模块的目录见 `local_module_dirs()`）。
    """
    local = local_module_names()
    out = {}
    for p in sorted(SCRIPTS_DIR.glob("**/*.py")):
        if "__pycache__" in p.parts or p.name == "doctor.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        soft = guarded_imports(tree) | conditional_imports(tree)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        for name in names:
            if name in local:
                continue
            if is_stdlib(name, resolve_spec(name)):
                continue
            row = out.setdefault(name, {"files": [], "hard": set()})
            if p.name not in row["files"]:
                row["files"].append(p.name)
            if name not in soft:
                row["hard"].add(p.name)
    return out


def package_version(name: str):
    try:
        return importlib.metadata.version(PIP_NAME.get(name, name))
    except importlib.metadata.PackageNotFoundError:
        return ""


UNKNOWN_VERSION = "已装（版本未知）"


def tool_version(cmd, args=("--version",)):
    """外部命令 → 一行版本串；命令不存在返回 None。

    命令在、`--version` 不认（如 GitCode CLI 只认 `version` 子命令）时返回 UNKNOWN_VERSION：
    「问不到版本」不等于「没装」，把报错首行当版本号会让证据段出现「Error: unknown flag」这种句子。
    """
    exe = shutil.which(cmd)
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_VERSION
    line = (r.stdout or r.stderr or "").strip().splitlines()
    if r.returncode != 0 or not line:
        return UNKNOWN_VERSION
    return line[0].strip()


def check_python():
    v = ".".join(str(x) for x in sys.version_info[:3])
    state = OK if sys.version_info >= (3, 10) else DEGRADE
    note = f"体检用的解释器：{sys.executable}"
    if state != OK:
        note += "；3.10 以下没有标准库名单，依赖判定只能按路径推断，可能多报"
    if sys.platform.startswith("win"):
        note += "；面板按 python3 → python → py -3 的顺序挑，挑中的未必是这一个——点面板报缺依赖时先对一下"
    return {"id": "python", "label": "Python", "kind": "tool", "state": state, "detail": v, "note": note,
            "fix": "" if state == OK else "装 Python 3.10 或更高（CI 在 3.11 上验证）"}


def check_third_party():
    rows = []
    found = module_importers()
    for name, info in sorted(found.items(), key=lambda kv: (-len(kv[1]["hard"] or kv[1]["files"]), kv[0])):
        label = DISPLAY.get(name, name)
        spec = resolve_spec(name)
        if spec is not None:
            detail = f"{package_version(name) or '已装'}（{len(info['files'])} 个脚本引用"
            if name == "yaml":
                detail += "，C 加速" + ("可用）" if _has_csafe() else "不可用，只是慢）")
            else:
                detail += "）"
            rows.append({"id": name, "label": label, "kind": "package", "state": OK,
                         "detail": detail, "fix": ""})
            continue
        pip_name = PIP_NAME.get(name, name)
        fix = f"{sys.executable} -m pip install {pip_name}"
        fix_note = (f"pip 名与 import 名不同时按发行包名装；"
                    f"内网离线：{sys.executable} -m pip install --no-index --find-links <wheel 目录> {pip_name}")
        hard = sorted(info["hard"])
        if hard:
            rows.append({"id": name, "label": label, "kind": "package", "state": BLOCK,
                         "detail": f"未安装；{len(hard)} 个脚本无条件 import 它（如 {'、'.join(hard[:3])}）",
                         "note": "缺它时那些脚本在 import 阶段就退出，不是跑到一半才失败",
                         "fix": fix, "fix_note": fix_note})
        else:
            files = sorted(info["files"])
            rows.append({"id": name, "label": label, "kind": "package", "state": DEGRADE,
                         "detail": (f"未安装；{len(files)} 个脚本在 try/except 或平台条件里用它"
                                    f"（{'、'.join(files[:2])}）" if files else "未安装"),
                         "note": "缺席时那些脚本自己退化，不会崩",
                         "fix": fix, "fix_note": fix_note})
    return rows


def _has_csafe():
    """PyYAML 的 C 加速是否可用。不可用只是慢（`_yaml.py` 会退回纯 Python 后端）。"""
    saved = list(sys.path)
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import yaml  # noqa: F401  —— 只在确认 yaml 可解析后调用
        return hasattr(yaml, "CSafeLoader")
    except Exception:
        return False
    finally:
        sys.path[:] = saved


def check_git(root: Path):
    version = tool_version("git")
    if version is None:
        return {"id": "git", "label": "git", "kind": "tool", "state": DEGRADE, "detail": "未安装",
                "note": "缺了不崩：知识库版本退化成 unknown，traces/ 等运行时件退回本检出",
                "fix": "装 git（检出隔离与 PR 门禁都依赖它）"}
    if not (root / ".git").exists():
        return {"id": "git", "label": "git", "kind": "tool", "state": BLOCK,
                "detail": f"{version}；{root} 不是 git 检出",
                "note": "脚本里的路径都按检出根解析",
                "fix": f"在 ascend-sleuth 检出根目录运行（当前 root={root}）"}
    return {"id": "git", "label": "git", "kind": "tool", "state": OK, "detail": version, "fix": ""}


def check_node():
    version = tool_version("node")
    if version:
        return {"id": "node", "label": "Node.js", "kind": "tool", "state": OK, "detail": version, "fix": ""}
    return {"id": "node", "label": "Node.js", "kind": "tool", "state": DEGRADE, "detail": "未安装",
            "note": "诊断与知识沉淀不需要它；面板安装/构建、CI 检查、token 记账需要",
            "fix": "装 Node.js",
            "fix_note": "面板也可改走插件页粘贴路径安装，那条不需要 node"}


def check_gh():
    version = tool_version("gh")
    if version:
        return {"id": "gh", "label": "gh", "kind": "tool", "state": OK, "detail": version,
                "note": "批量导 issue 还要登录：gh auth status"}
    return {"id": "gh", "label": "gh", "kind": "tool", "state": DEGRADE, "detail": "未安装",
            "note": "只有批量导入 issue 与诊断时的上游修复核查用它；缺了这两处如实说明不可查证；"
                    "装完还要登录（gh auth login），登录必须由人在交互终端完成",
            "fix": "按平台装 gh",
            "fix_kind": "install-cli", "fix_auto": True}


GITCODE_INSTALL = "npx -y atomgit-cli@latest install"
GITCODE_LOGIN = "gitcode auth login --web"


def check_gitcode():
    """GitCode 通道：issue 摄取与上游核查的第二条来源（GitHub 之外）。

    三态按认证来源分：环境 token（GC_TOKEN / GITCODE_TOKEN）→ 直接可用；
    CLI 已装且 `auth status` 通过 → 可用；CLI 未装 / 未登录 → 降级，并给安装或
    网页登录命令。登录必须由人在交互终端完成（`--web` 会打开建 token 页面，
    仍需在终端粘贴一次），体检器不代做、不读 token。
    """
    env_source = ""
    for env_name in ("GC_TOKEN", "GITCODE_TOKEN"):
        if (os.environ.get(env_name) or "").strip():
            env_source = env_name
            break
    bin_name = ""
    version = ""
    for candidate in ("gitcode", "gc"):
        version = tool_version(candidate)
        if version:
            bin_name = candidate
            break
    if not bin_name:
        note = "GitCode 侧 issue 摄取走它；缺了只能人工查网页"
        if env_source:
            note += f"；环境 token（{env_source}）已设置，但摄取脚本仍要 CLI 作 API 入口"
        return {"id": "gitcode", "label": "GitCode CLI", "kind": "tool", "state": DEGRADE,
                "detail": "未安装" + (f"（{env_source} 已设置，但缺 CLI）" if env_source else ""),
                "note": note,
                "fix": GITCODE_INSTALL,
                "fix_kind": "install-cli", "fix_auto": True}
    try:
        proc = subprocess.run([bin_name, "auth", "status", "--json"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=10)
    except Exception as exc:  # noqa: BLE001 - 体检器把异常折成一行原因
        return {"id": "gitcode", "label": "GitCode CLI", "kind": "tool", "state": DEGRADE,
                "detail": f"{version}；登录状态读不出来（{type(exc).__name__}）",
                "fix": GITCODE_LOGIN, "fix_kind": "login-web", "fix_auto": False}
    if proc.returncode == 0:
        source = ""
        try:
            doc = json.loads(proc.stdout.strip() or "{}")
            source = str(doc.get("source") or doc.get("token_source") or "")
        except Exception:
            source = ""
        return {"id": "gitcode", "label": "GitCode CLI", "kind": "tool", "state": OK,
                "detail": version + (f"；登录态来自 {source}" if source else ""),
                "note": "issue 摄取可用；上游自动查证仍只支持 GitHub，GitCode 的上游要用 CLI 人工核对"}
    return {"id": "gitcode", "label": "GitCode CLI", "kind": "tool", "state": DEGRADE,
            "detail": f"{version}；未登录",
            "note": "`--web` 会打开建 token 页面，仍需在交互终端粘贴一次；不要贴到对话里",
            "fix": GITCODE_LOGIN, "fix_kind": "login-web", "fix_auto": False}


def check_traces(root: Path):
    """traces/ 是交接包与面板的数据源。只验「看得到」与「解析得出」两件事。"""
    try:
        from exec_log_path import resolve_traces
        traces = resolve_traces(root)
    except Exception:
        traces = root / "traces"
    if not traces.is_dir():
        return {"id": "traces", "label": "traces/", "kind": "data", "state": OK,
                "detail": "还没有诊断记录（全新检出的正常状态）", "fix": ""}
    files = sorted(traces.glob("*.yaml"))
    try:
        from _yaml import load_text
    except Exception:
        return {"id": "traces", "label": "traces/", "kind": "data", "state": DEGRADE,
                "detail": f"{len(files)} 份；未校验能否解析（缺 PyYAML）",
                "fix": "先修 PyYAML，再重跑本命令复验 traces 能否解析"}
    bad = []
    for p in files:
        try:
            if not isinstance(load_text(p.read_text(encoding="utf-8")), dict):
                bad.append(p.name)
        except Exception:
            bad.append(p.name)
    if bad:
        return {"id": "traces", "label": "traces/", "kind": "data", "state": BLOCK,
                "detail": f"{len(files)} 份，其中 {len(bad)} 份解析不出（{'、'.join(bad[:3])}）",
                "note": "导出交接包要解析它们",
                "fix": "修那几份 trace 的 YAML（导出交接包与面板展开都读它们）"}
    return {"id": "traces", "label": "traces/", "kind": "data", "state": OK,
            "detail": f"{len(files)} 份均可解析", "fix": ""}


def check_index(root: Path):
    """索引是面板列表与候选路由的读入口。缺了只是要重建，不是环境问题。"""
    if (root / "knowledge" / "_index.yaml").is_file():
        return {"id": "index", "label": "知识库索引", "kind": "data", "state": OK,
                "detail": "knowledge/_index.yaml 在", "fix": ""}
    return {"id": "index", "label": "知识库索引", "kind": "data", "state": DEGRADE,
            "detail": "knowledge/_index.yaml 不在", "fix": "python3 scripts/build_index.py"}


def check_evolution(root: Path):
    """部署级演进角色（sleuth.config.yaml）。这是策略声明，不是环境缺陷。

    为什么放进体检：内网 fork 的预期形态是 `signal-only`（只记信号、不跑实验）。不显示时，
    用户在收尾报告里只看到"没有卡"，会以为演进坏了；显示后，"按声明不跑实验"与"演进失败"
    能分开。声明写坏只挡演进流程，不挡诊断与沉淀，所以记降级而不是阻断。
    """
    try:
        from evolve_mode import read_role, ModeError
    except Exception as e:
        return {"id": "evolution", "label": "演进角色", "kind": "policy", "state": DEGRADE,
                "detail": f"读不出声明（{e.__class__.__name__}）",
                "fix": "确认 scripts/evolve_mode.py 在（缺文件时收尾读不到部署角色）"}
    try:
        role, source = read_role(root)
    except ModeError as e:
        return {"id": "evolution", "label": "演进角色", "kind": "policy", "state": DEGRADE,
                "detail": f"声明写坏：{e}",
                "note": "收尾检查会停下来问人，不会自己挑一档跑",
                "fix": "改 sleuth.config.yaml 的 evolution.role 为 maintainer / signal-only / off 之一"}
    meaning = {
        "maintainer": "维护者部署：信号分诊后可跑受控实验；EV 卡只作高风险授权",
        "signal-only": "只记信号，不跑实验（本地/内网 fork）",
        "off": "不做收尾检查",
    }[role]
    return {"id": "evolution", "label": "演进角色", "kind": "policy", "state": OK,
            "detail": f"{role} —— {meaning}（来源：{source}）", "fix": ""}


def _platform_reason(reason: str) -> str:
    """适配器给的英文式子原因 → 一行短中文。认不出的原样带出，不猜。"""
    r = (reason or "").strip()
    for prefix, short in (("未配置 token 环境变量：", "未配置 "), ("缺少命令：", "缺 ")):
        if r.startswith(prefix):
            return short + r[len(prefix):]
    return r or "不可用"


def check_pr_platforms(root):
    """PR 平台适配器清单：只读清单与环境变量，不联网、不装依赖。

    体检器不代装（见文件头三条约束）；这里只回答「这台机器上有几个平台能查 PR 状态」。
    清单由 scripts/pr_status.py --list-platforms 打印，doctor 不写平台特判。
    """
    script = Path(root) / "scripts" / "pr_status.py"
    if not script.is_file():
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": DEGRADE,
                "detail": "缺少 scripts/pr_status.py",
                "fix": "把插件更新到带沉淀队列的版本",
                "fix_note": "或先跳过 PR 状态查询，用「标记已合入」手动确认"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--root", str(root), "--list-platforms", "--json"],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001 - 体检器把异常折成一行原因
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": DEGRADE,
                "detail": "清单脚本跑不起来：" + str(exc), "fix": "python3 scripts/pr_status.py --list-platforms"}
    try:
        doc = json.loads(proc.stdout.strip() or "{}")
    except Exception:  # noqa: BLE001
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": DEGRADE,
                "detail": "清单脚本没有给出 JSON", "fix": "python3 scripts/pr_status.py --list-platforms"}
    if doc.get("ok") is False:
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": DEGRADE,
                "detail": str((doc.get("error") or {}).get("message") or "清单不可用"),
                "fix": "python3 scripts/pr_status.py --list-platforms"}
    platforms = doc.get("platforms") or []
    # 已选目标平台优先：GitHub 可用不等于 GitCode 目标可用。
    target_platform = ""
    try:
        ledger_proc = subprocess.run(
            [sys.executable, str(script), "--root", str(root), "--json"],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        ledger = json.loads(ledger_proc.stdout.strip() or "{}")
        target = ((ledger.get("ledger") or {}).get("target") or {})
        target_platform = str(target.get("platform") or "")
    except Exception:  # noqa: BLE001 - 读记录失败不阻断清单检查
        target_platform = ""
    if target_platform:
        picked = next((p for p in platforms if str(p.get("id")) == target_platform), None)
        if picked is None:
            return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": DEGRADE,
                    "detail": "目标平台 " + target_platform + " 没有适配器",
                    "fix": "在 scripts/platforms/ 加适配器，或换一个目标远端"}
        if not picked.get("available"):
            return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": DEGRADE,
                    "detail": "目标平台 " + str(picked.get("name") or target_platform) + " 不可用："
                              + str(picked.get("reason") or "缺 token/命令"),
                    "fix": str(picked.get("install_hint") or "按适配器说明配 token/命令")}
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": OK,
                "detail": "目标平台 " + str(picked.get("name") or target_platform) + " 可用",
                "note": "清单来自 scripts/platforms/；只读，不联网"}
    ok = [p for p in platforms if p.get("available")]
    bad = [p for p in platforms if not p.get("available")]
    if not ok:
        reason = "；".join(str(p.get("reason") or p.get("id")) for p in bad[:3]) or "没有平台清单"
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": DEGRADE,
                "detail": "没有可用的平台：" + reason,
                "fix": "按适配器的 install_hint 配 token/命令",
                "fix_note": "或先手动确认 PR 状态"}
    detail = "可用 " + "、".join(str(p.get("name") or p.get("id")) for p in ok)
    if bad:
        detail += "；不可用 " + "、".join(
            str(p.get("id")) + f"（{_platform_reason(str(p.get('reason') or ''))}）" for p in bad[:3])
    return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "data", "state": OK, "detail": detail,
            "note": "清单来自 scripts/platforms/；只读，不联网"}


def check_kb_sync(root: Path):
    """知识库同步：只读本机状态，不联网。

    判三件事：部署是否声明离线、配置是否可用、本机远端 ref 落后多少。上次 fetch 的失败
    从 `.local/kb-sync-state.json` 读——它决定下一次开单会不会直接跳过联网。
    """
    try:
        # settings 的解析在 `_settings`；同步状态的读写与渲染在 `_kb_sync`。
        import _kb_sync
        import _settings
    except Exception as exc:  # noqa: BLE001 - 体检器把缺依赖折成一行原因
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": DEGRADE,
                "detail": f"读不出同步配置（{type(exc).__name__}: {exc}）",
                "fix": "python3 scripts/kb_sync.py --show"}
    try:
        mode = _kb_sync.deployment_sync_mode(root)
        settings, config, problem = _settings.load_settings(root)
        config_sync = settings.get("sync") or {}
        state = _kb_sync.load_state(root)
    except Exception as exc:  # noqa: BLE001
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": DEGRADE,
                "detail": f"读不出同步配置（{type(exc).__name__}: {exc}）",
                "fix": "python3 scripts/kb_sync.py --show"}

    if mode == "offline":
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": OK,
                "detail": "offline —— sleuth.config.yaml 声明 sync.mode: offline，不联网",
                "note": "trace_begin / kb_drift 不会 fetch；trace 记 kb_sync: off",
                "fix": ""}
    if not config_sync.get("enabled", True):
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": OK,
                "detail": "已关闭（.local/settings.json 的 sync.enabled = false）",
                "note": "打开：python3 scripts/pr_status.py --set-sync --enable",
                "fix": ""}
    remote = str(config_sync.get("remote") or "origin")
    branch = str(config_sync.get("branch") or "main")
    remote_ref = f"{remote}/{branch}"
    identity = settings.get("identity") or {}
    try:
        snap = _kb_sync.local_snapshot(root, remote, branch, identity=identity)
    except Exception as exc:  # noqa: BLE001
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": DEGRADE,
                "detail": f"读不出本机 {remote_ref}（{type(exc).__name__}: {exc}）",
                "fix": "python3 scripts/kb_sync.py --show"}

    if not snap.get("ok") and snap.get("reason") == "not-a-repo":
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": DEGRADE,
                "detail": f"{root} 不是 git 检出，无法算落后",
                "fix": "python3 scripts/kb_sync.py --show"}

    behind = snap.get("behind")
    degraded = False
    identity_remote = str(snap.get("identity_remote") or "origin")
    identity_name = identity_remote if snap.get("identity_explicit") \
        else f"{identity_remote}（默认）"
    if behind == "unknown":
        detail = f"本机没有 {remote_ref} ref，算不出落后"
        degraded = True
    elif isinstance(behind, int) and behind > 0:
        detail = f"落后 {remote_ref} {behind} 个提交"
        degraded = True
    else:
        detail = f"与 {remote_ref} 一致"
    detail += f"；归属仓 {identity_name}"
    if snap.get("identity_explicit") and not snap.get("identity_resolved"):
        detail += "（解析不到）"
        degraded = True
    elif snap.get("same_repo") is False:
        detail += "；同步源与归属仓不同源"
        degraded = True

    last_ok = str(state.get("last_ok_at") or "")
    last_reason = str(state.get("reason") or "")
    if last_reason:
        attempted = str(state.get("attempted_at") or "")
        detail += f"；上次 fetch 失败：{_kb_sync.fetch_reason_text(last_reason)}"
        if attempted:
            detail += f"（{attempted}）"
        degraded = True
    detail += f"；上次核对：{last_ok or '从未'}"
    if config == "default":
        if problem:
            detail += f"；配置读不出，按默认值算：{problem}"
            degraded = True
        else:
            detail += "；未配置 .local/settings.json，按默认值算"

    note = "只读，不联网；落后数按本机已有的远端 ref 算"
    return {"id": "kb-sync", "label": "知识库同步", "kind": "data",
            "state": DEGRADE if degraded else OK,
            "detail": detail, "note": note,
            "fix": "python3 scripts/kb_sync.py --show" if degraded else ""}


def accepted_checks(root: Path) -> set:
    """`.local/settings.json` 的 `doctor.accept` → 已接受不修的检查项 id。

    只对降级项生效：阻断项意味着脚本在 import 阶段就退出，把它标成已接受等于让结论说谎。
    配置读不出或没写这一段时返回空集——配置问题不该让体检失败。
    """
    try:
        from _settings import load_settings, settings_path
        if not settings_path(root).is_file():
            return set()
        data, _config, _problem = load_settings(root)
    except Exception:  # noqa: BLE001 - 读配置失败按「没接受过任何项」算
        return set()
    section = data.get("doctor") if isinstance(data, dict) else None
    raw = section.get("accept") if isinstance(section, dict) else None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return set()
    return {str(x).strip() for x in raw if str(x).strip()}


def _last_path(root: Path) -> Path:
    try:
        from _settings import repo_root
        base = repo_root(root)
    except Exception:  # noqa: BLE001 - 拿不到主检出就锚在当前 root
        base = Path(root)
    return Path(base) / LAST_REL


def read_last(root: Path):
    """上一次体检的结论快照；没有或读不出返回 None。"""
    try:
        doc = json.loads(_last_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("checks"), dict):
        return None
    return doc


def write_last(root: Path, rep) -> None:
    """记下本次结论。写不了（只读部署、CI）就跳过：记录失败不该让体检失败。"""
    doc = {"schema": LAST_SCHEMA, "at": _now_iso(), "python": rep["python"],
           "checks": {c["id"]: c["state"] for c in rep["checks"]}}
    path = _last_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def diff_last(rep, last):
    """本次结论与上次快照的差异 → 渲染用的一行素材。"""
    if not last:
        return {"first": True, "at": "", "changes": []}
    now = {c["id"]: c for c in rep["checks"]}
    prev = last.get("checks") or {}
    labels = {c["id"]: c.get("label") or c["id"] for c in rep["checks"]}
    changes = []
    for cid in list(now) + [i for i in prev if i not in now]:
        was, is_ = prev.get(cid), now.get(cid, {}).get("state")
        if was == is_:
            continue
        changes.append({"id": cid, "label": labels.get(cid, cid),
                        "was": was or "（上次未检查）", "now": is_ or "（本次未检查）"})
    return {"first": False, "at": str(last.get("at") or ""), "changes": changes}


def ordered_bad(checks):
    """待修项按依赖排序：被依赖项在前（装 gitcode 要先有 node）。同层保持检查顺序。"""
    bad = {c["id"] for c in checks if c["state"] != OK}
    by_id = {c["id"]: c for c in checks}
    order, seen = [], set()

    def visit(cid):
        if cid in seen:
            return
        seen.add(cid)
        for dep in DEPENDS_ON.get(cid, []):
            if dep in bad:
                visit(dep)
        order.append(cid)

    # 阻断优先（结论说「先修阻断项」）；降级项再按影响面排——拖垮的能力多的排前面
    degraded = sorted([x for x in checks if x["state"] == DEGRADE],
                      key=lambda x: -len(x.get("impact") or []))
    for c in [x for x in checks if x["state"] == BLOCK] + degraded:
        if c["id"] in bad:
            visit(c["id"])
    return [by_id[i] for i in order]


def check_capability_table(checks):
    """能力表引用的 id 必须都存在于检查项里。

    为什么值得单列一项：能力表按 id 取 state，写错一个 id 不会报错，只会让那条流程永远显示「能跑」——
    假绿比缺项更难发现。
    """
    known = {c["id"] for c in checks}
    unknown = sorted({n for _, needs in CAPABILITIES for n in needs if n not in known})
    if not unknown:
        return {"id": "capability-table", "label": "能力表自检", "kind": "data", "state": OK,
                "detail": f"引用的 {len(known)} 个检查项都在", "fix": ""}
    return {"id": "capability-table", "label": "能力表自检", "kind": "data", "state": BLOCK,
            "detail": f"引用了不存在的检查项 id：{'、'.join(unknown)}",
            "note": "拼错的 id 取不到 state，对应流程会静默显示「能跑」",
            "fix": "修 scripts/doctor.py 的 CAPABILITIES"}


def apply_local_policy(checks, accepted):
    """把本机配置落到检查项上：依赖关系、已接受项。

    只有降级项能被接受：阻断项意味着脚本在 import 阶段就退出，标成已接受等于让结论说谎。
    """
    accepted = set(accepted or ())
    for c in checks:
        c["depends_on"] = list(DEPENDS_ON.get(c["id"], []))
        c["accepted"] = bool(c["state"] == DEGRADE and c["id"] in accepted)
    return checks


def build_report(root: Path, *, record: bool = True):
    checks = [check_python()]
    checks += check_third_party()
    checks += [check_git(root), check_node(), check_gh(), check_gitcode(), check_pr_platforms(root),
               check_kb_sync(root), check_traces(root), check_index(root), check_evolution(root)]
    checks.append(check_capability_table(checks))

    apply_local_policy(checks, accepted_checks(root))

    by_id = {c["id"]: c for c in checks}
    caps = []
    for name, needs in CAPABILITIES:
        miss = [n for n in needs if by_id.get(n, {}).get("state") == BLOCK]
        weak = [n for n in needs if by_id.get(n, {}).get("state") == DEGRADE]
        caps.append({"name": name, "needs": needs,
                     "state": "no" if miss else ("partial" if weak else "yes"), "missing": miss,
                     "accepted": bool(weak) and all(by_id[n].get("accepted") for n in weak)})
    # 没有任何能力引用的阻断项（新出现的第三方包、能力表自检失败）：单独列一条，否则结论会一边报
    # 「N 项阻断」一边说七条流程都能跑
    covered = {n for _, needs in CAPABILITIES for n in needs}
    orphan = [c["id"] for c in checks if c["state"] == BLOCK and c["id"] not in covered]
    if orphan:
        caps.append({"name": "其余脚本化流程", "needs": orphan, "state": "no", "missing": orphan,
                     "accepted": False})
    for c in checks:   # 能力反查结果挂到检查项上：「下一步」排序与「影响：」行共用一份
        c["impact"] = _capability_impact({"capabilities": caps}, c["id"])
    blocked = [c for c in checks if c["state"] == BLOCK]
    degraded = [c for c in checks if c["state"] == DEGRADE]
    todo = [c for c in ordered_bad(checks) if not c.get("accepted")]
    actions = []
    for c in todo:
        if c.get("fix") and c["fix"] not in actions:
            actions.append(c["fix"])
    last = read_last(root) if record else None
    rep = {"ok": not blocked, "root": str(root), "python": sys.executable,
           "blocked": len(blocked), "degraded": len(degraded),
           "accepted": len([c for c in degraded if c.get("accepted")]),
           "checks": checks, "capabilities": caps, "next_actions": actions,
           "record_enabled": record,
           "previous": diff_last({"checks": checks}, last)}
    if record:
        write_last(root, rep)
    return rep


KIND_TEXT = {"package": "包", "tool": "工具", "data": "数据面", "policy": "部署声明"}


def _state_of(rep, check_id: str) -> str:
    for c in rep["checks"]:
        if c["id"] == check_id:
            return c["state"]
    return ""


def _check_label(rep, check_id: str) -> str:
    for c in rep["checks"]:
        if c["id"] == check_id:
            return c.get("label") or check_id
    return check_id


def _capability_impact(rep, check_id: str):
    """这条检查项坏掉时哪些能力跟着降级。反查 CAPABILITIES，不另写一份对照表。"""
    return [c["name"] for c in rep["capabilities"] if check_id in (c.get("needs") or [])]


def _previous_line(rep) -> str:
    """「与上次比」一行：结论级差异，不重复证据段。"""
    prev = rep.get("previous") or {}
    if not rep.get("record_enabled", True):
        return "与上次比：未读快照（--no-record），本次结论不记基线。"
    if prev.get("first"):
        return "与上次比：本机第一次体检，本次结论记为基线。"
    changes = prev.get("changes") or []
    if not changes:
        at = prev.get("at") or "上次"
        return f"与上次比：结论一致（{at}）。"
    parts = [f"{c['label']} {STATE_TEXT.get(c['was'], c['was'])}→{STATE_TEXT.get(c['now'], c['now'])}"
             for c in changes[:4]]
    more = f" 等 {len(changes)} 项" if len(changes) > 4 else ""
    return f"与上次比：{len(changes)} 项变化——" + "；".join(parts) + more


def _ok_line(c) -> str:
    """正常项一行：detail 已以名字开头时不再重复（`git version 2.50.1`，不是 `git git version …`）。"""
    label, detail = c.get("label") or c["id"], c.get("detail") or ""
    if not detail:
        return label
    if detail.lower().startswith(label.lower()):
        return detail
    return f"{label} {detail}"


def render(rep) -> str:
    total = len(rep["checks"])
    blocked, degraded = rep["blocked"], rep["degraded"]
    okn = total - blocked - degraded
    accepted = int(rep.get("accepted") or 0)
    accepted_text = ""
    if degraded and accepted:
        accepted_text = f"（其中 {accepted} 项已接受不修）"
    if blocked:
        head = (f"结论：{blocked} 项阻断、{degraded} 项降级{accepted_text}——"
                f"{total} 项检查里 {okn} 项正常，先修阻断项再重跑本命令。")
    else:
        head = f"结论：无阻断项，{degraded} 项降级{accepted_text}——{total} 项检查里 {okn} 项正常。"
    lines = [head, _previous_line(rep), ""]

    caps = rep["capabilities"]
    yes = sum(1 for c in caps if c["state"] == "yes")
    partial = sum(1 for c in caps if c["state"] == "partial")
    no = sum(1 for c in caps if c["state"] == "no")
    lines.append(f"能力（{len(caps)} 项：{yes} 可用、{partial} 降级、{no} 不可用）")
    for c in caps:
        if c["state"] == "yes":
            continue
        missing = [n for n in (c.get("missing") or []) if n]
        weak = [n for n in (c.get("needs") or [])
                if n not in missing and _state_of(rep, n) == DEGRADE]
        lack, self_bad = [], False
        for n in missing + weak:
            label = _check_label(rep, n)
            if label == c["name"]:   # 检查项与能力同名（如「知识库同步」）：说缺自己会读成 bug
                self_bad = True
                continue
            lack.append(label)
        mark = "✘" if c["state"] == "no" else "!"
        tail = f"　缺：{'、'.join(lack)}" if lack else ""
        if self_bad:
            tail += "（该能力自身的检查项也降级）"
        if c.get("accepted"):
            tail += "（已接受）"
        lines.append(f"  {mark} {c['name']}" + tail)
    ok_caps = [c["name"] for c in caps if c["state"] == "yes"]
    if ok_caps:
        lines.append("  ✔ " + "、".join(ok_caps))

    lines += ["", f"检查了什么（{total} 项：{okn} 正常、{degraded} 降级、{blocked} 阻断）"]
    ok_checks = [c for c in rep["checks"] if c["state"] == OK]
    if not ok_checks:
        lines.append("  正常：无")
    groups = [("tool", "工具"), ("package", "包"), ("data", "仓库与数据"), ("policy", "部署声明")]
    for kind, title in groups:
        group = [c for c in ok_checks if (c.get("kind") or "tool") == kind]
        if not group:
            continue
        if kind in ("data", "policy"):
            lines.append(f"  {title}：")
            lines += [f"    {_ok_line(c)}" for c in group]
        else:
            lines.append(f"  {title}：" + " · ".join(_ok_line(c) for c in group))

    bad_all = [c for c in rep["checks"] if c["state"] != OK]
    bad = [c for c in ordered_bad(rep["checks"]) if not c.get("accepted")]
    bad += [c for c in bad_all if c.get("accepted")]
    if bad:
        lines += ["", f"有问题（{len(bad)} 项）："]
        for c in bad:
            tag = "阻断" if c["state"] == BLOCK else "降级"
            kind = KIND_TEXT.get(c.get("kind") or "", "")
            lines.append(f"  [{tag}] {c['label']}" + (f"（{kind}）" if kind else "") + "：" + (c.get("detail") or ""))
            if c.get("accepted"):
                lines.append("         状态：已接受不修（.local/settings.json 的 doctor.accept），不列下一步")
            waiting = [d for d in (c.get("depends_on") or []) if _state_of(rep, d) != OK]
            if waiting:
                lines.append("         依赖：先修 " + "、".join(_check_label(rep, d) for d in waiting))
            impact = c.get("impact") or _capability_impact(rep, c["id"])
            if impact:
                lines.append("         影响：" + "、".join(impact))
            else:
                lines.append("         影响：没有已列能力直接依赖它，只降级上面点名的脚本")
            if c.get("note"):
                lines.append(f"         后果：{c['note']}")
            if c.get("fix"):
                lines.append(f"         修：{c['fix']}")
            if c.get("fix_note"):
                lines.append(f"         备注：{c['fix_note']}")

    lines += ["", "下一步（按影响面排序，一次修一项，修完重跑 python3 scripts/doctor.py）："]
    if rep["next_actions"]:
        lines += [f"  {i}. {a}" for i, a in enumerate(rep["next_actions"], 1)]
    else:
        accepted = int(rep.get("accepted") or 0)
        if accepted:
            lead = f"  没有待修项（{accepted} 项已接受不修）。"
        else:
            lead = "  环境齐了。"
        lines.append(lead + "验内容门禁跑 python3 scripts/rehearse_evolve_loop.py（逐条复跑 CI 命令）；"
                     "日常提交前按 .github/workflows/kb-checks.yml 的 run: 逐条跑。")
    lines += ["", f"体检用的解释器：{rep['python']}",
              "（换解释器就换一份结论；点面板报缺依赖时，先确认它用的是不是这一个）"]
    return "\n".join(lines)


class _Parser(argparse.ArgumentParser):
    """参数错误用 4，与「有阻断项」的 2 分开——面板和脚本要能区分「环境有问题」与「命令写错了」。"""

    def error(self, message):
        print(f"doctor: {message}", file=sys.stderr)
        raise SystemExit(4)


def main() -> int:
    ap = _Parser(description="本机环境体检：哪些流程能跑、哪些会降级")
    ap.add_argument("--root", default=None,
                    help="仓库根目录（默认：本脚本上两级）。只改数据面基准（traces / 索引 / 检出判定）；"
                         "依赖扫描始终跟本脚本所在的 scripts/")
    ap.add_argument("--json", action="store_true", help="只吐 JSON（面板/脚本用）")
    ap.add_argument("--no-record", action="store_true",
                    help="不读也不写 .local/doctor-last.json（不给「与上次比」、不改基线）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else SCRIPTS_DIR.parent
    if not (root / "scripts").is_dir():
        msg = f"{root} 不像 ascend-sleuth 检出（没有 scripts/）"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        else:
            print(f"doctor: {msg}", file=sys.stderr)
        return 3

    rep = build_report(root, record=not args.no_record)
    print(json.dumps(rep, ensure_ascii=False) if args.json else render(rep))
    return 0 if rep["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main_entry(main))
