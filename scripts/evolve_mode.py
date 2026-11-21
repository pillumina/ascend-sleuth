#!/usr/bin/env python3
# evolve_mode.py —— 部署级演进模式的唯一读取入口
#
# 谁读：evolve-check 第 0 步（收尾检查）、self-evolve 深度轮、doctor。
# 为什么单列一个脚本：三处各自解析 deployment.yaml 会各自漂移（本仓有过写侧与校验侧
# 各持一份词表的教训），所以解析只在这里做一次。
#
# 取值与优先级（先命中先用）：
#   1. 环境变量 ASCEND_SLEUTH_EVOLUTION —— 临时覆盖（CI、演练、一次运行），不是团队声明
#   2. 仓库根 deployment.yaml 的 evolution.mode —— 团队声明，随 PR 走
#   3. 缺省 full —— 与未引入这份声明时的行为一致
#
# 写坏（取值不在词表内、YAML 解析失败、文件存在但缺 evolution.mode）时报错退出：
# 不猜、不静默降级——静默降级到 off 会让"这个部署在演进"与"这个部署关掉了演进"
# 在数据上无法区分（原则十）。
#
# 用法：
#   python3 scripts/evolve_mode.py                    # 一行：mode=record-only（来源：deployment.yaml）
#   python3 scripts/evolve_mode.py --json             # {"mode": ..., "source": ...}
#   python3 scripts/evolve_mode.py --set record-only  # 写部署声明（git 里显示为未提交改动）

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

import sleuth_config as SC

MODES = ("full", "record-only", "off")
SET_CHOICES = ("full", "record-only", "off", "maintainer", "signal-only")

ENV_VAR = "ASCEND_SLEUTH_EVOLUTION"

DECL_REL = Path("deployment.yaml")

TEMPLATE = """\
# 部署级声明（每部署一份、不参与合并：两仓同名时保留本仓那份）。
#
# 谁读：scripts/evolve_mode.py —— evolve-check 收尾检查、self-evolve 深度轮、doctor。
# 取值：
#   full        照常产 EV 卡并攒批进 PR（上游默认）
#   record-only 仍然扫信号、仍然落执行记录，但不产卡、不跑验证门；
#               需要改行为面的信号写进收尾说明，由 MR 描述或 issue 交上游
#   off         不做收尾检查（仍落一条 skip 记录，让"没跑"与"跑了无信号"可区分）
# 值带引号写：YAML 会把不带引号的 off / on 读成布尔（解析侧对 False 兜成 off，True 报错）。
evolution:
  mode: "{mode}"
"""


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
            f"改成其中之一，或删掉该键走缺省（full）。"
        )
    return value


def read_role(root: Path):
    """→ (role, source)。新配置优先；旧 deployment.yaml 仍作兼容。"""
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return SC.ROLE_ALIASES.get(parse_mode(env, f"环境变量 {ENV_VAR}"),
                                   parse_mode(env, f"环境变量 {ENV_VAR}")), f"环境变量 {ENV_VAR}"
    try:
        cfg = SC.load_config(root)
    except SC.ConfigError as exc:
        raise ModeError(str(exc)) from exc
    if cfg.get("_source") != "legacy（deployment.yaml / eval/policy*.yaml / store.yaml）":
        return SC.role(cfg), str(cfg.get("_source") or SC.CONFIG_NAME)
    return None, "legacy"


def read_mode(root: Path):
    """→ (mode, source)。对外保持旧三值；新配置 role 映射到旧词表。"""
    role, source = read_role(root)
    if role is not None:
        return {"maintainer": "full", "signal-only": "record-only", "off": "off"}[role], source

    path = Path(root) / DECL_REL
    if not path.is_file():
        return "full", "缺省（无 deployment.yaml）"

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ModeError(f"{DECL_REL} 解析失败：{e}") from e

    if not isinstance(doc, dict):
        raise ModeError(f"{DECL_REL} 顶层不是映射（应为 evolution: {{mode: ...}}）")
    evolution = doc.get("evolution")
    if not isinstance(evolution, dict) or "mode" not in evolution:
        raise ModeError(f"{DECL_REL} 存在但缺少 evolution.mode——补上，或删掉该文件走缺省（full）")
    return parse_mode(evolution["mode"], str(DECL_REL)), str(DECL_REL)


def write_mode(root: Path, mode: str) -> Path:
    path = Path(root) / SC.CONFIG_NAME
    if path.is_file():
        raw = SC._read_yaml(path)
        raw.setdefault("schema", SC.SCHEMA)
        raw.setdefault("evolution", {})
        raw["evolution"]["role"] = SC.ROLE_ALIASES.get(mode, mode)
        path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=1000),
                        encoding="utf-8")
        return path
    path.write_text(
        "schema: {}\nevolution:\n  role: {}\n".format(
            SC.SCHEMA, SC.ROLE_ALIASES.get(mode, mode)),
        encoding="utf-8")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="读/写部署演进角色（sleuth.yaml）")
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
