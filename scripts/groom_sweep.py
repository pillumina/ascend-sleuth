#!/usr/bin/env python3
# groom_sweep.py —— 每日自动收尾：查合入 → 取证 → 收尾 → 清理。
#
# 为什么需要它：自动任务与 groom 开场都要做同一件事，但不应各自实现一遍判断。
# 本命令是唯一入口：任务只负责定时，groom 开场与 Copilot 触发也调它。
#
# 幂等：已收尾的草稿由 `groom_close_after_merge` 跳过，cleanup 只删匹配记录；
# 连续跑两次不会重复写 trace 或 close-log。
#
# 取证来源按顺序：台账 entry 的 `body` / `body_path` / `merge_commit`，
# 其次平台适配器的 `fetch()`（如 GitHub 的 `gh pr view --json body,mergeCommit`）。
# 两者都没有就报缺失，不猜。
#
# 用法：
#   python3 scripts/groom_sweep.py --repo <主检出绝对路径> --dry-run
#   python3 scripts/groom_sweep.py --repo <主检出绝对路径> --apply --fetch
#
# 退出码：0 = 正常（含无事可做与证据缺失）；2 = 有收尾失败。

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from _stdio import pin_utf8_stdio
from groom_common import dump_json, now_iso, repo_root, shared_inbox
import pr_status


def _run(cmd, root: Path, timeout: int = 300):
    return subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _check_all(root: Path) -> dict:
    """调 pr_status 刷新 open/unknown 的 PR 状态；保留错误码供调用方决定是否继续。"""
    script = root / "scripts" / "pr_status.py"
    if not script.is_file():
        return {"ok": False, "code": "E_NO_SCRIPT", "message": "检出里没有 pr_status.py",
                "checked": []}
    try:
        proc = _run([sys.executable, str(script), "--root", str(root),
                     "--check-all", "--json"], root, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "E_TIMEOUT", "message": "check-all 超时", "checked": []}
    payload = {}
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        payload = {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(error.get("code") or "")
    if not code:
        # 非零退出且没有结构化错误时按退出码归类：2 是参数错，1 是内部错。
        if proc.returncode == 2:
            code = "E_ARGS"
        elif proc.returncode == 1:
            code = "E_INTERNAL"
        elif proc.returncode != 0:
            code = "E_QUERY"
    message = (str(error.get("message") or "")
               or (proc.stderr or proc.stdout).strip()[:500])
    return {"ok": proc.returncode == 0 and bool(payload.get("ok")), "code": code,
            "message": message, "checked": payload.get("checked") or []}


#: 这些查询结果表示台账没有可靠落盘，本轮不能拿它决定收哪些项。
_FATAL_CHECK_CODES = {"E_CAS", "E_LEDGER", "E_ARGS", "E_INTERNAL", "E_NO_SCRIPT"}


def _cleaned_heads(inbox: Path) -> set:
    """cleanup-log.jsonl 里成功清理过的合入提交。"""
    path = inbox / ".groom" / "cleanup-log.jsonl"
    done = set()
    if not path.is_file():
        return done
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return done
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict) or not obj.get("head"):
            continue
        if obj.get("complete") is True:
            done.add(str(obj["head"]))
            continue
        if "complete" in obj:
            continue
        # 旧日志没有 complete 字段：退回保守判断，避免把残留当成已完成。
        deleted = obj.get("deleted") if isinstance(obj.get("deleted"), dict) else {}
        if (obj.get("ok") and not deleted.get("kept")
                and not obj.get("skipped_snapshots") and not obj.get("findings")):
            done.add(str(obj["head"]))
    return done


def _pr_ident(entry: dict) -> tuple:
    """PR 身份优先从登记链接取：主机、完整仓库路径、链接编号。

    台账字段只在链接缺失时兜底，不参与归组；否则一条台账的仓库写错，
    就能把同一 PR 的保护记录拆到另一组，绕过组内校验。
    """
    parsed = pr_status.parse_remote_url(str(entry.get("url") or ""))
    repo = (_normalize_repo(parsed.get("repo"))
            or _normalize_repo(entry.get("repo")))
    number = _pr_number_from_url(entry.get("url")) or str(entry.get("number") or "")
    return (str(parsed.get("host") or "").lower(), repo, number)


