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
3. **可重复**：不写数据面、不缓存。同一台机器两次跑结论一致——"反复发起检测"的意义在这条。
   运行时 Python 会生成 `scripts/__pycache__/`，那是解释器行为，不在数据面里。

## 与相邻脚本的分工（不要在这里重实现它们）

    metrics_health.py          知识库指标的闭环判据（容量 / 新鲜度 / 可解读性）
    verify_*.py                各类内容的结构校验
    rehearse_evolve_loop.py    端到端演练，把 CI 的命令清单逐条复跑

体检器**不抄 CI 的命令清单**（权威处是 `.github/workflows/kb-checks.yml`），只在「下一步」里指出该跑哪一条。

用法：
  python3 scripts/doctor.py            # 人读三段：结论 / 证据 / 下一步
  python3 scripts/doctor.py --json     # 机器读（面板与脚本用）
  python3 scripts/doctor.py --root <检出>

退出码：0 = 无阻断；2 = 有阻断项；3 = 不在检出里；4 = 命令行参数不合法。
"""
import argparse
import ast
import importlib.metadata
import importlib.util
import json
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from _stdio import pin_utf8_stdio

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
    ("面板 · 指标 tab 的体检", ["python", "yaml"]),
    ("面板安装 / 构建 / CI 检查", ["node"]),
    ("批量导入上游 issue", ["python", "yaml", "gh"]),
    ("诊断 token 与工具记账", ["node"]),
    ("沉淀队列与 PR 状态", ["python", "yaml", "git", "pr-platforms"]),
    ("知识库同步", ["python", "git", "kb-sync"]),
]

BLOCK, DEGRADE, OK = "blocked", "degraded", "ok"

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


def resolve_spec(name: str):
    """该模块在当前解释器里解析得到吗。用 find_spec 而不是 import：不执行模块、无副作用。

    `scripts/` 加进 sys.path，本仓自己的模块（`_yaml`、`kb_rev` 等）才不会误报成缺失。
    """
    saved = list(sys.path)
    sys.path.insert(0, str(SCRIPTS_DIR))
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
    只收非标准库、非本仓模块。
    """
    local = {p.stem for p in SCRIPTS_DIR.glob("*.py")}
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


def tool_version(cmd, args=("--version",)):
    """外部命令 → 一行版本串；命令不存在返回 None。"""
    exe = shutil.which(cmd)
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    line = (r.stdout or r.stderr or "").strip().splitlines()
    return line[0].strip() if line else "（无版本输出）"


