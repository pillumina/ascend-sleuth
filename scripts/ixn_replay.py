#!/usr/bin/env python3
# ixn_replay.py —— 交互型 replay 评测 harness（机制决议 EV-2026-012）
#
# 测 diagnose 的"交互面"（追问 / 信息充分性 / 过早结论），与单发 S2（检索/内容面）
# 正交。设计文档 docs/evolution-ixn-replay.md（口径经 2026-09 本地 pilot N=3 验证，
# 验证数据与结论内联于该文档 §4/§7）。
#
# harness 只做数据与评分；每段"诊断 + 追问"由 agent 执行（读 feed → 走 diagnose skill
# → 写 result），不自动（与 s2_replay 同构）。目录规范（持久化模型同 eval/s2/）：
#   eval/ixn-arena/<issue>/        **入库规格**（随 PR 审，可复用不重建）：gold.yaml
#                                 （held_out/resolution_ref/maintainer_questions(合理下限
#                                 ground truth)/decisive_fields/resolution_summary）
#                                 + stage-0.md … stage-N.md（分期 feed，S0 不含决定性答案）
#   .ixn-replay/<issue>/           本地：issue.md/comments.md（真实正文，gh 拉取）+
#                                 stage-k.result.yaml（agent 每段产物）+ conclusion.yaml
#                                 + score.yaml（评分输出）
#
# 用法：
#   python3 scripts/ixn_replay.py --prepare 2424 --repo vllm-project/vllm-ascend
#       拉 issue+评论 → .ixn-replay/<issue>/issue.md + comments.md（正文本地；gold/feed 走
#       eval/ixn-arena 提交）
#   python3 scripts/ixn_replay.py --score 2424
#       读 gold（入库权威源）+ 本地各段 result + conclusion → score.yaml + 人读摘要
#       指标：追问召回（∪questions ∩ ground truth 字段）/ 决定性字段在链 /
#       过早结论率 / 结论一致（需人工核验，v1 不自动判）
#   python3 scripts/ixn_replay.py --aggregate
#       汇总全部有 score.yaml 的样本成表
#
# 评分口径（pilot 数据校准，详见设计文档 §4）：ground truth 是维护者追问的"合理下限
# 非最优"；多报告者线程 ground truth 集合化；决定性字段按"链"不按首轮。

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

RUN_DIR = ".ixn-replay"
GOLD_FIELDS = ["held_out", "resolution_ref", "resolution_summary",
               "maintainer_questions", "decisive_fields"]


def sample_dir(root, issue):
    return root / RUN_DIR / str(issue)


def fetch_issue(repo, issue):
    """gh api 拉 issue body 与评论；返回 (body, comments_list)。"""
    body = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{issue}", "--jq", ".body"],
        capture_output=True, text=True, check=True).stdout
    comments = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{issue}/comments?per_page=100",
         "--jq", "[.[]|{user:.user.login,created:.created_at,body}]"],
        capture_output=True, text=True, check=True).stdout
    return body, json.loads(comments)


