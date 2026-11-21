#!/usr/bin/env python3
# precheck.py —— 提交前预核的触发判定与报告审计
#
# 两个子命令：
#   policy：按改动路径与标签判定要不要派判断性预核、哪一档、上限多少、跑哪些检查
#   audit ：汇总 proposals/reviews/ 的预核报告，算字符、结论次数、发现数，模拟正文上限的节省
#
# 为什么需要 policy：原流程每个 PR 都派一次独立预核，报告没有上限；本地 22 份报告合计
# 36.8 万字符，13 份有两次以上结论，最长的一份 6.4 万字符、10 次结论。把"什么时候做、
# 做多大"写成可执行判定，避免每次靠临场判断，也让"低风险改动不派会话"有据可查。
#
# 为什么 audit 只是本地工具：报告在 proposals/reviews/（gitignored），CI 上没有这一份；
# 它给维护者一条可重复的"有没有收益"读数，不进 CI。字符数只算报告输出，不含读 diff 与
# 跑门的输入；比例用于比较不同上限，不是绝对 token 数。
#
# 用法：
#   python3 scripts/precheck.py policy --base origin/main
#   python3 scripts/precheck.py policy --paths docs/README.md scripts/precheck.py --label kb/high-risk
#   python3 scripts/precheck.py audit --dir proposals/reviews --cap 6000
#
# 退出码：0 判定完成 / 审计完成；2 用法或读取错误。

import argparse
import re
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 改动面 → 档位。顺序有意义：先判脚本/机制面，再判内容面，最后判文档面。
SCRIPT_PREFIXES = (
    "scripts/",
    "dsh-plugins/",
    ".github/workflows/",
    "metrics/gates.yaml",
    "eval/",
    "tests/",
    "proposals/",
    "triage-tree.d/",
    "docs/spec/",
    "docs/mechanism/",
)
SCRIPT_FILES = (
    "triage-tree.yaml",
    "docs/guide/git-workflow.md",
)
CONTENT_PREFIXES = ("knowledge/", "references/")
DOC_PREFIXES = ("docs/", "skills/", ".github/PULL_REQUEST_TEMPLATE/")
DOC_FILES = ("README.md", "CLAUDE.md", "AGENTS.md", "CONTEXT.md")

# 生成物、数据与资产：机器能判，不派会话。未列出的路径按脚本/机制档做（判不准时取高）。
SELFCHECK_PREFIXES = (
    "metrics/timeline.d/",
    "metrics/entry-activity.d/",
    "assets/",
)

CAPS = {
    "script": {"rounds": 2, "max_findings": 5, "max_report_chars": 6000},
    "content": {"rounds": 1, "max_findings": 3, "max_report_chars": 3000},
    "docs": {"rounds": 1, "max_findings": 3, "max_report_chars": 3000},
}

CHECKLISTS = {
    "docs": [
        "可读性 / 逻辑性 / 黑话三项各给一行结论",
        "对照 writing-norms §1 逐条过改动段落，报命中项与行号",
        "文中路径、命令、字段名、代号、数字逐个核对",
        "新增代号登记 docs/glossary.yaml，scope 写对",
    ],
    "content": [
        "route_check.py 报出会落在哪个分支",
        "quickly_check.expected 在真实报错上跑一次",
        "与相邻 case 查重，事实自洽",
        "脱敏自查",
    ],
    "script": [
        "对改动的判定逻辑构造反例并跑出来",
        "检查门本身有没有洞（静默跳过、假绿、真空通过）",
        "断言是否真钉住行为，跨平台路径与错误路径有没有覆盖",
        "受影响的文档承诺扫一遍，临时件有没有残留",
    ],
}


def _match(path: str, prefixes, files) -> bool:
    p = path.replace("\\", "/")
    if p in files:
        return True
    return any(p == pref or p.startswith(pref) for pref in prefixes)


