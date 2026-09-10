#!/usr/bin/env python3
"""flow_pool.py —— 流程评测池（eval/flow/）的校验与回放输入生成

用途：评估「加载哪条流程 / 加载多深」对诊断结论的影响（EV-2026-038 第三轮实验与长期指标）。
池结构见 eval/flow/README.md；样本的 ground truth 来自对应 KB case 的 root_cause，
输入来自上游 issue 首帖（不含标题）。

三个子命令（都是确定性的，不联网）：
  --leak-scan   输入文本是否含 ground truth 的决定性词（防泄题；新增样本必跑）
  --prepare     产回放输入 → .flow-replay/<id>.md（可选 --with-flow 附流程全文）
  --stats       池统计（category / 流程覆盖 / 泄露状态）

退出码：--leak-scan 发现泄露 → 非零（可直接接 CI）。
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

POOL_DIR = "eval/flow"
OUT_DIR = ".flow-replay"


def load_pool(root: Path):
    samples = []
    for f in sorted((root / POOL_DIR).glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for s in doc.get("samples") or []:
            s["_file"] = f.name
            samples.append(s)
    return samples


def leak_scan(root: Path):
    """输入不得含 ground truth 的**泄露关键**词（leak_critical）。

    口径：leak_critical = case root_cause 的决定性词 − case symptoms 里出现过的词
    （症状词是观察量，输入里出现是正常的；隐藏机制词出现才是泄题）。
    """
    bad = 0
    for s in load_pool(root):
        text = str((s.get("input") or {}).get("symptoms") or "")
        kws = (s.get("expected") or {}).get("leak_critical") or []
        hits = [k for k in kws if k and k in text]
        if hits:
            bad += 1
            print(f"LEAK {s['id']} ({s['held_out_case']}): {hits[:6]}")
        else:
            print(f"ok   {s['id']} ({s['held_out_case']}) kw={len(kws)}")
    print(f"\nflow_pool --leak-scan: {bad} 条泄露 / {len(load_pool(root))} 条")
    return 1 if bad else 0


def prepare(root: Path, with_flow: bool):
    out = root / OUT_DIR
    out.mkdir(exist_ok=True)
    n = 0
    for s in load_pool(root):
        lines = [
            f"# 回放样本 {s['id']}（{s['held_out_case']}）",
            "",
            f"category: {s['category']}",
            f"held_out_case: {s['held_out_case']}（本轮检索必须排除）",
            "",
            "## 现场（工程师首帖原文）",
            "",
            s["input"]["symptoms"],
            "",
        ]
        flow = s.get("flow_relevant")
        if with_flow and flow:
            p = root / "references" / "methodologies" / f"{flow}.yaml"
            if p.exists():
                lines += ["## 可参考的流程词条（全文）", "", p.read_text(encoding="utf-8"), ""]
        (out / f"{s['id']}.md").write_text("\n".join(lines), encoding="utf-8")
        n += 1
    print(f"flow_pool --prepare: {n} 个输入 → {OUT_DIR}/（with_flow={with_flow}）")


def stats(root: Path):
    from collections import Counter
    samples = load_pool(root)
    print(f"样本数: {len(samples)}")
    print("category:", dict(Counter(s["category"] for s in samples)))
    print("leakage :", dict(Counter(s.get("leakage") for s in samples)))
    with_flow = [s for s in samples if s.get("flow_relevant")]
    print(f"有对应流程: {len(with_flow)}/{len(samples)}")
    print("  按流程:", dict(Counter(s["flow_relevant"] for s in with_flow)))
    gap = [s["held_out_case"] for s in samples if not s.get("flow_relevant")]
    print(f"无流程覆盖（覆盖缺口）: {len(gap)} → {gap}")


def flow_coverage(root: Path):
    """每条 methodology 的「留出检验」覆盖：池内样本哪些被该词条收录（train-on-test），
    哪些未收录（泛化证据）。

    判据（第三轮实验 SCORE-3）：收录样本只能证明"词条记住了自己的 case"；
    未收录样本上的通过记录才是泛化证据。一条流程若 0 条未收录样本 → 其"方法"地位未验证。
    """
    from collections import defaultdict

    flows = {}
    for f in sorted((root / "references" / "methodologies").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        cases = set()
        for s in d.get("sources") or []:
            for c in s.get("cases") or []:
                cases.add(str(c))
        flows[d.get("id", f.stem)] = cases

    pool = load_pool(root)
    rows = []
    for fid, src_cases in flows.items():
        bound = [s for s in pool if s.get("flow_relevant") == fid]
        contaminated = [s["held_out_case"] for s in bound if s["held_out_case"] in src_cases]
        clean = [s["held_out_case"] for s in bound if s["held_out_case"] not in src_cases]
        rows.append((fid, len(src_cases), len(contaminated), len(clean), contaminated, clean))
    rows.sort(key=lambda r: (-r[3], -r[2]))
    print(f"{'flow':42s} {'#srcCases':>9s} {'收录(污染)':>10s} {'未收录(泛化)':>12s}")
    for fid, ns, nc, ncl, cont, cl in rows:
        print(f"{fid:42s} {ns:9d} {nc:10d} {ncl:12d}")
        if cont:
            print(f"    收录样本: {cont}")
        if cl:
            print(f"    未收录样本: {cl}")
    no_clean = [r[0] for r in rows if r[3] == 0 and r[2] > 0]
    if no_clean:
        print("\n⚠ 有被评测绑定但**无未收录样本**的流程（泛化未验证）：")
        for f in no_clean:
            print(f"   - {f}")


def main():
    ap = argparse.ArgumentParser(description="流程评测池校验与回放输入生成")
    ap.add_argument("--leak-scan", action="store_true")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--with-flow", action="store_true", help="回放输入附上流程词条全文")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--flow-coverage", action="store_true", help="每条流程的留出检验覆盖")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()
    if args.leak_scan:
        sys.exit(leak_scan(root))
    if args.prepare:
        prepare(root, args.with_flow)
        return
    if args.stats:
        stats(root)
        return
    if args.flow_coverage:
        flow_coverage(root)
        return
    ap.print_help()


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio

    pin_utf8_stdio()
    main()