def check_python():
    v = ".".join(str(x) for x in sys.version_info[:3])
    state = OK if sys.version_info >= (3, 10) else DEGRADE
    note = f"体检用的解释器：{sys.executable}"
    if state != OK:
        note += "；3.10 以下没有标准库名单，依赖判定只能按路径推断，可能多报"
    if sys.platform.startswith("win"):
        note += "；面板按 python3 → python → py -3 的顺序挑，挑中的未必是这一个——点面板报缺依赖时先对一下"
    return {"id": "python", "label": "Python", "state": state, "detail": v, "note": note,
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
        fix = (f"{sys.executable} -m pip install {pip_name}"
               f"；pip 名与 import 名不同时按发行包名装"
               f"；内网离线：{sys.executable} -m pip install --no-index --find-links <wheel 目录> {pip_name}")
        hard = sorted(info["hard"])
        if hard:
            rows.append({"id": name, "label": label, "kind": "package", "state": BLOCK,
                         "detail": f"未安装；{len(hard)} 个脚本无条件 import 它（如 {'、'.join(hard[:3])}）",
                         "note": "缺它时那些脚本在 import 阶段就退出，不是跑到一半才失败",
                         "fix": fix})
        else:
            rows.append({"id": name, "label": label, "kind": "package", "state": DEGRADE,
                         "detail": f"未安装；{len(info['files'])} 个脚本在 try/except 或平台条件里用它",
                         "note": "缺席时那些脚本自己退化，不会崩",
                         "fix": fix})
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
        return {"id": "node", "label": "Node.js", "state": OK, "detail": version, "fix": ""}
    return {"id": "node", "label": "Node.js", "state": DEGRADE, "detail": "未安装",
            "note": "诊断与知识沉淀不需要它；面板安装/构建、CI 检查、token 记账需要",
            "fix": "装 Node.js；或者面板改走插件页粘贴路径安装（那条不需要 node）"}


def check_gh():
    version = tool_version("gh")
    if version:
        return {"id": "gh", "label": "gh CLI", "kind": "tool", "state": OK, "detail": version,
                "note": "批量导 issue 还要登录：gh auth status"}
    return {"id": "gh", "label": "gh CLI", "kind": "tool", "state": DEGRADE, "detail": "未安装",
            "note": "只有批量导入 issue 与诊断时的上游修复核查用它；缺了这两处如实说明不可查证",
            "fix": "按平台装 gh，然后 gh auth login"}


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
    """部署级演进模式（deployment.yaml）。这是策略声明，不是环境缺陷。

    为什么放进体检：内网 fork 的预期形态是 `record-only`（只记信号不产卡）。不显示时，
    用户在收尾报告里只看到"没有卡"，会以为演进坏了；显示后，"按声明不产卡"与"演进失败"
    能分开。声明写坏只挡演进流程，不挡诊断与沉淀，所以记降级而不是阻断。
    """
    try:
        from evolve_mode import read_mode, ModeError
    except Exception as e:
        return {"id": "evolution", "label": "演进模式", "kind": "policy", "state": DEGRADE,
                "detail": f"读不出声明（{e.__class__.__name__}）",
                "fix": "确认 scripts/evolve_mode.py 在（缺文件时收尾读不到部署模式）"}
    try:
        mode, source = read_mode(root)
    except ModeError as e:
        return {"id": "evolution", "label": "演进模式", "kind": "policy", "state": DEGRADE,
                "detail": f"声明写坏：{e}",
                "note": "收尾检查会停下来问人，不会自己挑一档跑",
                "fix": "改 deployment.yaml 的 evolution.mode 为 full / record-only / off 之一"}
    meaning = {
        "full": "照常产卡并攒批进 PR",
        "record-only": "只记信号不产卡（内网 fork 的预期形态）",
        "off": "不做收尾检查",
    }[mode]
    return {"id": "evolution", "label": "演进模式", "kind": "policy", "state": OK,
            "detail": f"{mode} —— {meaning}（来源：{source}）", "fix": ""}


def check_pr_platforms(root):
    """PR 平台适配器清单：只读清单与环境变量，不联网、不装依赖。

    体检器不代装（见文件头三条约束）；这里只回答「这台机器上有几个平台能查 PR 状态」。
    清单由 scripts/pr_status.py --list-platforms 打印，doctor 不写平台特判。
    """
    script = Path(root) / "scripts" / "pr_status.py"
    if not script.is_file():
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": DEGRADE,
                "detail": "缺少 scripts/pr_status.py",
                "fix": "把插件更新到带沉淀队列的版本；或先跳过 PR 状态查询，用「标记已合入」手动确认"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--root", str(root), "--list-platforms", "--json"],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001 - 体检器把异常折成一行原因
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": DEGRADE,
                "detail": "清单脚本跑不起来：" + str(exc), "fix": "python3 scripts/pr_status.py --list-platforms"}
    try:
        doc = json.loads(proc.stdout.strip() or "{}")
    except Exception:  # noqa: BLE001
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": DEGRADE,
                "detail": "清单脚本没有给出 JSON", "fix": "python3 scripts/pr_status.py --list-platforms"}
    if doc.get("ok") is False:
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": DEGRADE,
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
    except Exception:  # noqa: BLE001 - 读台账失败不阻断清单检查
        target_platform = ""
    if target_platform:
        picked = next((p for p in platforms if str(p.get("id")) == target_platform), None)
        if picked is None:
            return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": DEGRADE,
                    "detail": "目标平台 " + target_platform + " 没有适配器",
                    "fix": "在 scripts/platforms/ 加适配器，或换一个目标远端"}
        if not picked.get("available"):
            return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": DEGRADE,
                    "detail": "目标平台 " + str(picked.get("name") or target_platform) + " 不可用："
                              + str(picked.get("reason") or "缺 token/命令"),
                    "fix": str(picked.get("install_hint") or "按适配器说明配 token/命令")}
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": OK,
                "detail": "目标平台 " + str(picked.get("name") or target_platform) + " 可用",
                "note": "清单来自 scripts/platforms/；只读，不联网"}
    ok = [p for p in platforms if p.get("available")]
    bad = [p for p in platforms if not p.get("available")]
    if not ok:
        reason = "；".join(str(p.get("reason") or p.get("id")) for p in bad[:3]) or "没有平台清单"
        return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": DEGRADE,
                "detail": "没有可用的平台：" + reason,
                "fix": "按适配器的 install_hint 配 token/命令；或先手动确认 PR 状态"}
    detail = "可用 " + "、".join(str(p.get("name") or p.get("id")) for p in ok)
    if bad:
        detail += "；不可用 " + "、".join(str(p.get("id")) for p in bad[:3])
    return {"id": "pr-platforms", "label": "PR 平台适配器", "kind": "tool", "state": OK, "detail": detail,
            "note": "清单来自 scripts/platforms/；只读，不联网"}


