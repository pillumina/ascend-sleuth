#!/usr/bin/env python3
# groom_recheck.py —— 合入前复核：评估是不是还对着**当前集成状态**
#
# 一条本地 groom 不可能看见所有并发草稿。本脚本不假装能看见；它保证的确定性事实：
#   1. marker 字段齐全、枚举合法、没有重复字段；人的批准绑定到同一次评估与同一份内容；
#   2. assessed_commit 存在且是 base 祖先；从它到 base 的相关知识变化 → 过期；
#   3. 每个新增/修改的 Case 都必须有 marker，且提交内容的规范化哈希等于评估内容哈希；
#   4. 人的决定要能授权该动作（reject/defer/covered 不授权新增或修改）；
#   5. PR 新增 case 与 base 前进期间新增 case 有显著词法重叠 → 报可能重复，要求人复核。
#
# 这就是 PR-A 先合入、PR-B 仍带着对基线 commit 的评估那个场景的确定性处置：B 的 base 前进后，
# 本检查会报 stale，要求 B 对新的 main 重跑。它不能替代分支保护（base 必须最新 + 必须
# 跑这条检查），后者是部署前提，见 docs/mechanism/agent-groom.md。
#
# provenance marker（由 groom_record.py --pr-marker 生成，放进 PR body）：
#   <!-- groom-assessment
#   schema: groom-pr/v2
#   draft: <key>
#   case_id: <draft suggested id>
#   submitted_case_id: <final id>
#   category: interrupt
#   assessed_commit: <sha>
#   assessment_id: <sha>
#   assessed_content_sha256: <sha>
#   proposed_novelty: covered
#   candidate_case: CASE-001
#   human_decision: covered
#   human_decision_assessment_id: <sha>
#   human_decision_content_sha256: <sha>
#   review_required: true
#   approval_stale: false
#   -->
#
# 用法：
#   python3 scripts/groom_recheck.py --pr-body-file /tmp/pr.md --base origin/main --head HEAD
#   python3 scripts/groom_recheck.py --pr-body-file /tmp/pr.md --enforce   # 缺 marker 也算失败
#   python3 scripts/groom_recheck.py --pr-body-file /tmp/pr.md --advisory  # 只报不拦（CI 过渡）
#   python3 scripts/groom_recheck.py --post-merge --pr-body-file /tmp/pr.md
#
# 退出码：0 = 无需动作；2 = 过期/未决/可能撞车；3 = 参数或 git 不可用。

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from _lexical import tokens_of
from _stdio import pin_utf8_stdio
from groom_common import (
    canonical_content_sha, dump_json, is_ancestor, normalize_commit,
    now_iso, repo_root, run_git,
)

MARKER_RE = re.compile(r"<!--\s*groom-assessment\s*(.*?)-->", re.S)
CATEGORIES = {"interrupt", "precision", "performance"}


class GitReadError(RuntimeError):
    """无法读取待审核对象时中止检查，不得视为无改动。"""


