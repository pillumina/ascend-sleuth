#!/usr/bin/env python3
# ev_proposal.py —— self-evolve 产卡辅助：卡号分配 + 卡骨架生成 + 卡概览
#
# self-evolve skill 执行"产候选卡"时的机械辅助（原则二/九：机械环节脚本化，
# agent 不手动数卡号/不手写易错骨架）：
#   1. 分配下一个 EV 卡号（读 proposals/ideas/ 现有卡，自动递增）
#   2. 生成卡骨架（从 examples/sample-idea.yaml 复制，填好 id/created_at，
#      其余字段留空待 agent 填）——避免格式错误
#   3. 卡概览（--list）：列现有卡 id/title/status/authorization，供起草时
#      查重与冲突检测（orchestration §5.2）
#
# 用法：
#   python3 scripts/ev_proposal.py --next          # 打印下一个卡号（如 EV-2026-002）
#   python3 scripts/ev_proposal.py --new           # 生成新卡骨架文件并打印路径
#   python3 scripts/ev_proposal.py --list          # 现有卡概览
#   python3 scripts/ev_proposal.py --status <id> <new_status>   # 推进卡状态（+ 追加 decisions 提示）
#
# 注意：卡状态推进涉及授权与验证语义（见 pipeline §7 状态机），本脚本只提供
# 机械辅助 + 校验提示，不自动改 status 语义——状态变更的合理性由 agent 依设计
# 判断，decisions 追加由 agent/人写入。

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

IDEAS_DIR = "proposals/ideas"
TEMPLATE = "examples/sample-idea.yaml"


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def next_id(root: Path) -> str:
    """下一个卡号 = max(文件名里的号, 卡内 `id:` 字段的号) + 1。

    为什么两处都看（2026-09-10 修）：只看 `id:` 字段时，一旦文件名与它内部的 `id:`
    不一致（复制粘贴卡时的常见手误，如文件叫 EV-2026-099.yaml 而内容是 `id: EV-2026-001`），
    算出的"下一个号"会撞上一个**已存在的文件名**；而 make_new 是直接覆盖写——于是静默
    吃掉一张既有卡。取两边最大值，让分配结果同时避开"已用号"与"已占文件名"。
    """
    year = datetime.now().year
    max_n = 0
    for f in (root / IDEAS_DIR).glob("EV-*.yaml"):
        candidates = []
        doc = load_yaml(f)
        if isinstance(doc, dict):
            candidates.append(str(doc.get("id", "")))
        candidates.append(f.stem)          # 文件名也算一路（防文件名/字段不一致）
        for cid in candidates:
            # 格式 EV-YYYY-NNN
            parts = cid.split("-")
            if len(parts) == 3 and parts[1] == str(year):
                try:
                    max_n = max(max_n, int(parts[2]))
                except ValueError:
                    pass
    return f"EV-{year}-{max_n + 1:03d}"


def make_new(root: Path) -> Path:
    cid = next_id(root)
    tpl = root / TEMPLATE
    out = root / IDEAS_DIR / f"{cid}.yaml"
    # 覆盖保护（2026-09-10）：本函数的写入是"直接覆盖"。一旦算出的号已被占用
    # （文件名/字段不一致、手工放了同名文件、并发产卡），覆盖写会**静默吃掉既有卡**——
    # 卡是审计资产，静默丢失不可接受。这里宁可失败也不覆盖，让人/agent 显式处理。
    if out.exists():
        raise FileExistsError(
            f"{out} 已存在——拒绝覆盖（EV 卡是审计资产，静默覆盖=丢决策链）。"
            "请先处理该文件：填完它、改名，或确认不该存在后删除，再重跑 --new。")
    if tpl.exists():
        # 复制模板，替换 id 与 created_at
        txt = tpl.read_text(encoding="utf-8")
        txt = txt.replace("id: EV-2026-001", f"id: {cid}")
        txt = txt.replace("created_at: 2026-09-01", f"created_at: {datetime.now().date().isoformat()}")
        out.write_text(txt, encoding="utf-8")
    else:
        out.write_text(f"# {cid} idea 卡骨架（模板缺失，手填）\nid: {cid}\n", encoding="utf-8")
    return out


def list_cards(root: Path):
    rows = []
    for f in sorted((root / IDEAS_DIR).glob("*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            rows.append((f.stem, "?", "?", "解析失败"))
            continue
        rows.append((
            str(doc.get("id", f.stem)),
            str(doc.get("title", ""))[:60],
            str(doc.get("status", "?")),
            str(doc.get("authorization", "?")),
        ))
    print(f"{'id':<14} {'status':<14} {'auth':<8} title")
    for cid, title, status, auth in rows:
        print(f"{cid:<14} {status:<14} {auth:<8} {title}")


def main():
    ap = argparse.ArgumentParser(description="self-evolve 产卡辅助")
    ap.add_argument("--next", action="store_true", help="打印下一个卡号")
    ap.add_argument("--new", action="store_true", help="生成新卡骨架")
    ap.add_argument("--list", action="store_true", help="列现有卡")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()
    if args.next:
        print(next_id(root))
    elif args.new:
        try:
            p = make_new(root)
        except FileExistsError as e:
            # 覆盖保护触发：非零退出 + 一行可读原因（不抛 traceback，agent 能直接照做）
            print(f"ev_proposal: 拒绝产卡——{e}", file=sys.stderr)
            sys.exit(2)
        print(f"已生成骨架: {p}")
        print(f"ID: {p.stem} —— 按 examples/sample-idea.yaml 填字段后跑 verify_proposals.py")
    elif args.list:
        list_cards(root)
    else:
        ap.print_help()


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