def _groups(merged: dict) -> list:
    """按主机、仓库、PR 编号归组；同一 PR 的多份草稿只执行一次整份 body。"""
    groups = {}
    for key, entry in sorted(merged.items()):
        groups.setdefault(_pr_ident(entry), []).append(key)
    return groups


def _pr_number_from_url(value: str) -> str:
    """从 PR/MR 链接的路径里取编号；查询参数与锚点不算。"""
    text = str(value or "").split("?", 1)[0].split("#", 1)[0]
    for marker in ("/-/merge_requests/", "/merge_requests/", "/pulls/", "/pull/"):
        if marker in text:
            digits = re.match(r"(\d+)", text.split(marker, 1)[1])
            if digits:
                return digits.group(1)
    return ""


def _identity_error(entry: dict) -> str:
    """台账的仓库与编号都要和登记链接一致；任一项冲突就停止取证。"""
    number = str(entry.get("number") or "").strip()
    url_number = _pr_number_from_url(entry.get("url"))
    if number and url_number and number != url_number:
        return f"台账编号 {number} 与登记链接编号 {url_number} 不一致"
    ledger_repo = _normalize_repo(entry.get("repo"))
    url_repo = _normalize_repo(
        pr_status.parse_remote_url(str(entry.get("url") or "")).get("repo"))
    if ledger_repo and url_repo and ledger_repo != url_repo:
        return f"台账仓库 {ledger_repo} 与登记链接仓库 {url_repo} 不一致"
    return ""


def _adapter_fetch(entry: dict) -> tuple:
    """按解析后的 PR 主机找适配器，并核对返回证据属于同一 PR。"""
    url = str(entry.get("url") or "")
    parsed = pr_status.parse_remote_url(url)
    host = str(parsed.get("host") or "").lower()
    if not host:
        return None, "无法解析 PR 主机"
    entry_number = str(entry.get("number") or "").strip()
    url_number = _pr_number_from_url(url)
    identity = _identity_error(entry)
    if identity:
        return None, identity + "，不采用平台证据"
    want_number = entry_number or url_number
    for adapter in pr_status.load_adapters():
        if host not in [str(item).lower() for item in (adapter.get("hosts") or [])]:
            continue
        module = adapter.get("module")
        fn = getattr(module, "fetch", None) if module else None
        if callable(fn):
            try:
                fetched = fn(entry)
            except Exception as exc:
                return None, f"取证失败：{exc}"
            if not isinstance(fetched, dict) or not fetched.get("ok"):
                return fetched, None
            got_url = str(fetched.get("url") or "")
            if got_url:
                got = pr_status.parse_remote_url(got_url)
                got_number = _pr_number_from_url(got_url)
                if (str(got.get("host") or "").lower() != host
                        or _normalize_repo(got.get("repo"))
                        != _normalize_repo(parsed.get("repo"))
                        or (want_number and got_number and got_number != want_number)):
                    return None, "平台返回的证据不属于同一 PR"
            return fetched, None
        return None, f"适配器 {adapter.get('id')} 不支持取证"
    return None, "没有匹配的取证适配器"


def _normalize_repo(value: str) -> str:
    """完整仓库路径，去掉查询串、锚点与只属于网页地址的 MR/PR 后缀。"""
    text = str(value or "").strip().strip("/").split("?", 1)[0].split("#", 1)[0]
    for marker in ("/-/merge_requests/", "/merge_requests/", "/pull/", "/pulls/"):
        if marker in text:
            text = text.split(marker, 1)[0]
            break
    return text.lower()


def _match_remote(root: Path, entry: dict) -> str:
    """返回与台账 PR 对应的 remote 名：主机与完整仓库路径都要对得上。

    只按仓库名或只比前两段路径时，GitHub 与 GitLab 的同名仓库、同一组下的
    不同项目会串台，必须用完整路径。
    """
    repo = _normalize_repo(entry.get("repo"))
    target = pr_status.parse_remote_url(str(entry.get("url") or ""))
    want_host = str(target.get("host") or "").lower()
    want_repo = _normalize_repo(target.get("repo")) or repo
    proc = _run(["git", "remote", "-v"], root)
    if proc.returncode != 0:
        return ""
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] != "(fetch)":
            # 只用 fetch URL 选远端：push URL 可能指向另一个仓库，
            # 但 refs/remotes/<remote>/... 是从 fetch URL 拉下来的。
            continue
        parsed = pr_status.parse_remote_url(parts[1])
        got_repo = _normalize_repo(parsed.get("repo"))
        got_host = str(parsed.get("host") or "").lower()
        if want_repo and got_repo != want_repo:
            continue
        if want_host and got_host and got_host != want_host:
            continue
        return parts[0]
    return ""


