#!/usr/bin/env python3
# evolve_mode.py —— 部署级演进模式的唯一读取入口
#
# 谁读：evolve-check 第 0 步（收尾检查）、self-evolve 深度轮、doctor。
# 为什么单列一个脚本：三处各自解析 sleuth.config.yaml 会各自漂移，所以解析只做一次。
#
# 取值与优先级（先命中先用）：
#   1. 环境变量 ASCEND_SLEUTH_EVOLUTION —— 临时覆盖（CI、演练、一次运行）
#   2. 仓库根 sleuth.config.yaml 的 evolution.role —— 部署声明
#   3. 无配置时内置默认值 maintainer
#
# 写坏（取值不在词表内、YAML 解析失败、文件存在但缺 evolution.mode）时报错退出：
# 不猜、不静默降级——静默降级到 off 会让"这个部署在演进"与"这个部署关掉了演进"
# 在数据上无法区分（原则十）。
#
# 用法：
#   python3 scripts/evolve_mode.py                    # 一行：role=maintainer（来源：sleuth.config.yaml）
#   python3 scripts/evolve_mode.py --json             # {"mode": ..., "source": ...}
#   python3 scripts/evolve_mode.py --set record-only  # 写部署声明（git 里显示为未提交改动）

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import sleuth_config as SC

MODES = ("full", "record-only", "off")
SET_CHOICES = ("full", "record-only", "off", "maintainer", "signal-only")

ENV_VAR = "ASCEND_SLEUTH_EVOLUTION"



def repo_root(start: Path = None) -> Path:
    """仓库根：优先 git 给的顶层目录，退化到脚本所在仓库。

    读的是**当前检出**（不是主检出）：允许一个分支上的声明与另一分支不同，
    evolve 模式是随分支走的仓库属性。
    """
    start = Path(start or Path.cwd())
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True, cwd=str(start), encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    return Path(__file__).resolve().parents[1]


class ModeError(Exception):
    """声明写坏：调用方要把消息原样给用户，不要吞。"""


def parse_mode(raw, source: str) -> str:
    # YAML 1.1 把不带引号的 off / no 读成布尔 False（`mode: off` 是这种写法）。
    # 词表里没有名为 true/false 的模式，所以 False 只能是想写 off——照它收下；
    # True 没有对应的模式，报错，并说清是引号的事。
    if isinstance(raw, bool):
        if raw is False:
            return "off"
        raise ModeError(
            f"{source} 的 evolution.mode 被读成了布尔值 True（YAML 把 on / yes 当布尔）。"
            f'写 full / record-only / off 之一；要 off 就加引号：mode: "off"，或改用 --set 生成。'
        )
    value = str(raw).strip()
    value = SC.ROLE_ALIASES.get(value, value)
    if value in ("maintainer", "signal-only"):
        return {"maintainer": "full", "signal-only": "record-only"}[value]
    if value not in MODES:
        raise ModeError(
            f"{source} 的 evolution.mode 是 {value!r}，不在词表 {list(MODES)} 里。"
            f"改成 maintainer / signal-only / off 之一。"
        )
    return value


def read_role(root: Path):
    """→ (role, source)。只读 sleuth.config.yaml；环境变量可临时覆盖。"""
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        mode = parse_mode(env, f"环境变量 {ENV_VAR}")
        role = {"full": "maintainer", "record-only": "signal-only", "off": "off"}[mode]
        return role, f"环境变量 {ENV_VAR}"
    try:
        config = SC.load_config(Path(root))
        return SC.role(config), str(config.get("_source") or SC.CONFIG_NAME)
    except SC.ConfigError as exc:
        raise ModeError(str(exc)) from exc


def read_mode(root: Path):
    """→ (mode, source)。对外保持旧三值；role 映射到旧词表。"""
    role, source = read_role(root)
    return {"maintainer": "full", "signal-only": "record-only", "off": "off"}[role], source


def _set_role_text(text: str, role: str) -> str:
    """按行替换 evolution.role，保留注释与排版。"""
    lines = text.splitlines(keepends=True)
    evo_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^evolution:\s*(?:#.*)?$", line.rstrip("\n")):
            evo_idx = i
            break
        if re.match(r"^evolution:\s*\{\s*\}\s*(?:#.*)?$", line.rstrip("\n")):
            indent = line[:len(line) - len(line.lstrip())]
            lines[i] = f"{indent}evolution:\n{indent}  role: \"{role}\"\n"
            return "".join(lines)
    if evo_idx is None:
        return text.rstrip() + f'\nevolution:\n  role: "{role}"\n'
    end_idx = len(lines)
    for j in range(evo_idx + 1, len(lines)):
        if lines[j].strip() and not lines[j].startswith((" ", "\t", "#")):
            end_idx = j
            break
    for j in range(evo_idx + 1, end_idx):
        match = re.match(r"^(\s*)role:\s*([^#\n]*?)(\s*#.*)?$", lines[j].rstrip("\n"))
        if match:
            lines[j] = f'{match.group(1)}role: "{role}"{match.group(3) or ""}\n'
            return "".join(lines)
    insert_at = evo_idx + 1
    lines.insert(insert_at, f'  role: "{role}"\n')
    return "".join(lines)


def write_mode(root: Path, mode: str) -> Path:
    path = Path(root) / SC.CONFIG_NAME
    role = SC.ROLE_ALIASES.get(mode, mode)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        path.write_text(_set_role_text(text, role), encoding="utf-8")
        return path
    path.write_text(
        "schema: {}\nevolution:\n  role: \"{}\"\n".format(SC.SCHEMA, role),
        encoding="utf-8")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="读/写部署演进角色（sleuth.config.yaml）")
    ap.add_argument("--root", type=Path, default=None, help="仓库根（默认当前检出的顶层）")
    ap.add_argument("--json", action="store_true", help="输出 JSON：{mode, source}")
    ap.add_argument("--set", choices=SET_CHOICES, default=None, help="写入配置角色")
    args = ap.parse_args(argv)

    root = args.root or repo_root()
    try:
        if args.set:
            path = write_mode(root, args.set)
            print(f"已写入 {path}：evolution.role={SC.ROLE_ALIASES.get(args.set, args.set)}")
            print("git 里会显示为未提交改动；提交后对该仓的所有检出与所有 agent 生效。")
            return 0
        mode, source = read_mode(root)
    except ModeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    try:
        role, _ = read_role(root)
    except ModeError:
        role = None
    if args.json:
        print(json.dumps({"mode": mode, "role": role, "source": source}, ensure_ascii=False))
    else:
        print(f"role={role or mode} mode={mode}（来源：{source}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
