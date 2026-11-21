#!/usr/bin/env python3
"""evolve_intake.py —— 演进记录的单一入口：先采集，再按部署声明分流

## 为什么要有这个入口

产卡动作原先散在七个 skill 里，每个都自己判断「要不要产卡」。文本判据会漂移，agent 也会绕。
本脚本把这条策略收进结构：

    调用方（任何 skill）→ evolve_intake record <观察载荷>
                              │ 读 sleuth.yaml 的 evolution.role
                              ├─ maintainer  → 写信号台账，上游分诊后走 RSI
                              ├─ signal-only → 写 proposals/signals/<部署>-<哈希>.yaml
                              └─ off         → 不落盘，只打印一行
                              （旧 deployment.yaml 的 full 仍兼容为产卡骨架）

## 为什么采集在分流之前

record-only 不该「什么都不记」：值得关注的信号恰恰出在下游部署。载荷在分流前定下来，模式只决定
落到卡还是落到台账，信息不会因为模式而丢。

## 记录层能保证什么、不能保证什么

能：证据不空、组件与出处可解析、同一信号去重计数。这些是确定性的，脚本可以判。
不能：这条信号值不值得产卡——那要读组件、读卡库、读指标，是上游分诊层（深层轮 + 独立预核）的事。

## 用法

    python3 scripts/evolve_intake.py record --signal T10 --signal-text "自审发现的缺口" \\
        --target skills/evolve-check/SKILL.md --evidence "收尾原因串与面板解析不同源" \\
        --trajectory products/VLLM-ASC-123(submitted) --suggested "让两者同源" --source evolve-check

退出码：0 正常；2 载荷不合契约或部署声明写坏。
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

import evolve_signals as ES
import evolve_mode as EM

PLACEHOLDER_EVIDENCE = {"待填", "todo", "tbd", "证据", "无", "-", "...", "同上"}


def repo_root(start: Path = None) -> Path:
    return ES.repo_root(start)


def validate(root: Path, target: str, evidence: str, trajectory) -> list:
    """记录层的完整性契约。返回错误列表（空 = 通过）。

    只判「能不能被复核」，不判「值不值得产卡」——后者是上游分诊层的事。
    """
    errors = []
    ev = (evidence or "").strip()
    if len(ev) < 8:
        errors.append(f"证据太短（{ev!r}）：写现象不写结论，至少一句话；不写客户原文")
    if ev.lower() in PLACEHOLDER_EVIDENCE:
        errors.append(f"证据是占位词（{ev!r}）：占位记录会污染下游分诊")
    tgt = (target or "").strip()
    if not tgt:
        errors.append("缺 target_component：没有组件的信号无法分诊")
    elif "/" in tgt and not (Path(root) / tgt).exists():
        errors.append(f"target_component 指向的文件不存在：{tgt}（写仓库内路径或组件名）")
    traj = [t for t in (trajectory or []) if str(t).strip()]
    if not traj:
        errors.append("缺 trajectory：没有出处的信号无法回放")
    return errors


def soft_warnings(root: Path, trajectory) -> list:
    """路徑样但解析不到的出处只提示，不拒收（制品 id 与 trace 锚本来就不是文件）。"""
    out = []
    for t in trajectory or []:
        s = str(t).split("#")[0]
        if "/" in s and re.search(r"\.[A-Za-z0-9]{1,6}$", s) and not (Path(root) / s).exists():
            out.append(s)
    return out


def _prefill_card(path: Path, *, signal: str, signal_text: str, target: str, evidence: str,
                  trajectory, suggested: str) -> None:
    """把骨架卡里最费手的几行填上，其余（hypothesis / measure / validation）留给人。

    用行级替换而不是整文件 dump：模板里的注释是填卡指引，dump 会把它们冲掉。
    """
    text = path.read_text(encoding="utf-8")
    title = f"{signal_text or signal} → {target}"
    title = (title[:78] + "…") if len(title) > 79 else title
    lines = text.splitlines()
    block = ["source_signals:", f"  - signal: {signal}", f"    evidence: {evidence!r}",
             "    trajectory:"]
    block += [f"      - {str(t)!r}" for t in trajectory]
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("target_component:"):
            out.append(f"target_component: {target}")
            i += 1
            continue
        if ln.startswith("title:"):
            out.append(f"title: {title}")
            i += 1
            continue
        if ln.startswith("source_signals:"):
            out += block
            i += 1
            while i < len(lines) and not lines[i].startswith("hypothesis:"):
                i += 1
            continue
        out.append(ln)
        i += 1
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def record(root: Path, *, signal: str, signal_text: str, target: str, evidence: str,
           trajectory, suggested: str = "", source: str = "evolve-check",
           session: str = "", force: bool = False) -> dict:
    role, mode_source = EM.read_role(root)
    if role is None:
        mode, mode_source = EM.read_mode(root)
    else:
        # 新角色语义：maintainer 也先把观察落成信号；是否提升为 RSI 提案由
        # 上游分诊决定，不再自动产 EV 卡。旧 deployment.yaml 仍走 legacy full。
        mode = "off" if role == "off" else "record-only"
    errors = validate(root, target, evidence, trajectory)
    if errors:
        raise ValueError("；".join(errors))

    if mode == "off":
        return {"mode": mode, "mode_source": mode_source, "path": None}

    if mode == "record-only":
        r = ES.add(root, signal=signal, target=target, evidence=evidence,
                   trajectory=trajectory, suggested=suggested, source=source,
                   session=session, signal_text=signal_text)
        return {"mode": mode, "mode_source": mode_source, "path": r["path"],
                "occurrences": r["doc"]["occurrences"]}

    # full：预填卡骨架。--force 让演练与测试能在非 full 部署里走通这条路。
    if not force:
        import ev_proposal as EP
        p = EP.make_new(root)
    else:
        import ev_proposal as EP
        p = EP.make_new(root, force=True)
    _prefill_card(p, signal=signal, signal_text=signal_text, target=target,
                  evidence=evidence, trajectory=trajectory, suggested=suggested)
    return {"mode": mode, "mode_source": mode_source, "path": p}


def main(argv=None):
    ap = argparse.ArgumentParser(description="演进记录入口：采集 → 按部署声明分流")
    ap.add_argument("--root", type=Path, default=None, help="仓库根（默认当前检出顶层）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="记录一条演进观察（卡或台账由部署声明决定）")
    r.add_argument("--signal", required=True, help="信号编号或自由文本（如 T10）")
    r.add_argument("--signal-text", default="", help="信号的中文含义")
    r.add_argument("--target", required=True, help="要改的组件：仓库内路径或组件名")
    r.add_argument("--evidence", required=True, help="一句话现象（不含客户原文）")
    r.add_argument("--trajectory", action="append", default=[], help="出处：产出 id / trace / 链路，可重复")
    r.add_argument("--suggested", default="", help="建议动作（可选）")
    r.add_argument("--source", default="evolve-check", help="来源 skill")
    r.add_argument("--session", default="", help="会话 id（如有）")
    r.add_argument("--force", action="store_true", help="演练/测试：非 full 部署也产卡骨架")

    args = ap.parse_args(argv)
    root = (args.root or repo_root()).resolve()

    try:
        res = record(root, signal=args.signal, signal_text=args.signal_text, target=args.target,
                     evidence=args.evidence, trajectory=args.trajectory,
                     suggested=args.suggested, source=args.source, session=args.session,
                     force=args.force)
    except EM.ModeError as e:
        print(f"✗ 部署声明写坏：{e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    warns = soft_warnings(root, args.trajectory)
    for w in warns:
        print(f"! 出处解析不到（按制品 id 处理）：{w}", file=sys.stderr)

    mode = res["mode"]
    if mode == "off":
        print(f"skip：部署声明 off（{res['mode_source']}）——不记录")
    elif mode == "record-only":
        print(f"signal：{res['path']}（{res['occurrences']} 次；{res['mode_source']}）")
    else:
        print(f"card：{res['path']}（骨架已填 source_signals，measure 待填；{res['mode_source']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
