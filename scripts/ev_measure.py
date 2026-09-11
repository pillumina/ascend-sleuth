#!/usr/bin/env python3
# ev_measure.py —— EV 卡预测的复现把手（reviewer 侧）
#
# 为什么需要它：execution §「评审（reviewer 角色）：卡 + before/after diff +
# predicted_effect vs verification 结果（30s 判定）」把评审设计成 30 秒判定，并把它失效的
# 形态命名为「评审变橡皮图章或被迫开全文」。但 predicted_effect 长期只有散文（存量 48 张卡
# 0 张带可执行命令），30s 判定无从执行——reviewer 只能开全文，或直接批。本脚本把
# 「预测 → 实测」对照压成一条命令：**任何 reviewer 都能跑，不要求他持有改动者的心智模型**。
# 多人协作时这一条尤其关键：评审者数量增长而"完整心智模型"只有一个。
#
# 判据强度（原则十，如实标注）：
#   - 本脚本证明**效果**（改动是否产生了它声称的变化），不证明**价值**（该变化是否值得）。
#   - 「命令是否真的在测那件事」机器判不了 = 约定强度，靠人审抽查。但一条命令 5 秒能读完，
#     一段无法复现的论证不能——这把"不可判"换成"可判但有残余风险"。
#   - 声明不可度量（measure.reason）是合法退化路径，计为无法判定（exit 2），不冒充通过。
#
# 退出码：0 = 符合预测 / 盘点无缺口；1 = 不符合预测（预测被证伪）；2 = 无法判定
# （找不到卡、声明不可度量、存量卡无口径、用法错）。2 与 1 分开，避免"判不了"被读成"失败"。
#
# 用法：
#   python3 scripts/ev_measure.py EV-2026-050            # 只看判据（不执行）
#   python3 scripts/ev_measure.py EV-2026-050 --run      # 执行并比对
#   python3 scripts/ev_measure.py --audit                # 全库盘点：可复现 / 声明不可度量 / 缺口 / 存量
#   python3 scripts/ev_measure.py --audit --json

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

# 与校验器共用同一份定义（cutover / 归一 helper）。抄成两份 = 口径漂移的经典来源，
# 所以这里 import 而不是复制。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_proposals import (  # noqa: E402
    MEASURE_CUTOVER,
    exit_code_value,
    measure_enforced,
)

CLIP_HEAD = 12          # 日志裁剪纪律：长输出只留头尾
CLIP_TAIL = 25
DEFAULT_TIMEOUT = 300