CLASSIFICATIONS = {"duplicate", "covered", "variant", "new_pattern", "ambiguous"}
HUMAN_DECISIONS = {"new_pattern", "variant", "covered", "defer", "reject", "pending"}
MERGE = {"duplicate", "covered", "variant"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKER_FIELDS = (
    "schema", "draft", "case_id", "submitted_case_id", "category", "assessed_commit",
    "assessment_id", "assessed_content_sha256", "proposed_novelty", "candidate_case",
    "human_decision", "human_decision_assessment_id", "human_decision_content_sha256",
    "review_required",
)


def parse_markers(body: str):
    """解析所有 marker；重复字段视为该 marker 无效，而不是后者覆盖前者。"""
    out = []
    for m in MARKER_RE.finditer(body or ""):
        data, error = {}, None
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            if key in data:
                error = f"重复字段 `{key}`"
            data[key] = value
        if error:
            data["_error"] = error
        out.append(data)
    return out


def parse_marker(body: str):
    markers = parse_markers(body)
    return markers[0] if markers else None


def validate_marker(marker):
    errors = []
    if marker.get("_error"):
        errors.append(marker["_error"])
    for field in REQUIRED_MARKER_FIELDS:
        if field not in marker:
            errors.append(f"缺字段 `{field}`")
    if marker.get("schema") != "groom-pr/v2":
        errors.append(f"schema 必须是 groom-pr/v2（实际 `{marker.get('schema')}`）")
    if marker.get("category") not in CATEGORIES:
        errors.append(f"category 非法：`{marker.get('category')}`")
    novelty = marker.get("proposed_novelty") or ""
    if novelty not in CLASSIFICATIONS:
        errors.append(f"proposed_novelty 非法：`{novelty}`")
    human = marker.get("human_decision") or ""
    if human not in HUMAN_DECISIONS:
        errors.append(f"human_decision 非法：`{human}`")
    review = marker.get("review_required")
    if review not in ("true", "false"):
        errors.append(f"review_required 必须是 true/false（实际 `{review}`）")
    for field in ("assessment_id", "assessed_content_sha256"):
        if marker.get(field) and not HEX64.match(marker[field]):
            errors.append(f"{field} 必须是 64 位小写十六进制")
    if human != "pending":
        for field in ("human_decision_assessment_id", "human_decision_content_sha256"):
            if not HEX64.match(marker.get(field) or ""):
                errors.append(f"{field} 缺失或不是 64 位十六进制")
        if marker.get("human_decision_assessment_id") != marker.get("assessment_id"):
            errors.append("human_decision_assessment_id 与 assessment_id 不一致（批准不是针对这次评估）")
        if marker.get("human_decision_content_sha256") != marker.get("assessed_content_sha256"):
            errors.append("human_decision_content_sha256 与 assessed_content_sha256 不一致"
                          "（批准不是针对这份内容）")
    if human in ("duplicate", "covered", "variant") and not marker.get("candidate_case"):
        errors.append(f"human_decision={human} 时 candidate_case 不能为空")
    if not marker.get("assessed_commit"):
        errors.append("assessed_commit 为空")
    return errors


def _show(repo: Path, commit: str, rel: str, required: bool = False):
    proc = run_git(["show", f"{commit}:{rel}"], cwd=repo, check=False)
    if proc.returncode != 0:
        if required:
            raise GitReadError(f"读取已改动文件 {commit}:{rel} 失败：{proc.stderr.strip()}")
        return None
    try:
        import io
        import yaml
        return yaml.safe_load(io.StringIO(proc.stdout))
    except Exception as exc:
        if required:
            raise GitReadError(f"解析已改动文件 {commit}:{rel} 失败：{exc}") from exc
        return None


def _case_of(data):
    if isinstance(data, dict) and isinstance(data.get("cases"), list) and data["cases"]:
        c = data["cases"][0]
        return c if isinstance(c, dict) else None
    return None


def _case_text(case):
    if not case:
        return ""
    parts = [str(case.get("title") or ""), str(case.get("root_cause") or ""),
             str(case.get("fix") or "")]
    for s in (case.get("symptoms") or []):
        parts.append(str(s))
    for step in (case.get("diagnosis") or [])[:4]:
        if isinstance(step, dict):
            parts += [str(step.get("command_template") or ""), str(step.get("expected") or "")]
    return "\n".join(parts)


def _diff_cases(repo: Path, older: str, newer: str, diff_filter=None):
    args = ["diff", "--name-status"]
    if diff_filter and diff_filter != "A":
        args.append(f"--diff-filter={diff_filter}")
    args += [f"{older}..{newer}", "--", "knowledge"]
    proc = run_git(args, cwd=repo, check=False)
    out = []
    if proc.returncode != 0:
        raise GitReadError(f"git diff {older}..{newer} 失败：{proc.stderr.strip()}")
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        if not path.endswith(".yaml") or "_index" in path:
            continue
        if diff_filter == "A" and not (status.startswith("A") or status.startswith("R")):
            # git 可能把"删一条 + 加一条内容相近的 case"识别成 rename（R060）。
            # 对"新增"的判定来说，rename 的目标路径同样是新增，不能漏。
            continue
        out.append((status, path))
    return out


def find_case_file(repo: Path, commit: str, case_id: str):
    """在 commit 的 knowledge/ 里按 id 找文件（bounded：只扫索引总表，不读全库正文）。"""
    data = _show(repo, commit, "knowledge/_index.yaml")
    if isinstance(data, dict):
        for ns, cells in (data.get("namespaces") or {}).items():
            for cat, entries in (cells or {}).items():
                for e in entries or []:
                    if str(e.get("id")) == case_id:
                        return str(e.get("file") or "")
    return None


def compare_new_cases(repo: Path, assessed: str, base: str, head: str):
    """PR 新增 case vs base 前进期间新增 case 的词法重叠（只报候选，不判重）。"""
    added_main = [(st, p) for st, p in _diff_cases(repo, assessed, base, "A")]
    added_pr = [(st, p) for st, p in _diff_cases(repo, base, head, "A")]
    if not added_main or not added_pr:
        return []
    main_cases = []
    for _st, path in added_main:
        case = _case_of(_show(repo, base, path, required=True))
        if case and case.get("id"):
            main_cases.append((case.get("id"), path, _case_text(case)))
    out = []
    for _st, path in added_pr:
        case = _case_of(_show(repo, head, path, required=True))
        if not case or not case.get("id"):
            continue
        pr_tokens = tokens_of(_case_text(case))
        for cid, cpath, ctext in main_cases:
            main_tokens = tokens_of(ctext)
            overlap = pr_tokens & main_tokens
            if len(overlap) >= 1 or _same_sig(case, ctext):
                out.append({
                    "pr_case": str(case.get("id")),
                    "main_case": str(cid),
                    "main_file": cpath,
                    "token_overlap": sorted(overlap)[:8],
                    "note": "base 前进期间新增的 case 与 PR 新增 case 有共同字面量——人复核是否同一问题",
                })
    return out


def _same_sig(case, other_text):
    qc = case.get("quickly_check") or {}
    for branch in qc.values():
        exp = str((branch or {}).get("expected") or "")
        if exp.startswith("regex:"):
            for alt in exp[len("regex:"):].split("|"):
                alt = alt.strip()
                if len(alt) >= 6 and alt.lower() in (other_text or "").lower():
                    return True
    return False


def _path_in_commit(repo: Path, commit: str, rel: str) -> bool:
    return run_git(["cat-file", "-e", f"{commit}:{rel}"], cwd=repo, check=False).returncode == 0


def _changed_cases(repo: Path, base: str, head: str):
    """PR 新增/修改的 Case（只认 A/M/R；删除不在本流程授权范围内）。"""
    out = []
    for status, path in _diff_cases(repo, base, head):
        if status[0] not in ("A", "M", "R"):
            continue
        case = _case_of(_show(repo, head, path, required=True))
        if not case or not case.get("id"):
            raise GitReadError(f"已改动文件 {head}:{path} 缺少可读取的 Case 或 id")
        if case and case.get("id"):
            out.append({"status": status[0], "path": path, "case": case,
                        "id": str(case.get("id")),
                        "is_new": status[0] == "A" or (status[0] == "R"
                                                        and not _path_in_commit(repo, base, path)),
                        "content_sha256": canonical_content_sha(case)})
    return out


def _marker_matches_case(marker, case):
    declared = marker.get("submitted_case_id") or marker.get("case_id") or ""
    return declared == case["id"]


def _authorization_errors(marker, case):
    human = marker.get("human_decision")
    if human in ("reject", "defer"):
        return [f"人的决定是 {human}，不授权任何内容提交"]
    if human == "pending":
        return ["人的决定仍是 pending，PR 没有可执行的授权"]
    if human == "covered":
        return ["人的决定是 covered，不授权新增/修改 Case"]
    if human == "variant":
        if case["is_new"]:
            return ["variant 应并入已有 Case，不能以新增文件形式提交"]
        cand = marker.get("candidate_case") or ""
        if cand and cand != case["id"]:
            return [f"variant 的候选是 {cand}，但提交的是 {case['id']}"]
        return []
    if human == "new_pattern":
        if not case["is_new"]:
            return ["new_pattern 授权的是新增 Case，但 PR 修改了已有 Case"]
        return []
    return [f"未知授权动作 `{human}`"]


def _check(body, repo: Path, base_ref: str, head_ref: str, enforce_marker: bool,
          post_merge: bool = False):
    findings = []

    def add(severity, code, message, **extra):
        findings.append({"severity": severity, "code": code, "message": message, **extra})

    base_resolved = normalize_commit(repo, base_ref)
    head_resolved = normalize_commit(repo, head_ref)
    base, head = base_resolved, head_resolved
    if not base or not head:
        add("error", "git-ref-unavailable",
            f"取不到 base={base_ref!r} / head={head_ref!r} 的 commit；先 fetch 或修正引用。")
        return findings, {"base": base, "head": head}

    if post_merge:
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run([sys.executable, "scripts/build_index.py", "--check"], cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["索引检查失败"]
            add("error", "post-merge-index-stale", f"合入后索引与内容不一致：{tail[0]}")
        else:
            add("info", "post-merge-index-ok", "合入后索引覆盖检查通过。")

    markers = parse_markers(body)
    if not markers:
        add("warning" if not enforce_marker else "error", "missing-marker",
            "PR 正文没有 groom-assessment provenance。本地 groom 的结论没有随 PR 走到 CI。"
            + ("" if not enforce_marker else "（--enforce：缺 marker 即失败）"))
        return findings, {"base": base, "head": head, "marker": None}

    valid_markers = []
    for marker in markers:
        errors = validate_marker(marker)
        if errors:
            add("error", "marker-invalid",
                "provenance marker 不完整或字段非法：" + "；".join(errors[:6]),
                marker={k: v for k, v in marker.items() if k != "_error"})
            continue
        assessed = marker["assessed_commit"]
        assessed_resolved = normalize_commit(repo, assessed)
        if not assessed_resolved:
            add("error", "assessment-commit-missing",
                f"marker 记录的 assessed_commit {assessed[:12]} 在本仓库不存在"
                f"（force-push / 浅克隆？）")
            continue
        if not is_ancestor(repo, assessed_resolved, base):
            add("error", "assessment-not-ancestor",
                f"评估 commit {assessed_resolved[:12]} 不是 base {base[:12]} 的祖先——"
                f"PR 分支或 base 被改写过，必须对当前 base 重跑 groom。")
            continue
        marker["_assessed_resolved"] = assessed_resolved
        valid_markers.append(marker)

    changed_cases = _changed_cases(repo, base, head)
    covered_ids = set()
    for case in changed_cases:
        matching = [m for m in valid_markers if _marker_matches_case(m, case)]
        if not matching:
            add("error", "case-without-provenance",
                f"PR 提交/修改了 {case['id']}，但找不到覆盖它的 groom provenance marker。",
                case=case["id"], path=case["path"])
            continue
        if len(matching) > 1:
            add("error", "duplicate-provenance",
                f"{case['id']} 有多份 provenance marker（{len(matching)} 份）——先删掉旧的，不要叠放。",
                case=case["id"])
        marker = matching[0]
        if marker["category"] != case["case"].get("category"):
            add("error", "category-mismatch",
                f"{case['id']} 的 marker 分类与提交内容不一致，不能据此缩小复核范围。",
                case=case["id"])
        covered_ids.add(id(marker))
        if marker.get("assessed_content_sha256") != case["content_sha256"]:
            add("error", "content-mismatch",
                f"{case['id']} 的提交内容与评估时绑定的内容不一致（assessed "
                f"{str(marker.get('assessed_content_sha256'))[:12]} ≠ 实际 "
                f"{case['content_sha256'][:12]}）——评估没有授权这份内容。",
                case=case["id"], path=case["path"])
        for issue in _authorization_errors(marker, case):
            add("error", "decision-does-not-authorize", f"{case['id']}：{issue}",
                case=case["id"])

    # 没有对应内容的新增/合并授权：说明 marker 声称的动作没有发生，不能当作已授权
    for marker in valid_markers:
        if id(marker) in covered_ids:
            continue
        human = marker.get("human_decision")
        if human in ("new_pattern", "variant"):
            add("error", "authorization-without-content",
                f"marker 授权 {human}，但 PR 没有对应的新增/修改 Case。")
        elif human in ("reject", "defer"):
            add("error", "decision-does-not-authorize",
                f"人的决定是 {human}，不授权任何内容提交。")

    # stale：对每个有效 marker 检查 relevant knowledge 是否在评估后变化
    for marker in valid_markers:
        assessed_resolved = marker["_assessed_resolved"]
        category = marker.get("category") or ""
        candidate = marker.get("candidate_case") or ""
        diff = run_git(["diff", "--name-only", f"{assessed_resolved}..{base}", "--", "knowledge"],
                       cwd=repo, check=False)
        if diff.returncode != 0:
            raise GitReadError(f"读取评估后的知识变更失败：{diff.stderr.strip()}")
        changed = [p for p in diff.stdout.splitlines()
                   if p.strip() and "knowledge/_index" not in p.replace("\\", "/")]
        relevant = changed
        if category:
            relevant = [p for p in changed
                        if f"/{category}/" in p or p.startswith("knowledge/common/")]
        if candidate:
            cand_file = find_case_file(repo, base, candidate)
            if not cand_file:
                add("error", "candidate-missing",
                    f"marker 指向的候选 {candidate} 在当前 base 的索引里找不到——"
                    f"候选被改名/删除/归档，评估已过期。")
            elif cand_file in changed:
                relevant = sorted(set(relevant) | {cand_file})
        if relevant:
            add("error", "assessment-stale",
                f"从评估 commit {assessed_resolved[:12]} 到 base {base[:12]}，相关 knowledge 变了 "
                f"{len(relevant)} 个文件——对旧 main 的结论不能直接合入，必须重跑 groom。",
                files=relevant[:20])
        elif changed:
            add("info", "knowledge-changed-elsewhere",
                f"评估后知识库有 {len(changed)} 个文件变化，但不在本评估的分类/候选范围内"
                f"（按 category / common / 候选自身过滤）。")

    possible = compare_new_cases(
        repo, valid_markers[0]["_assessed_resolved"] if valid_markers else base, base, head)
    for item in possible:
        add("error", "possible-duplicate-after-merge",
            f"PR 新增 {item['pr_case']} 与 base 期间新增 {item['main_case']} 有共同字面量 "
            f"{item['token_overlap']}——人复核是否同一问题（本检查不判重）。",
            detail=item)

    return findings, {"base": base, "head": head,
                      "markers": [{k: v for k, v in m.items() if not k.startswith("_")}
                                  for m in valid_markers],
                      "changed_cases": [c["id"] for c in changed_cases]}


def check(body, repo: Path, base_ref: str, head_ref: str, enforce_marker: bool,
          post_merge: bool = False):
    try:
        return _check(body, repo, base_ref, head_ref, enforce_marker, post_merge)
    except GitReadError as exc:
        return [{"severity": "error", "code": "git-read-failed", "message": str(exc)}], {
            "base": base_ref, "head": head_ref}


def main():
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="Groom 合入前复核（stale assessment / 并发 PR）")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--pr-body-file", default=None)
    ap.add_argument("--pr-body", default=None)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--enforce", action="store_true", help="缺 marker / 未决也失败")
    ap.add_argument("--advisory", action="store_true", help="只报告，不改变退出码（CI 过渡用）")
    ap.add_argument("--post-merge", action="store_true", help="另跑索引覆盖检查")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = repo_root(Path(args.repo).resolve() if args.repo else Path.cwd())
    if args.pr_body_file:
        body = Path(args.pr_body_file).read_text(encoding="utf-8")
    elif args.pr_body is not None:
        body = args.pr_body
    else:
        body = sys.stdin.read()

    findings, ctx = check(body, root, args.base, args.head, args.enforce, args.post_merge)
    blocking = [f for f in findings if f["severity"] == "error"]
    result = {
        "schema": "groom-recheck/v1",
        "checked_at": now_iso(),
        "repo": str(root),
        "base": ctx.get("base"),
        "head": ctx.get("head"),
        "marker": ctx.get("marker"),
        "findings": findings,
        "ok": not blocking,
        "advisory": args.advisory,
    }
    if args.json:
        print(dump_json(result))
    else:
        print(f"Groom 合入前复核：base {str(ctx.get('base'))[:12]} · head {str(ctx.get('head'))[:12]}")
        if not findings:
            print("  通过：没有过期评估或潜在并发撞车。")
        for f in findings:
            label = {"error": "✗", "warning": "⚠", "info": "·"}.get(f["severity"], "·")
            print(f"  {label} [{f['code']}] {f['message']}")
            for path in f.get("files") or []:
                print(f"      - {path}")
    if args.advisory:
        return 3 if any(f["code"].startswith("git-") for f in findings) else 0
    return 0 if not blocking else 2


if __name__ == "__main__":
    sys.exit(main())