def classify(paths, labels=()):
    """→ dict：mode / tier / reasons / caps / checks / checklist。

    mode：selfcheck（不派会话）/ light（判断性预核，文档或内容档）/ full（脚本机制档）。
    tier：docs / content / script。
    """
    labels = [str(x) for x in (labels or [])]
    paths = [str(x).replace("\\", "/") for x in (paths or [])]
    reasons, checks = [], []
    hit_script, hit_content, hit_docs, hit_selfcheck, unknown = [], [], [], [], []

    for p in paths:
        if _match(p, SCRIPT_PREFIXES, SCRIPT_FILES):
            hit_script.append(p)
        elif _match(p, CONTENT_PREFIXES, ()):
            hit_content.append(p)
        elif _match(p, DOC_PREFIXES, DOC_FILES):
            hit_docs.append(p)
        elif _match(p, SELFCHECK_PREFIXES, ("sleuth.config.yaml", ".gitignore")):
            hit_selfcheck.append(p)
        else:
            unknown.append(p)

    if unknown:
        # 判不准时取高，不静默降级；单独记原因，输出里能看出是兜底而不是识别为脚本面。
        hit_script += unknown
        reasons.append("未识别路径，按脚本/机制档兜底：" + "、".join(unknown[:4]))

    if "kb/high-risk" in labels:
        reasons.append("标签 kb/high-risk：按脚本/机制档做")
        if not hit_script:
            hit_script = list(paths) or ["<未给路径>"]

    if hit_script:
        mode, tier = "full", "script"
        reasons.append("脚本/机制面：" + "、".join(hit_script[:4]) + ("…" if len(hit_script) > 4 else ""))
        checks += [
            "git status --porcelain | cut -c4- | python3 scripts/select_unit_tests.py",
            "只跑改动面自己的 --check，不重跑全部门；全门由 CI 负责",
        ]
        if any(p.startswith("tests/") for p in paths):
            checks.append("python3 scripts/check_test_portability.py")
        if any(p.startswith("proposals/") for p in paths):
            checks.append("python3 scripts/verify_proposals.py --check")
    elif hit_content:
        mode, tier = "light", "content"
        reasons.append("内容面：" + "、".join(hit_content[:4]))
        checks += [
            "python3 scripts/route_check.py <case 文件>",
            "只跑内容面的检查，不重跑全部门；全门由 CI 负责",
        ]
    elif hit_docs:
        mode, tier = "light", "docs"
        reasons.append("文档面：" + "、".join(hit_docs[:4]))
        checks.append("python3 scripts/build_docs_index.py --check")
        checks.append("python3 scripts/render_review_summary.py --scan <改动的文档或目录>")
    elif hit_selfcheck:
        mode, tier = "selfcheck", "selfcheck"
        reasons.append("生成物/数据/资产：" + "、".join(hit_selfcheck[:4]) + "，机器能判，不派会话")
        checks.append("按改动面跑对应的 --check，不派判断性预核")
    else:
        mode, tier = "full", "script"
        reasons.append("没有可识别的改动面：按脚本/机制档兜底")

    return {
        "mode": mode,
        "tier": tier,
        "reasons": reasons,
        "caps": CAPS[tier] if mode != "selfcheck" else None,
        "checks": checks,
        "checklist": CHECKLISTS[tier] if mode != "selfcheck" else [],
    }