def load_cards(root: Path):
    """→ [(id, doc, path)]，按 id 排序。坏 YAML 静默跳过（校验器负责报它）。"""
    ideas = root / "proposals" / "ideas"
    cards = []
    if not ideas.exists():
        return cards
    for f in sorted(ideas.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("id"):
            cards.append((str(doc["id"]), doc, f))
    cards.sort(key=lambda t: t[0])
    return cards


def classify(doc):
    """预测口径 → (kind, measure)。kind ∈ runnable / declared / missing。"""
    pe = doc.get("predicted_effect")
    m = pe.get("measure") if isinstance(pe, dict) else None
    if not isinstance(m, dict):
        return "missing", None
    cmd = m.get("command")
    if isinstance(cmd, str) and cmd.strip():
        return "runnable", m
    if isinstance(m.get("reason"), str) and m["reason"].strip():
        return "declared", m
    return "missing", m


def clip(text: str) -> str:
    lines = text.rstrip("\n").split("\n") if text.strip() else ["（无输出）"]
    if len(lines) <= CLIP_HEAD + CLIP_TAIL + 2:
        return "\n".join(lines)
    hidden = len(lines) - CLIP_HEAD - CLIP_TAIL
    return "\n".join(lines[:CLIP_HEAD]
                     + [f"... （已裁剪 {hidden} 行——日志裁剪纪律）"]
                     + lines[-CLIP_TAIL:])


def one_line(value, limit=160) -> str:
    s = " ".join(str(value or "").split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def localize_command(command: str) -> str:
    """**仅 Windows**：把卡里写的 `python3 ...` 替换为本机当前解释器；其他平台原样返回。

    EV 卡的 `predicted_effect.measure.command` 按约定写成 `python3 scripts/xxx.py`
    （CI / Linux 口径）。Windows 上 `python3` 常不存在——python.org 安装器装的是
    `python.exe` + `py.exe` 启动器，而 PATH 里 Store 的「应用执行别名」占位程序既不
    打印版本也不返回 0。照原样执行会得到 ERROR（无法判定）；而"判据跑不起来"与
    "预测被证伪"必须分开（本脚本的退出码 2 与 1 正是为此分的）。只替换首个 token。

    POSIX 上**不做替换**：那里 `python3` 就在 PATH 里，替换会改变实际执行的解释器
    （虚拟环境里的 python 与 PATH 的 python3 未必同一个），属无谓的行为差异。
    """
    if os.name != "nt":
        return command
    parts = command.split(None, 1)
    if not parts or parts[0] not in ("python3", "python"):
        return command
    rest = f" {parts[1]}" if len(parts) > 1 else ""
    return f'"{sys.executable}"{rest}'


def describe(card_id, doc, kind, measure):
    pe = doc.get("predicted_effect") or {}
    print(f"=== {card_id} · {one_line(doc.get('title'), 90)} ===")
    print(f"状态: {doc.get('status')} · 维度: {doc.get('dimension')} · 授权: {doc.get('authorization')}")
    print(f"假设: {one_line(doc.get('hypothesis'), 220)}")
    if isinstance(pe, dict) and pe:
        print(f"预测: {one_line(pe.get('metric'), 160)}")
        print(f"  改前 from: {one_line(pe.get('from'), 160)}")
        print(f"  改后 to:   {one_line(pe.get('to'), 160)}")
    if kind == "runnable":
        print(f"判据: {measure['command'].strip()}")
        want = []
        ec = exit_code_value(measure.get("expect_exit"))
        if ec is not None:
            want.append(f"exit={ec}")
        so = measure.get("expect_stdout")
        if isinstance(so, str) and so.strip():
            want.append(f"输出含 {so.strip()!r}")
        print(f"  期望: {' 且 '.join(want)}")
    elif kind == "declared":
        print("判据: （声明不可度量）")
        print(f"  理由: {one_line(measure.get('reason'), 240)}")
    else:
        print("判据: （无）")


def run_measure(root: Path, measure, timeout: int):
    """执行并比对 → (verdict, detail)。verdict ∈ PASS / FAIL / ERROR。"""
    command = localize_command(measure["command"].strip())
    if command != measure["command"].strip():
        print(f"  （卡内命令以 `{measure['command'].strip().split(None, 1)[0]}` 书写；"
              f"本机改用当前解释器执行——判据等价，避免「跑不起来」被读成「被证伪」）")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run(command, shell=True, cwd=str(root), capture_output=True,
                           text=True, timeout=timeout, env=env, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "ERROR", f"命令超时（>{timeout}s）——预测未能在给定时限内复现"
    out = (r.stdout or "") + (r.stderr or "")

    checks = []                    # (说明, 是否满足, 实测描述)
    ec = exit_code_value(measure.get("expect_exit"))
    if ec is not None:
        checks.append((f"exit == {ec}", r.returncode == ec, f"实测 exit={r.returncode}"))
    so = measure.get("expect_stdout")
    if isinstance(so, str) and so.strip():
        hit = so.strip() in out
        checks.append((f"输出含 {so.strip()!r}", hit, "未出现" if not hit else ""))

    print(f"--- 实测（cwd={root}，timeout={timeout}s）---")
    print(clip(out))
    for label, ok, detail in checks:
        print(f"{label} {'✓' if ok else '✗'}" + (f"  :: {detail}" if detail else ""))
    verdict = "PASS" if all(c[1] for c in checks) else "FAIL"
    return verdict, ""


def cmd_card(root: Path, args, card_id: str) -> int:
    match = next((c for c in load_cards(root) if c[0] == card_id), None)
    if match is None:
        print(f"找不到卡 {card_id}（{root / 'proposals' / 'ideas'}）")
        return 2
    _, doc, _path = match
    kind, measure = classify(doc)
    describe(card_id, doc, kind, measure)

    if kind == "declared":
        print(f"=> 无法判定（exit 2）：本条如实声明不可度量——reviewer 无从复核，"
              f"按约定强度处理（原则十：不冒充通过）")
        return 2
    if kind == "missing":
        if measure_enforced(doc):
            print("=> 无法判定（exit 2）：强制卡缺 measure——CI 应已红（verify_proposals --check）")
        else:
            print("=> 无法判定（exit 2）：存量卡（"
                  f"created_at 早于 {MEASURE_CUTOVER.isoformat()}）豁免「预测可复现」，无口径可复现")
        return 2
    if not args.run:
        print(f"（未执行；加 --run 复现：python3 scripts/ev_measure.py {card_id} --run）")
        return 0

    verdict, detail = run_measure(root, measure, args.timeout)
    if verdict == "PASS":
        print("=> PASS 符合预测（效果层）。命令是否真在测那件事 = 约定强度，靠人审抽查")
        return 0
    if verdict == "ERROR":
        print(f"=> 无法判定（exit 2）：{detail}")
        return 2
    print("=> FAIL 不符合预测（预测被证伪）——按 execution §follow-up 判定：再迭代或回滚")
    return 1


def cmd_audit(root: Path, as_json: bool) -> int:
    buckets = {"runnable": [], "declared": [], "missing": [], "legacy": []}
    for cid, doc, _p in load_cards(root):
        kind, _m = classify(doc)
        if kind == "missing" and not measure_enforced(doc):
            buckets["legacy"].append(cid)
        else:
            buckets[kind].append(cid)

    enforced = len(buckets["runnable"]) + len(buckets["declared"]) + len(buckets["missing"])
    total = enforced + len(buckets["legacy"])
    if as_json:
        print(json.dumps({
            "cutover": MEASURE_CUTOVER.isoformat(),
            "total": total, "enforced": enforced,
            "runnable": buckets["runnable"], "declared": buckets["declared"],
            "missing": buckets["missing"], "legacy": buckets["legacy"],
        }, ensure_ascii=False, indent=2))
    else:
        print("EV 卡预测可复现性盘点（proposals/ideas/，口径 EV-2026-050）")
        print(f"  强制范围: created_at >= {MEASURE_CUTOVER.isoformat()} 的卡（{enforced}/{total} 张在范围内）")
        print(f"  可复现（command + 期望） : {len(buckets['runnable']):>3d}")
        print(f"  声明不可度量（reason）   : {len(buckets['declared']):>3d}   ← 如实退化，按约定强度")
        print(f"  缺口（强制卡缺 measure） : {len(buckets['missing']):>3d}   ← CI 应红")
        print(f"  存量豁免                 : {len(buckets['legacy']):>3d}   ← "
              f"补写不恢复当时的判断，只造事后叙述（原则十）")
        if buckets["missing"]:
            print("  缺口明细: " + "、".join(buckets["missing"]))
        print("\n  reviewer 用法: python3 scripts/ev_measure.py <card-id> --run")
    return 1 if buckets["missing"] else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="EV 卡预测的复现把手（reviewer 侧）")
    ap.add_argument("card_id", nargs="?", help="卡号，如 EV-2026-050")
    ap.add_argument("--run", action="store_true", help="执行判据命令并与期望比对")
    ap.add_argument("--audit", action="store_true", help="全库盘点预测可复现性")
    ap.add_argument("--json", action="store_true", help="配合 --audit 输出 JSON")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="执行判据的超时秒数")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()

    root = args.root.resolve()
    if args.audit:
        return cmd_audit(root, args.json)
    if not args.card_id:
        ap.error("需要卡号，或用 --audit 盘点全库")
    return cmd_card(root, args, args.card_id)


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
