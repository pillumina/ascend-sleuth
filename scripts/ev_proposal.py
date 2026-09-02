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
    year = datetime.now().year
    max_n = 0
    for f in (root / IDEAS_DIR).glob("EV-*.yaml"):
        doc = load_yaml(f)
        if isinstance(doc, dict):
            cid = str(doc.get("id", ""))
        else:
            cid = f.stem
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
        p = make_new(root)
        print(f"已生成骨架: {p}")
        print(f"ID: {p.stem} —— 按 examples/sample-idea.yaml 填字段后跑 verify_proposals.py")
    elif args.list:
        list_cards(root)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