def fmt_policy(result) -> str:
    lines = [f"mode: {result['mode']}", f"tier: {result['tier']}", "reasons:"]
    lines += [f"  - {r}" for r in result["reasons"]]
    caps = result["caps"]
    if caps:
        lines.append("caps:")
        if caps["rounds"] >= 2:
            lines.append(f"  rounds: {caps['rounds']}（第 1 轮审全量，第 2 轮只审增量）")
        else:
            lines.append(f"  rounds: {caps['rounds']}（只审一轮）")
        lines.append(f"  max_findings: {caps['max_findings']}")
        lines.append(f"  max_report_chars: {caps['max_report_chars']}")
        lines.append("report_header:")
        lines.append(f"  模式：判断性预核（{result['tier']} 档）")
        lines.append(f"  轮次：第 1 轮 / 上限 {caps['rounds']} 轮")
        lines.append("  结局：待回填（采纳 / 驳回 / 未处理）")
    lines.append("checks:")
    lines += [f"  - {c}" for c in result["checks"]]
    if result["checklist"]:
        lines.append("checklist:")
        lines += [f"  - {c}" for c in result["checklist"]]
    return "\n".join(lines)


def git_changed(root: Path, base: str):
    """→ 改动文件列表；git 读不到返回 None，确实没有改动返回 []。

    用 `git diff <base>`（工作区 vs 基线）而不是 `base...HEAD`：提交前跑时还没提交的改动
    也要算进来。未跟踪文件另取一次，否则新建的脚本/测试在提交前看不见。
    """
    try:
        mb = subprocess.run(
            ["git", "-C", str(root), "merge-base", base, "HEAD"],
            capture_output=True, text=True, encoding="utf-8",
        )
        diff_base = mb.stdout.strip() if mb.returncode == 0 and mb.stdout.strip() else base
        r = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", diff_base],
            capture_output=True, text=True, encoding="utf-8",
        )
        if r.returncode != 0:
            return None
        paths = [x for x in r.stdout.splitlines() if x.strip()]
        u = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, encoding="utf-8",
        )
        if u.returncode == 0:
            paths += [x for x in u.stdout.splitlines() if x.strip()]
        return sorted(set(paths))
    except OSError:
        return None


CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _num(raw: str) -> int:
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    if raw in CN_DIGITS:
        return CN_DIGITS[raw]
    return 0


def _section_count(text: str, level: str) -> int:
    """数「### 重要级」这类小节下的编号条目；同一级别跨轮出现时取单节最大值。

    报告有两种写法：摘要里的「N 条重要级」，和小节标题 + 编号列表。只认前一种会把
    「### 1.2 重要级 + 1./2./3.」记成 0，上限模拟就失去意义。
    """
    lines = text.splitlines()
    in_section = False
    counts, current = [], 0
    for line in lines:
        stripped = line.strip()
        is_heading = (bool(re.match(r"^#{1,6}\s", stripped))
                      or bool(re.match(r"^\*\*[^*]+\*\*", stripped))
                      or (stripped.endswith(("：", ":")) and level in line))
        if is_heading:
            if in_section:
                counts.append(current)
            # 「阻断/重要级」这种合写按重要级算；阻断级不重复计。
            in_section = level in line and not (level == "阻断" and "/" in line)
            current = 0
            continue
        if in_section and re.match(r"^\s*\d+[.、]\s+", line):
            current += 1
    if in_section:
        counts.append(current)
    return max(counts or [0])


def max_level_count(text: str, level: str) -> int:
    pats = [
        re.compile(r"([0-9]+|[一二两三四五六七八九十]+)[ \t]*条[ \t]*" + level + "级"),
        re.compile(level + r"级[ \t]*([0-9]+|[一二两三四五六七八九十]+)[ \t]*条"),
    ]
    nums = []
    for pat in pats:
        nums += [_num(m.group(1)) for m in pat.finditer(text)]
    return max(nums + [_section_count(text, level)])