def _git_merge(root: Path, entry: dict) -> tuple:
    """用 git 找合入提交：只认提交标题，合并提交优先，不能确认仓库就不猜。

    B 方案：内网外网都只要 git fetch 通，就能判断合入并拿到合入提交；
    平台 CLI 只在 git 匹配不到时兜底。
    """
    repo = str(entry.get("repo") or "")
    remote = _match_remote(root, entry) if repo else "origin"
    if repo and not remote:
        return "", f"本地 clone 的 remote 与台账 repo 不一致（{repo}）"
    base = str(entry.get("base") or "").strip()
    if not base:
        ref = f"refs/remotes/{remote}/main"
    else:
        # 统一解析到匹配 remote 的完整跟踪引用；简写会按 refs/heads/... 解析到
        # 同名本地分支，所以校验与取证都只用 refs/remotes/...。
        if base.startswith("refs/remotes/"):
            parts = base.split("/", 3)
            branch = parts[3] if len(parts) == 4 else base
        else:
            prefix = base.split("/", 1)[0] if "/" in base else ""
            branch = base.split("/", 1)[1] if prefix in ("origin", "upstream", "fork") else base
        ref = f"refs/remotes/{remote}/{branch}"
    proc = _run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], root)
    if proc.returncode != 0:
        if entry.get("repo"):
            return "", f"远端引用缺失：{ref}"
        # 无 repo 的调用方明确要求本地或其他 ref：保留原值。
        ref = str(entry.get("base") or "").strip()
    base = ref
    number = str(entry.get("number") or "")
    if number:
        # --grep 会命中正文；这里只认提交标题，且标题必须以 (#N) / !N 结尾，
        # 中间提到或正文提到都不算合入证据。
        for pattern in (f"(#{number})", f"!{number}"):
            proc = _run(["git", "log", base, "--format=%H%x00%s",
                         "--fixed-strings", "--grep", pattern], root)
            if proc.returncode != 0:
                continue
            for line in proc.stdout.splitlines():
                sha, _, subject = line.partition("\x00")
                if re.search(rf"\(#{number}\)\s*$|!{number}\s*$", subject):
                    return sha.strip(), ""
    head = str(entry.get("head") or "")
    if head:
        proc = _run(["git", "merge-base", "--is-ancestor", head, base], root)
        if proc.returncode == 0:
            # 只取合并提交：登记分支头之后又加的提交不能当成合入点。
            proc = _run(["git", "rev-list", "--ancestry-path", f"{head}..{base}",
                         "--merges"], root)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip().splitlines()[-1], ""
            # fast-forward：没有合并提交时，head 本身就是合入点。
            return head, ""
    return "", "git 里找不到合入提交（可能还没 fetch，或 PR 号匹配不到）"


def _evidence(root: Path, entry: dict) -> tuple:
    """返回 (body, merge_commit, 原因, 来源)。body 可空（本地评估就是标记），merge 必须有。

    来源决定能否自动写：ledger（台账已有 SHA）与 platform（适配器确认 merged 并返回
    SHA）可信；git 只能推断，默认停在疑似状态。
    """
    body = str(entry.get("body") or "")
    body_path = entry.get("body_path")
    if body_path:
        path = Path(str(body_path))
        if path.is_file():
            body = path.read_text(encoding="utf-8-sig", errors="replace")
    identity = _identity_error(entry)
    if identity:
        # 身份不一致在台账 SHA、平台、git 三个分支之前拦下。
        return "", "", identity, ""
    merge = ""
    if str(entry.get("state") or "").lower() == "merged":
        merge = str(entry.get("merge_commit") or "")
    if merge:
        return body, merge, None, "ledger"
    fetched, why = _adapter_fetch(entry)
    if fetched and fetched.get("ok"):
        state = str(fetched.get("state") or "").lower()
        if state in ("open", "closed"):
            # 平台明确说没合入：即使 --allow-git-only，也不能拿同号 Git 提交覆盖。
            return "", "", f"平台状态 {state}，本轮不按合入处理", ""
        fetched_merge = str(fetched.get("merge_commit") or "")
        if fetched_merge and state in ("", "merged"):
            return body or str(fetched.get("body") or ""), fetched_merge, None, "platform"
        why = why or f"平台状态不是 merged（{state or 'unknown'}）"
    merge, git_why = _git_merge(root, entry)
    if merge:
        return body, merge, None, "git"
    return "", "", git_why or why or "缺合入提交", ""