def cmd_prepare(issue, repo, root):
    if not repo:
        print("--prepare 需要 --repo user/repo（gh 拉取上游线程）", file=sys.stderr)
        return 2
    d = sample_dir(root, issue)
    d.mkdir(parents=True, exist_ok=True)
    try:
        body, comments = fetch_issue(repo, issue)
    except subprocess.CalledProcessError as e:
        print(f"gh 拉取失败（issue 不存在或网络）：{e}", file=sys.stderr)
        return 1
    (d / "issue.md").write_text(body or "", encoding="utf-8")
    cm = "\n\n".join(f"--- [{c['user']}] {c['created']} ---\n{c.get('body','')}"
                     for c in comments)
    (d / "comments.md").write_text(cm, encoding="utf-8")
    gold_tpl = {
        "_comment": "交互 replay 标注模板。maintainer_questions/decisive_fields 每项为 "
                    "{field: 字段名, keywords: [判字词]}；decisive_fields = 改变结论走向的字段。"
                    "维护者追问是合理下限非最优；多报告者线程请集合化。",
        "issue": int(issue), "repo": repo, "held_out": None,
        "resolution_ref": "", "resolution_summary": "",
        "maintainer_questions": [], "decisive_fields": [],
    }
    (d / "gold.yaml").write_text(
        yaml.safe_dump(gold_tpl, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"已生成 {d}/：issue.md / comments.md / gold.yaml（待补标注 + 切 stage-*.md）")
    print("下一步：补 gold.yaml（held_out/维护者追问/决定性字段）→ 按真实披露切 stage-*.md"
          "（S0 不含决定性字段答案）→ agent 逐段运行写 stage-k.result.yaml → --score")
    return 0


def _field_hits(fields, text):
    """fields: [{field, keywords}]；text: 全部追问拼接。返回 (命中集, 未命中集)。"""
    t = (text or "").casefold()
    hit, miss = [], []
    for f in fields or []:
        name = f.get("field", "")
        kws = [k for k in (f.get("keywords") or [name]) if len(k) >= 2]
        if not kws:
            miss.append(name); continue
        if any(k.casefold() in t for k in kws):
            hit.append(name)
        else:
            miss.append(name)
    return hit, miss


ARENA_DIR = "eval/ixn-arena"     # 入库规格：gold + stage feed（持久化，随 PR 审；模型同 eval/s2/）
#                                # .ixn-replay/（本地）：真实正文/评论 + run 结果 + score


def arena_gold_path(root, issue):
    """gold 权威源：入库 eval/ixn-arena/<issue>/gold.yaml，回退本地 .ixn-replay/。"""
    p = root / ARENA_DIR / str(issue) / "gold.yaml"
    if p.exists():
        return p
    return root / RUN_DIR / str(issue) / "gold.yaml"


def cmd_score(issue, root):
    d = sample_dir(root, issue)
    gp = arena_gold_path(root, issue)
    if not gp.exists():
        print(f"gold 缺失（入库 {root / ARENA_DIR}/{issue}/gold.yaml 或本地 .ixn-replay）: {gp}",
              file=sys.stderr)
        return 1
    d.mkdir(parents=True, exist_ok=True)
    gold = yaml.safe_load(gp.read_text(encoding="utf-8"))
    # 收集各段 result（本地 .ixn-replay/<issue>/）
    stages = []
    for f in sorted(d.glob("stage-*.result.yaml")):
        r = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        stages.append((f.stem, r))
    conclusion = {}
    cf = d / "conclusion.yaml"
    if cf.exists():
        conclusion = yaml.safe_load(cf.read_text(encoding="utf-8")) or {}
    all_questions = " ".join(
        str(r.get("questions") or "") for _, r in stages)
    q_join = re.sub(r"[\[\]'\"\n]", " ", all_questions)

    score = {"issue": int(issue), "stages_run": len(stages)}
    # 1) 追问召回：maintainer_questions ∪ decisive_fields
    mq_hit, mq_miss = _field_hits(gold.get("maintainer_questions"), q_join)
    df_hit, df_miss = _field_hits(gold.get("decisive_fields"), q_join)
    union = (gold.get("maintainer_questions") or []) + (gold.get("decisive_fields") or [])
    u_hit = set(mq_hit) | set(df_hit)
    u_all = {f.get("field", "") for f in union if f.get("field")}
    score["question_recall"] = {
        "hit": sorted(u_hit), "miss": sorted(u_all - u_hit),
        "rate": round(len(u_hit & u_all) / len(u_all), 3) if u_all else None}
    # 2) 决定性字段在链（不要求首轮）
    score["decisive_in_chain"] = {"found": sorted(df_hit), "missing": sorted(df_miss)}
    # 3) 过早结论
    prem = [s for s, r in stages if r.get("premature_conclusion")]
    score["premature_stages"] = prem
    # 4) 结论一致：v1 不做自动判定（resolution 多阶段），留人工核验
    score["conclusion_match"] = {"auto": "unverified",
                                 "note": "需人工对照 resolution_summary 与 conclusion.yaml"}
    (d / "score.yaml").write_text(
        yaml.safe_dump(score, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"== {issue} 评分（stages={len(stages)}，held_out={gold.get('held_out')}）==")
    rr = score["question_recall"]
    print(f"  追问召回 {len(rr['hit'])}/{len(rr['hit']) + len(rr['miss'])}"
          + (f"（{rr['rate']:.0%}）" if rr["rate"] is not None else "") + f" 命中={rr['hit']}"
          + (f" 未命中={rr['miss']}" if rr["miss"] else ""))
    dc = score["decisive_in_chain"]
    print(f"  决定性字段在链  found={dc['found']}" + (f" missing={dc['missing']}" if dc["missing"] else ""))
    print(f"  过早结论阶段 {prem if prem else '无'}")
    print(f"  结论一致：需人工核验（{d / 'conclusion.yaml'} vs gold.resolution_summary）")
    return 0


def cmd_aggregate(root):
    rows = []
    for d in sorted((root / RUN_DIR).glob("*/")):
        sf = d / "score.yaml"
        if not sf.exists():
            continue
        s = yaml.safe_load(sf.read_text(encoding="utf-8")) or {}
        rr = s.get("question_recall") or {}
        rows.append((d.name, rr.get("rate"), rr.get("hit"), rr.get("miss"),
                     s.get("decisive_in_chain", {}).get("missing"),
                     s.get("premature_stages")))
    if not rows:
        print("（无已评分样本：先 --score）")
        return 0
    print("| issue | 追问召回率 | 命中 | 未命中 | 决定性字段缺 | 过早结论 |")
    print("|---|---|---|---|---|---|")
    for issue, rate, hit, miss, dc_miss, prem in rows:
        r = f"{rate:.0%}" if isinstance(rate, (int, float)) else "-"
        print(f"| {issue} | {r} | {hit or '-'} | {miss or '-'} | {dc_miss or '-'} | {prem or '-'} |")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="交互型 replay 评测 harness（机制 EV-2026-012；文档 docs/evolution-ixn-replay.md）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare", metavar="ISSUE", help="拉 issue+评论，生成素材与 gold 模板")
    g.add_argument("--score", metavar="ISSUE", help="读 gold + 各段 result，出分")
    g.add_argument("--aggregate", action="store_true", help="汇总已评分样本")
    ap.add_argument("--repo", default="", help="上游仓库 user/repo（--prepare 用）")
    ap.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if args.prepare:
        return cmd_prepare(args.prepare, args.repo, root)
    if args.score:
        return cmd_score(args.score, root)
    return cmd_aggregate(root)


if __name__ == "__main__":
    sys.exit(main())