def audit_reports(directory: Path, cap: int = 6000):
    """→ dict：报告数、字符、结论次数、发现数、上限模拟。跳过 *pr-body*.md。"""
    files = sorted(p for p in directory.glob("*.md") if "pr-body" not in p.name)
    rows = []
    for p in files:
        text = p.read_text(encoding="utf-8")
        rows.append({
            "name": p.name,
            "chars": len(text),
            "verdicts": len(re.findall(r"MERGE_READY\s*[:：]", text)),
            "blocking": max_level_count(text, "阻断"),
            "important": max_level_count(text, "重要"),
            "suggestion": max_level_count(text, "建议"),
        })
    total = sum(r["chars"] for r in rows)
    capped = sum(min(r["chars"], cap) for r in rows)
    return {
        "files": len(rows),
        "chars": total,
        "median": int(statistics.median([r["chars"] for r in rows])) if rows else 0,
        "max": max([r["chars"] for r in rows] or [0]),
        "multi": sum(1 for r in rows if r["verdicts"] >= 2),
        "max_important": max([r["important"] for r in rows] or [0]),
        "max_total": max([r["blocking"] + r["important"] + r["suggestion"] for r in rows] or [0]),
        "over_total_cap": sum(1 for r in rows
                              if r["blocking"] + r["important"] + r["suggestion"] > 5),
        "capped": capped,
        "saving": (1 - capped / total) if total else 0,
        "rows": rows,
    }


def fmt_audit(result, cap: int) -> str:
    lines = [
        f"报告：{result['files']} 份（已跳过 *pr-body*.md）",
        f"字符：{result['chars']:,}（中位 {result['median']:,}，最大 {result['max']:,}）",
        f"结论次数 ≥2 的报告：{result['multi']} 份",
        f"重要级最多 {result['max_important']} 条/份；发现合计最多 {result['max_total']} 条/份；"
        f"超过 5 条上限的报告：至少 {result['over_total_cap']} 份（按「N 条」、小节编号与合写标题计数；行内分号列表可能少计）",
        f"上限模拟（正文 ≤{cap:,} 字符）：{result['capped']:,} 字符，省 {result['saving'] * 100:.1f}%",
        "字符数只算报告输出，不含读 diff 与跑门；比例用于比较上限，不是绝对 token。",
    ]
    return "\n".join(lines)


def add_base(p) -> None:
    p.add_argument("--base", default="origin/main", help="git 基线（默认 origin/main）")


def main() -> int:
    ap = argparse.ArgumentParser(description="提交前预核：触发判定与报告审计")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("policy", help="判定要不要派判断性预核、哪一档、上限多少")
    sp.add_argument("--paths", nargs="*", help="改动文件列表；不给时读 git diff")
    sp.add_argument("--label", action="append", default=[], help="PR 标签，可重复")
    add_base(sp)
    sp.add_argument("--root", type=Path, default=REPO)

    sa = sub.add_parser("audit", help="汇总预核报告字符、结论次数与发现数")
    sa.add_argument("--dir", type=Path, default=REPO / "proposals" / "reviews")
    sa.add_argument("--cap", type=int, default=6000, help="正文上限模拟（字符，默认 6000）")

    args = ap.parse_args()
    root = getattr(args, "root", REPO).resolve()

    if args.cmd == "policy":
        paths = args.paths
        if not paths:
            paths = git_changed(root, args.base)
            if paths is None:
                print(f"读不到改动清单：先 git fetch <归属仓>，或用 --paths 传改动文件"
                      f"（基线 {args.base}）", file=sys.stderr)
                return 2
            if not paths:
                print(fmt_policy({
                    "mode": "selfcheck", "tier": "selfcheck",
                    "reasons": [f"没有改动（工作区与 {args.base} 一致）"],
                    "caps": None, "checks": ["无改动，不需要预核"], "checklist": [],
                }))
                return 0
        print(fmt_policy(classify(paths, args.label)))
        return 0

    directory = args.dir
    if not directory.is_absolute():
        directory = (root / directory).resolve()
    if not directory.is_dir():
        print(f"读不到报告目录：{directory}", file=sys.stderr)
        return 2
    result = audit_reports(directory, args.cap)
    if not result["files"]:
        print(f"{directory} 下没有预核报告（*pr-body*.md 已跳过）", file=sys.stderr)
        return 2
    print(fmt_audit(result, args.cap))
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    raise SystemExit(main())