def check_kb_sync(root: Path):
    """知识库同步：只读本机状态，不联网。

    判三件事：部署是否声明离线、配置是否可用、本机远端 ref 落后多少。上次 fetch 的失败
    从 `.local/kb-sync-state.json` 读——它决定下一次开单会不会直接跳过联网。
    """
    try:
        import kb_sync
    except Exception as exc:  # noqa: BLE001 - 体检器把缺依赖折成一行原因
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": DEGRADE,
                "detail": f"读不出同步配置（{type(exc).__name__}: {exc}）",
                "fix": "python3 scripts/kb_sync.py --show"}
    try:
        mode = kb_sync.deployment_sync_mode(root)
        settings, config, problem = kb_sync.load_settings(root)
        config_sync = settings.get("sync") or {}
        state = kb_sync.load_state(root)
    except Exception as exc:  # noqa: BLE001
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": DEGRADE,
                "detail": f"读不出同步配置（{type(exc).__name__}: {exc}）",
                "fix": "python3 scripts/kb_sync.py --show"}

    if mode == "offline":
        return {"id": "kb-sync", "label": "知识库同步", "kind": "data", "state": OK,
                "detail": "offline —— deployment.yaml 声明 sync.mode: offline，不联网",
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
    try:
        snap = kb_sync.local_snapshot(root, remote, branch)
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
    if behind == "unknown":
        detail = f"本机没有 {remote_ref} ref，算不出落后"
        degraded = True
    elif isinstance(behind, int) and behind > 0:
        detail = f"落后 {remote_ref} {behind} 个提交"
        degraded = True
    else:
        detail = f"与 {remote_ref} 一致"
    if snap.get("same_repo") is False:
        detail += "；配置远端与 origin 不同源"
        degraded = True

    last_ok = str(state.get("last_ok_at") or "")
    last_reason = str(state.get("reason") or "")
    if last_reason:
        attempted = str(state.get("attempted_at") or "")
        detail += f"；上次 fetch 失败：{kb_sync.fetch_reason_text(last_reason)}"
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


def build_report(root: Path):
    checks = [check_python()]
    checks += check_third_party()
    checks += [check_git(root), check_node(), check_gh(), check_pr_platforms(root),
               check_kb_sync(root), check_traces(root), check_index(root), check_evolution(root)]
    checks.append(check_capability_table(checks))
    by_id = {c["id"]: c for c in checks}
    caps = []
    for name, needs in CAPABILITIES:
        miss = [n for n in needs if by_id.get(n, {}).get("state") == BLOCK]
        weak = [n for n in needs if by_id.get(n, {}).get("state") == DEGRADE]
        caps.append({"name": name, "needs": needs,
                     "state": "no" if miss else ("partial" if weak else "yes"), "missing": miss})
    # 没有任何能力引用的阻断项（新出现的第三方包、能力表自检失败）：单独列一条，否则结论会一边报
    # 「N 项阻断」一边说七条流程都能跑
    covered = {n for _, needs in CAPABILITIES for n in needs}
    orphan = [c["id"] for c in checks if c["state"] == BLOCK and c["id"] not in covered]
    if orphan:
        caps.append({"name": "其余脚本化流程", "needs": orphan, "state": "no", "missing": orphan})
    blocked = [c for c in checks if c["state"] == BLOCK]
    degraded = [c for c in checks if c["state"] == DEGRADE]
    actions = []
    for c in blocked + degraded:
        if c.get("fix") and c["fix"] not in actions:
            actions.append(c["fix"])
    return {"ok": not blocked, "root": str(root), "python": sys.executable,
            "blocked": len(blocked), "degraded": len(degraded),
            "checks": checks, "capabilities": caps, "next_actions": actions}


def render(rep) -> str:
    if rep["ok"]:
        head = f"结论：无阻断项，{rep['degraded']} 项降级。"
    else:
        head = f"结论：{rep['blocked']} 项阻断、{rep['degraded']} 项降级——先修阻断项，再重跑本命令。"
    lines = [head]
    for state, prefix in (("yes", "能跑"), ("partial", "降级"), ("no", "不能跑")):
        names = [c["name"] for c in rep["capabilities"] if c["state"] == state]
        if names:
            lines.append(f"  {prefix}：" + "、".join(names))

    bad = [c for c in rep["checks"] if c["state"] != OK]
    if bad:
        lines += ["", "证据："]
        for c in bad:
            lines.append(f"  [{'阻断' if c['state'] == BLOCK else '降级'}] {c['label']} —— {c['detail']}")
            if c.get("note"):
                lines.append(f"         {c['note']}")
            if c.get("fix"):
                lines.append(f"         修：{c['fix']}")
    good = [c["detail"] if c.get("kind") == "tool" else f"{c['label']} {c['detail']}"
            for c in rep["checks"] if c["state"] == OK]
    if good:
        lines.append(("" if bad else "\n") + "  正常：" + "；".join(good))

    lines += ["", "下一步（按影响面排序，一次修一项，修完重跑 python3 scripts/doctor.py）："]
    if rep["next_actions"]:
        lines += [f"  {i}. {a}" for i, a in enumerate(rep["next_actions"], 1)]
    else:
        lines.append("  环境齐了。验内容门禁跑 python3 scripts/rehearse_evolve_loop.py（逐条复跑 CI 命令）；"
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
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else SCRIPTS_DIR.parent
    if not (root / "scripts").is_dir():
        msg = f"{root} 不像 ascend-sleuth 检出（没有 scripts/）"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        else:
            print(f"doctor: {msg}", file=sys.stderr)
        return 3

    rep = build_report(root)
    print(json.dumps(rep, ensure_ascii=False) if args.json else render(rep))
    return 0 if rep["ok"] else 2


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