def _append_log(inbox: Path, payload: dict, source: str) -> None:
    """每次运行追加一行，供面板与插件读；失败只影响日志，不影响结果。"""
    path = inbox / ".groom" / "sweep-log.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": now_iso(), "source": source, "ok": payload.get("ok"),
                 "merged": payload.get("merged"), "results": payload.get("results") or [],
                 "note": payload.get("note")}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run(args) -> dict:
    root = repo_root(Path(args.repo).resolve() if args.repo else Path.cwd())
    inbox = shared_inbox(root)
    check = None
    if not args.no_check:
        check = _check_all(root)
        if not check.get("ok") and check.get("code") in _FATAL_CHECK_CODES:
            payload = {"ok": False, "applied": bool(args.apply), "checked": check,
                       "merged": 0, "results": [],
                       "error": {"code": check.get("code"), "message": check.get("message")},
                       "note": "台账写入失败或冲突，本轮停止自动收尾"}
            _append_log(inbox, payload, args.source)
            return payload
    if args.fetch:
        try:
            # 合入提交可能只在 PR 的源远端（fork）而不在 origin；收尾要从该提交
            # 建隔离检出，所以这里把所有已配置远端都拉一遍。
            _run(["git", "fetch", "--all", "--quiet"], root, timeout=120)
        except Exception:
            pass

    ledger = pr_status.load_ledger(root)
    prs = ledger.get("prs") if isinstance(ledger.get("prs"), dict) else {}
    merged = {key: entry for key, entry in prs.items()
              if isinstance(entry, dict) and str(entry.get("state") or "").lower() == "merged"}
    # 按每条 PR 的查询结果决定能否回退：整轮 E_CHECK_PARTIAL 里已经确认
    # open/closed 的那条，不能被 Git 同号提交覆盖。
    checked_state = {}
    if check:
        for item in check.get("checked") or []:
            if isinstance(item, dict) and item.get("draft"):
                checked_state[str(item["draft"])] = str(item.get("state") or "").lower()
    git_only = args.no_check or (check is not None and not check.get("ok"))
    git_suspected = set()
    # 同一 PR 的多份草稿共享查询结论：组内任一草稿查到 open/closed 或台账已 closed，
    # 整组（默认写入与 git 回退）都不写。
    blocked_idents = set()
    for key, entry in prs.items():
        if not isinstance(entry, dict):
            continue
        if checked_state.get(key) in ("open", "closed"):
            blocked_idents.add(_pr_ident(entry))
        elif str(entry.get("state") or "").lower() == "closed":
            blocked_idents.add(_pr_ident(entry))
    if git_only:
        for key, entry in list(prs.items()):
            if key in merged or not isinstance(entry, dict):
                continue
            if _pr_ident(entry) in blocked_idents:
                continue
            if checked_state.get(key) in ("open", "closed"):
                continue
            state = str(entry.get("state") or "").lower()
            if state == "closed":
                continue
            if not str(entry.get("number") or ""):
                continue
            merge, _ = _git_merge(root, entry)
            if merge:
                # 清掉旧 SHA：git 找到的只算疑似，不能当台账里的可信合入。
                merged[key] = dict(entry, state="merged", merge_commit="")
                git_suspected.add(key)
    groups = _groups(merged)
    cleaned = _cleaned_heads(inbox)
    results = []
    for ident, keys in groups.items():
        # 同一个 PR 的所有台账记录（含已 closed 的保护记录）都要参与身份校验；
        # 只看 merged 的 keys 会漏掉被拆出去的那条。
        group_keys = [key for key, entry in prs.items()
                      if isinstance(entry, dict) and _pr_ident(entry) == ident]
        identity_errors = []
        for key in group_keys:
            error = _identity_error(prs[key])
            if error and error not in identity_errors:
                identity_errors.append(error)
        if identity_errors:
            results.append({"draft": keys[0], "drafts": keys,
                            "status": "identity-mismatch",
                            "reason": "；".join(identity_errors)})
            continue
        if ident in blocked_idents:
            results.append({"draft": keys[0], "drafts": keys,
                            "status": "skipped-not-merged",
                            "reason": "同一 PR 有未合入的草稿结论（open/closed），整组不写"})
            continue
        entry = merged[keys[0]]
        body, merge, why, source = _evidence(root, entry)
        if not merge:
            status = "identity-mismatch" if "不一致" in why else "missing-evidence"
            results.append({"draft": keys[0], "drafts": keys,
                            "status": status, "reason": why})
            continue
        if source == "git" and not getattr(args, "allow_git_only", False):
            results.append({"draft": keys[0], "drafts": keys,
                            "status": "git-suspected",
                            "reason": "git 推断的合入提交没有平台确认；"
                                      "加 --allow-git-only 才自动写"})
            continue
        if merge in cleaned:
            results.append({"draft": keys[0], "drafts": keys,
                            "status": "already-done", "merge": merge[:12]})
            continue
        if not args.apply:
            results.append({"draft": keys[0], "drafts": keys,
                            "status": "ready", "merge": merge[:12]})
            continue
        tmp_dir = inbox / ".groom" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(root / "scripts" / "groom_close_after_merge.py"),
               "--repo", str(root), "--merge", merge, "--apply", "--json"]
        if body:
            body_file = tmp_dir / f"sweep-{keys[0]}.md"
            body_file.write_text(body, encoding="utf-8")
            cmd += ["--pr-body-file", str(body_file)]
        else:
            # A 方案：没有 PR body 时用本地评估记录收尾。
            for key in keys:
                cmd += ["--draft-key", key]
        if args.no_cleanup:
            cmd.append("--no-cleanup")
        try:
            proc = _run(cmd, root)
        except subprocess.TimeoutExpired:
            results.append({"draft": keys[0], "drafts": keys,
                            "status": "failed", "reason": "收尾超时"})
            continue
        payload = {}
        try:
            payload = json.loads(proc.stdout or "{}")
        except ValueError:
            payload = {}
        cleanup = payload.get("cleanup")
        status = "closed" if proc.returncode == 0 else "failed"
        if payload.get("results"):
            first = str(payload["results"][0].get("status") or status)
            if first in ("failed", "error"):
                status = "failed"
        if isinstance(cleanup, dict) and cleanup.get("ok") is False:
            status = "cleanup-failed"
        reason = None
        if status not in ("closed", "already-done"):
            reason = (proc.stderr or proc.stdout or "").strip()[:300] or None
            if not reason and isinstance(cleanup, dict):
                reason = cleanup.get("error")
        results.append({"draft": keys[0], "drafts": keys, "status": status,
                        "merge": merge[:12], "reason": reason})
    failed = [r for r in results if r["status"] in ("failed", "cleanup-failed")]
    payload = {"ok": not failed, "applied": bool(args.apply), "checked": check,
               "merged": len(groups), "results": results,
               "note": "无事可做：台账里没有已合入待收尾的 PR" if not merged else None}
    _append_log(inbox, payload, args.source)
    return payload


def main(argv=None) -> int:
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="每日自动收尾：查合入、取证、收尾并清理")
    ap.add_argument("--repo", default=None, help="主检出绝对路径（默认当前目录）")
    ap.add_argument("--apply", action="store_true", help="真正收尾；不给只打印计划")
    ap.add_argument("--fetch", action="store_true", help="先 git fetch 再查")
    ap.add_argument("--no-check", action="store_true", help="不调用 pr_status 查合入状态")
    ap.add_argument("--no-cleanup", action="store_true", help="收尾后不调用清理")
    ap.add_argument("--allow-git-only", action="store_true",
                    help="没有平台状态确认时，也按 git 找到的合入提交自动写（默认只报告）")
    ap.add_argument("--source", default="manual",
                    help="触发源（manual / plugin / groom / copilot），写进 sweep-log")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        payload = run(args)
    except RuntimeError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 2
    if args.json:
        print(dump_json(payload))
    else:
        if payload["note"]:
            print(payload["note"])
        for item in payload["results"]:
            print(f"{item['status']:<15} {item['draft']}"
                  + (f" · {item['reason']}" if item.get("reason") else ""))
        if payload["checked"] and not payload["checked"].get("ok"):
            print(f"查合入未完成：{payload['checked'].get('detail')}")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
