#!/usr/bin/env python3
"""src_fetch.py —— 确定性获取（复用 / 新拉）**对应版本**的分析用源码

背景（两件事叠在一起，2026-09-14 一起修）：

  ① **闸门说假话（"本地没找到这个版本就去 web 搜索"的直接成因）**。旧实现的"复用优先"分支在版本
     不符时**无条件** `print("复用 <路径>")` + `return 0`——fetch/checkout 失败也走这条。而 SKILL 的
     契约是"非零退出 = 未取得源码"，于是 agent 拿到 exit 0 + 一个路径、grep 不到预期符号 → 判"本地
     没有这个版本" → 转 web 搜索。**换成任何目录布局这个失败都会复发**（布局只让"有没有这个版本"
     可判定，不会让"版本不符"变成失败），所以退出码是本脚本的第一契约，不是附带改进。
     加剧因素：`--ref 0.26.0` 与真实 tag `v0.26.0` 只差一个前缀——现在做 v 前缀容错解析，解析不到时
     列出可用 tag（旧实现静默判不匹配）。
  ② **缓存不可共享**。缓存根原为 `__file__` 上两级（= 执行脚本的那个检出），而 `src-code/` 是
     .gitignore 件 → 新 worktree 天然没有它、`git worktree remove` 连它一起删；"平铺版本目录给多
     agent 协作"在共享面根本不成立。现在根解析到**主检出**（同一克隆共享，复用 exec_log_path 的既有
     范式；`--local` 可强制回检出内）。

布局（每个版本目录自包含、互不干扰）：

    src-code/<org>/<repo>/<解析后的 ref>/                     # 例：…/vllm-ascend/v0.26.0/
    src-code/<org>/<repo>/<解析后的 ref>/.git/src-fetch-meta.json   # 版本标记（离线核对用）

  版本目录名 = **解析后的** ref（tag/分支名；commit 用 `sha-<12>`），于是「本地有没有这个版本」是一次
  目录名可判定的检查，且 `source_ref.ref` 与目录名是同一个 token（案例 ↔ 源码互查免费）。
  每个版本是一次独立浅克隆（`--depth 1`）：代价是一份工作树，换来版本间物理隔离——并发诊断下不存在
  "别人 checkout 走了我正在读的版本"这类静默错证据（单目录 + 换版本 checkout 的旧布局正是如此）。

退出码契约（agent 依此决定下一步，别只看输出里的路径）：

    0  已在本地产出该 ref 的树**并通过核对**（stdout 最后一行 = 绝对路径）
    2  用法/参数问题（未知仓库且无 --url、--prune 缺 --ref、--prune 目标不存在…）
    3  ref 解析不了：源可达但找不到该 tag/分支（**附可用 tag 示例**——多半是 tag 名不同或版本说错）
    4  拉取失败：候选源都不可达/克隆失败，或拉到的提交与 ref 不符（网络、私网、凭据）
    5  本地有该版本的目录但**核对不通过**（内容不是该 ref / 被外部改动）→ 确认后 --force 重拉

  stdout 末行只有两种形态：**exit 0 时是版本目录的绝对路径**，非零时是一行显式的失败声明
  （`✗ 未取得该版本源码`）——绝不会把某个版本目录当成结果给出来。旧实现正是在这里让 agent 误以为
  拿到了对应版本源码（版本不符也 exit 0 + 打印路径）。

用法：
  python3 scripts/src_fetch.py vllm-ascend --ref v0.23.0
  python3 scripts/src_fetch.py vllm-ascend --ref 0.26.0        # 自动容错到 v0.26.0
  python3 scripts/src_fetch.py vllm-project/vllm-ascend --ref v0.23.0
  python3 scripts/src_fetch.py Ascend/MindSpeed-LLM --ref v0.23.0        # gitcode
  python3 scripts/src_fetch.py my-org/my-repo --ref <commit> --url https://...   # 自定义/私有
  python3 scripts/src_fetch.py --list                    # 已知仓库与 host
  python3 scripts/src_fetch.py --list-versions           # 本地缓存：有哪些仓库、哪些版本（体积/时间/HEAD）
  python3 scripts/src_fetch.py vllm-ascend --ref v0.23.0 --prune        # 手工删版本（无自动 GC）
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from _stdio import write_text_lf

from exec_log_path import WHERE_LABEL_SRC, describe_src, resolve_src_code  # noqa: E402  （共享缓存根解析的单一事实源）

# 已知仓库 → 有序候选 URL host（按可信度排序；同一仓库不同 host 是常态，自动回退）
HOSTS = {
    "github": "https://github.com/{owner}/{repo}.git",
    "gitcode": "https://gitcode.com/{owner}/{repo}.git",
    "gitee": "https://gitee.com/{owner}/{repo}.git",
}
KNOWN_REPOS = {
    # key: (canonical org/repo, [(host, {owner, repo}), ...] 按序尝试)
    "vllm-ascend": ("vllm-project/vllm-ascend", [("github", {"owner": "vllm-project", "repo": "vllm-ascend"})]),
    "vllm-project/vllm-ascend": ("vllm-project/vllm-ascend", [("github", {"owner": "vllm-project", "repo": "vllm-ascend"})]),
    "mindspeed-llm": ("Ascend/MindSpeed-LLM", [("gitcode", {"owner": "Ascend", "repo": "MindSpeed-LLM"})]),
    "Ascend/MindSpeed-LLM": ("Ascend/MindSpeed-LLM", [("gitcode", {"owner": "Ascend", "repo": "MindSpeed-LLM"})]),
    "mindspeed-mm": ("Ascend/MindSpeed-MM", [("gitcode", {"owner": "Ascend", "repo": "MindSpeed-MM"})]),
    "Ascend/MindSpeed-MM": ("Ascend/MindSpeed-MM", [("gitcode", {"owner": "Ascend", "repo": "MindSpeed-MM"})]),
    "torch-npu": ("Ascend/pytorch", [("gitcode", {"owner": "Ascend", "repo": "pytorch"}), ("github", {"owner": "Ascend", "repo": "pytorch"})]),
    "Ascend/pytorch": ("Ascend/pytorch", [("gitcode", {"owner": "Ascend", "repo": "pytorch"}), ("github", {"owner": "Ascend", "repo": "pytorch"})]),
    "verl": ("volcengine/verl", [("github", {"owner": "volcengine", "repo": "verl"})]),
    "volcengine/verl": ("volcengine/verl", [("github", {"owner": "volcengine", "repo": "verl"})]),
}

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REF_UNRESOLVED = 3
EXIT_FETCH_FAILED = 4
EXIT_LOCAL_MISMATCH = 5

META_NAME = "src-fetch-meta.json"     # 落在 <版本目录>/.git/ 下（不在工作树里，git status 看不见）
TMP_PREFIX = ".tmp-"
TMP_STALE_SECONDS = 6 * 3600          # 半途被杀留下的临时克隆：超过这个岁数由下次运行顺手清掉


def die(code: int, msg: str, tail: str = "✗ 未取得该版本源码") -> int:
    """失败出口：原因 + 可执行的下一步走 stderr；stdout 只留一行**显式的失败声明**当末行。

    末行契约（调用方只看末行也安全）：exit 0 → 末行是版本目录的绝对路径；非零 → 末行是这句声明。
    旧实现失败时也打印路径，正是"agent 以为拿到了对应版本源码"的入口。
    """
    print(f"src_fetch: {msg}", file=sys.stderr)
    print(f"{tail}（exit {code}）")
    return code


def norm_repo(repo: str) -> str:
    """规范化仓库标识：去空白、尾部 .git；返回用于查表的键。"""
    return repo.strip().rstrip("/").removesuffix(".git")


def lookup(repo: str):
    """返回 (canonical_org/repo, [候选 (host, {owner,repo}), ...])；未知仓库返回 (repo, None)。"""
    key = norm_repo(repo)
    if key in KNOWN_REPOS:
        return KNOWN_REPOS[key]
    for k, val in KNOWN_REPOS.items():
        if norm_repo(k).lower() == key.lower():
            return val
    return (key, None)


def clone_url(host: str, owner: str, repo: str) -> str:
    return HOSTS[host].format(owner=owner, repo=repo)


def run(cmd, check=False) -> bool:
    try:
        subprocess.run(cmd, check=check, stdout=None if check else subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def progress(cmd):
    """把一条将执行的 git 命令打到 stdout（trace tool_calls 的原材料：哪个源不可达）。"""
    print("  $", " ".join(cmd))


def git_out(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p


def looks_like_sha(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{7,40}", (s or "").strip()))


def ref_aliases(ref: str):
    """ref 的写法变体（有序）：原样优先，其次 v 前缀容错（0.26.0 ↔ v0.26.0）。

    为什么必须有：issue/环境里写的是版本号（0.26.0），上游 tag 常是 v0.26.0。旧实现只按原样 fetch，
    失败后**静默**判"不匹配"并 exit 0——那是"agent 以为拿到了对应版本"的入口之一。
    """
    r = (ref or "").strip()
    out = [r]
    if len(r) > 1 and r[0] in "vV" and r[1].isdigit():
        out.append(r[1:])
    elif r[:1].isdigit():
        out.append("v" + r)
    return out


def refs_equivalent(a: str, b: str) -> bool:
    """两个 ref 写法是否指同一版本（仅用于本地复用的**容错匹配**；命中会明确打印出来）。"""
    a, b = (a or "").strip(), (b or "").strip()
    return a == b or a in ref_aliases(b) or b in ref_aliases(a)


def ls_remote(url: str, patterns):
    """`git ls-remote <url> <patterns...>` → (refname→sha 字典, 错误串)。(None, err) = 源不可达。"""
    p = git_out(["git", "ls-remote", url, *patterns])
    if p.returncode != 0:
        text = (p.stderr or p.stdout or "").strip()
        return None, text.splitlines()[-1] if text else "ls-remote 失败"
    have = {}
    for line in p.stdout.splitlines():
        if "\t" not in line:
            continue
        sha, name = line.split("\t", 1)
        have[name.strip()] = sha.strip()
    return have, ""


def remote_head(url: str):
    """远程默认分支 → ({kind: default, name, sha, requested}, "")；失败 (None, 原因)。"""
    p = git_out(["git", "ls-remote", "--symref", url, "HEAD"])
    if p.returncode != 0:
        return None, "ls-remote --symref 失败（源不可达）"
    branch, sha = "", ""
    for line in p.stdout.splitlines():
        if line.endswith("\tHEAD"):
            if line.startswith("ref:"):
                branch = line.split()[1].removeprefix("refs/heads/")
            else:
                sha = line.split("\t", 1)[0]
    if not sha:
        return None, "远程 HEAD 不可解析"
    return {"kind": "default", "name": branch or "HEAD", "sha": sha, "requested": ""}, ""


def resolve_ref(url: str, ref: str):
    """把用户给的 ref 解析为 {kind, name, sha, requested}；解析不了 → (None, 原因)。

    tag 优先于同名分支（源码分析几乎总是钉 tag）；annotated tag 取 `^{}`（提交）而非 tag 对象。
    """
    r = (ref or "").strip()
    if not r:
        return remote_head(url)
    if looks_like_sha(r):
        return {"kind": "commit", "name": r.lower(), "sha": r.lower(), "requested": r}, ""
    pats = []
    for name in ref_aliases(r):
        pats += [f"refs/tags/{name}", f"refs/tags/{name}^{{}}", f"refs/heads/{name}"]
    have, err = ls_remote(url, pats)
    if have is None:
        return None, err
    for name in ref_aliases(r):
        tag, deref, br = f"refs/tags/{name}", f"refs/tags/{name}^{{}}", f"refs/heads/{name}"
        if deref in have:
            return {"kind": "tag", "name": name, "sha": have[deref], "requested": r}, ""
        if tag in have:
            return {"kind": "tag", "name": name, "sha": have[tag], "requested": r}, ""
        if br in have:
            return {"kind": "branch", "name": name, "sha": have[br], "requested": r}, ""
    return None, f"源可达但找不到「{r}」对应的 tag/分支（已试 v 前缀容错）"


def available_tags(url: str, limit: int = 10):
    """可用 tag 示例（tag 名与预期不同时，给 agent 一个能照做的下一步，而不是让它去猜/去搜）。"""
    p = git_out(["git", "ls-remote", "--tags", url])
    if p.returncode != 0:
        return []
    tags = sorted({ln.split("\t", 1)[1].split("refs/tags/")[-1]
                   for ln in p.stdout.splitlines()
                   if "\t" in ln and "refs/tags/" in ln and not ln.rstrip().endswith("^{}")})
    return tags[-limit:]


def head_sha(path: Path):
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(path),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def describe_head(path: Path) -> str:
    """人读用：精确 tag，否则短 hash。"""
    for args in (["describe", "--tags", "--exact-match"], ["log", "-1", "--format=%h"]):
        p = subprocess.run(["git"] + args, cwd=str(path),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return "?"


def meta_path(version_dir: Path) -> Path:
    return version_dir / ".git" / META_NAME


def read_meta(version_dir: Path):
    try:
        return json.loads(meta_path(version_dir).read_text(encoding="utf-8"))
    except Exception:
        return None


def write_meta(version_dir: Path, meta: dict):
    write_text_lf(meta_path(version_dir), json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


def version_token(res: dict) -> str:
    """版本目录名 = 解析后的 ref（tag/分支名原样，commit 用 sha-<12>）。"""
    if res["kind"] == "commit":
        return "sha-" + res["name"][:12]
    return str(res["name"]).replace("/", "__")


def iter_version_dirs(repo_dir: Path):
    """某仓库下已有的版本目录（排除临时克隆与点目录）。"""
    if not repo_dir.is_dir():
        return []
    return [d for d in sorted(repo_dir.iterdir())
            if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists()]


def verify_version_dir(version_dir: Path):
    """**离线**核对一个版本目录 → (ok, 原因, meta)。不联网也能判"这个目录是不是那个版本"。

    依据是目录内 .git/src-fetch-meta.json 记录的实际 HEAD（克隆落地后回填），与当前 HEAD 对照——
    目录被外部 checkout 走、克隆半途被杀，都在这里被判出来，而不是被静默复用。
    """
    meta = read_meta(version_dir)
    head = head_sha(version_dir)
    if head is None:
        return False, "不是可用的 git 工作树（缺 .git 或仓库损坏）", meta
    if meta is None:
        return False, "无 src-fetch 版本标记（旧布局手工 clone 的目录？）——无法确认它是哪个版本", meta
    if head != str(meta.get("sha", "")):
        return False, (f"HEAD {head[:12]} 与标记的 {str(meta.get('sha', ''))[:12]} 不一致"
                       "（目录被外部改过/克隆未完成）"), meta
    return True, "", meta


def match_local_meta(meta, ref: str):
    """本地标记是否对应用户请求的 ref → "exact" | "sha" | "tolerant" | None。"""
    if not meta:
        return None
    r = (ref or "").strip()
    if not r:
        return "exact" if meta.get("ref_kind") == "default" else None
    if meta.get("ref_name") == r or meta.get("ref_requested") == r:
        return "exact"
    if looks_like_sha(r) and str(meta.get("sha", "")).startswith(r.lower()):
        return "sha"
    if refs_equivalent(str(meta.get("ref_name", "")), r):
        return "tolerant"
    return None


def find_local(repo_dir: Path, ref: str):
    """本地匹配该 ref 的版本目录 → [(dir, how, ok, 原因, meta)]。**不联网**。"""
    out = []
    for d in iter_version_dirs(repo_dir):
        meta = read_meta(d)
        how = match_local_meta(meta, ref)
        if how is None:
            continue
        ok, why, meta = verify_version_dir(d)
        out.append((d, how, ok, why, meta))
    return out


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def human_size(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024.0
    return f"{v:.1f} GB"


def mtime_date(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    except OSError:
        return "?"


def cleanup_stale_tmp(repo_dir: Path):
    """顺手清掉半途被杀留下的临时克隆（超 TMP_STALE_SECONDS；best-effort，不报错）。"""
    if not repo_dir.is_dir():
        return
    for d in repo_dir.glob(TMP_PREFIX + "*"):
        try:
            if time.time() - d.stat().st_mtime > TMP_STALE_SECONDS:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def clone_into(url: str, res: dict, tmp: Path, depth: str) -> bool:
    """把对应版本浅克隆到 tmp（tmp 必须是不存在的路径）。

    `-c advice.detachedHead=false`：钉 tag 必然进 detached HEAD，而 git 那段"你在游离头指针上"的建议
    会混进 agent 看到的输出里（trace tool_calls 的噪声），让它看起来像出了岔子——这里去掉。
    """
    quiet = ["git", "-c", "advice.detachedHead=false"]
    if res["kind"] == "commit":
        cmd = [*quiet, "clone", "--depth", depth, url, str(tmp)]
        progress(cmd)
        if not run(cmd, check=True):
            return False
        cmd = ["git", "-C", str(tmp), "fetch", "--depth", depth, "origin", res["name"]]
        progress(cmd)
        if not run(cmd, check=True):
            return False
        cmd = [*quiet, "-C", str(tmp), "checkout", "--detach", res["name"]]
        progress(cmd)
        return run(cmd, check=True)
    cmd = [*quiet, "clone", "--depth", depth, "--branch", res["name"], url, str(tmp)]
    progress(cmd)
    return run(cmd, check=True)


def install_version(tmp: Path, target: Path, meta: dict):
    """临时克隆 → 版本目录（原子 rename；并发时失败者复用赢家）→ (结果, 说明)。"""
    write_meta(tmp, meta)
    if target.exists():
        ok, why, _ = verify_version_dir(target)
        shutil.rmtree(tmp, ignore_errors=True)
        return ("reused", "另一进程已产出该版本") if ok else ("conflict", why)
    try:
        os.rename(tmp, target)          # 同文件系统内原子；目标已存在则抛 OSError
    except OSError:
        ok, why, _ = verify_version_dir(target)
        shutil.rmtree(tmp, ignore_errors=True)
        return ("reused", "另一进程并发产出，已复用") if ok else ("conflict", why)
    return "installed", ""


def list_versions(cache_root: Path, only_repo: str = ""):
    """本地缓存清单：有哪些仓库、哪些版本（体积/时间/HEAD）。"""
    print(f"源码缓存：{cache_root}")
    if not cache_root.is_dir():
        print("  （还没有任何源码缓存）")
        return
    repos = []
    for org in sorted(p for p in cache_root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for repo in sorted(p for p in org.iterdir() if p.is_dir() and not p.name.startswith(".")):
            repos.append((f"{org.name}/{repo.name}", repo))
    if only_repo:
        key = norm_repo(only_repo).lower()
        tail = key.split("/")[-1]
        repos = [(name, p) for name, p in repos if name.lower() == key or name.split("/")[-1].lower() == tail]
    if not repos:
        print(f"  （没有匹配「{only_repo}」的仓库缓存）")
        return
    for name, repo_dir in repos:
        versions = iter_version_dirs(repo_dir)
        legacy = (repo_dir / ".git").exists()
        print(f"\n{name}  —— {len(versions)} 个版本" + ("  ⚠ 另有旧布局单检出" if legacy else ""))
        if not versions:
            print("  （无版本目录）")
        for d in versions:
            meta = read_meta(d)
            ok, why, _ = verify_version_dir(d)
            head = str((meta or {}).get("sha", ""))[:12] or str(head_sha(d) or "?")[:12]
            print(f"  {d.name:<24} {human_size(dir_size(d)):>9}  {mtime_date(d)}  HEAD={head}"
                  + ("" if ok else f"  ⚠ {why}"))
        if legacy:
            print(f"  ⚠ 旧布局单检出（{describe_head(repo_dir)}）：{repo_dir}/.git")
            print("    不参与版本复用、新版也不会动它；要留就手工 mv 进 <版本>/ 目录，否则删掉即可")


def prune_version(repo_dir: Path, ref: str) -> int:
    """手工删除某版本目录（无自动 GC：正在被别的 agent 分析的版本不能自己消失）。"""
    cands = [d for d in iter_version_dirs(repo_dir)
             if d.name == ref or match_local_meta(read_meta(d), ref)]
    if not cands:
        have = ", ".join(d.name for d in iter_version_dirs(repo_dir)) or "（无）"
        return die(EXIT_USAGE, f"本地没有匹配「{ref}」的版本目录（现有：{have}）", tail="✗ 未执行删除")
    if len(cands) > 1:
        return die(EXIT_USAGE, f"「{ref}」匹配到多个版本目录：{', '.join(d.name for d in cands)}——请用完整目录名",
                   tail="✗ 未执行删除")
    print(f"删除 {cands[0]}（{human_size(dir_size(cands[0]))}）")
    shutil.rmtree(cands[0])
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description="确定性获取对应版本的源码")
    ap.add_argument("repo", nargs="?", help="仓库标识（已知名 / org/repo；未知需 --url）")
    ap.add_argument("--ref", default="", help="版本 tag/commit（源码分析依赖对应版本；空 = 默认分支）")
    ap.add_argument("--url", default="", help="自定义/私有 clone URL（内网、未知仓库时提供；脚本不碰凭据）")
    ap.add_argument("--dest", default=None, help="本地缓存根目录（默认主检出 src-code/，见 --local）")
    ap.add_argument("--local", action="store_true", help="缓存根用当前检出（默认锚到主检出，跨 worktree 共享）")
    ap.add_argument("--force", action="store_true", help="本地目录版本不符/损坏时删掉重拉（否则非零退出）")
    ap.add_argument("--depth", default="1", help="clone 深度（默认浅拉 1，够 grep/读）")
    ap.add_argument("--list", action="store_true", help="列出已知仓库与 host")
    ap.add_argument("--list-versions", action="store_true", help="列出本地缓存的仓库与版本")
    ap.add_argument("--prune", action="store_true", help="删除 --ref 指定的本地版本目录（无自动 GC）")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：本脚本上两级）")
    args = ap.parse_args()

    if args.list:
        print("已知仓库 → 候选 source：")
        for key, (canonical, cands) in KNOWN_REPOS.items():
            print(f"  {key:24s} -> {canonical}  ({'; '.join(c for c, _ in cands)})")
        return EXIT_OK

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    # --dest 归一为绝对路径：契约是"stdout 末行 = 绝对路径"，相对路径会让调用方拼错地方
    explicit = Path(args.dest).expanduser().resolve() if args.dest else None
    cache_root, where = resolve_src_code(root, explicit=explicit, local=args.local)

    if args.list_versions:
        print(f"（{WHERE_LABEL_SRC.get(where, where)}）")
        list_versions(cache_root, args.repo or "")
        return EXIT_OK

    if not args.repo:
        return die(EXIT_USAGE, "未指定 repo（--list 看已支持仓库，--list-versions 看本地缓存）")

    canonical, cands = lookup(args.repo)
    if args.url:
        cands = [("custom", {"url": args.url})]
        canonical = canonical or norm_repo(args.repo)
        print(f"自定义 URL：{args.url}")
    if cands is None:
        if "/" in canonical:
            cands = [("github", {"owner": canonical.split("/")[0], "repo": canonical.split("/")[1]})]
            print(f"未知仓库，默认走 GitHub：{canonical}")
        else:
            return die(EXIT_USAGE, f"未知仓库「{args.repo}」（无 / 且不在已知表）——给 --url 或 org/repo")

    org, repo = canonical.split("/", 1)
    repo_dir = cache_root / org / repo

    if args.prune:
        if not args.ref:
            return die(EXIT_USAGE, "--prune 需要 --ref 指明删哪个版本（--list-versions 看现有版本）", tail="✗ 未执行删除")
        if not repo_dir.is_dir():
            return die(EXIT_USAGE, f"本地没有该仓库的缓存：{repo_dir}", tail="✗ 未执行删除")
        return prune_version(repo_dir, args.ref)

    # ① 本地优先（**不联网**）：版本目录名 + 目录内标记就是答案
    local = find_local(repo_dir, args.ref)
    for d, how, ok, why, meta in local:
        if ok:
            note = "（按 v 前缀容错匹配）" if how == "tolerant" else ""
            print(f"复用 {d}（{meta.get('ref_kind')} {meta.get('ref_name')}，HEAD 已核对{note}）")
            print(f"缓存：{describe_src(cache_root, where)}")
            print(str(d))
            return EXIT_OK
    bad_local = [(d, why) for d, _how, ok, why, _m in local if not ok]

    # ② 需要联网：解析 ref（逐候选源）；解析不到就非零退出，并给可用 tag
    resolved, url_used, failures = None, "", []
    for host, slot in cands:
        url = slot["url"] if host == "custom" else clone_url(host, slot["owner"], slot["repo"])
        print(f"尝试解析 {url} 的 ref「{args.ref or '(默认分支)'}」")
        res, err = resolve_ref(url, args.ref)
        if res:
            resolved, url_used = res, url
            break
        failures.append(f"{url}: {err}")
        tags = available_tags(url)
        if tags:
            print(f"    该源可用 tag（末 {len(tags)} 个）：{', '.join(tags)}")

    if resolved is None:
        for line in failures:
            print(f"  ✗ {line}", file=sys.stderr)
        if bad_local:
            d, why = bad_local[0]
            return die(EXIT_LOCAL_MISMATCH,
                       f"本地有该版本的目录但核对不通过：{d}（{why}）——"
                       "确认它就是该版本就用 --force 重拉（会删掉该目录）")
        return die(EXIT_REF_UNRESOLVED,
                   f"未能解析 ref「{args.ref or '(默认分支)'}」：tag 名可能与预期不同（已自动容错 v 前缀）。"
                   "按上面列出的可用 tag 重试，或让用户确认版本号。"
                   "**不要用 web 搜索代替取对应版本源码**")

    # ③ 版本目录已在（token 命中但标记不符/损坏）
    target = repo_dir / version_token(resolved)
    if target.exists() and not (target / ".git").exists():
        if not any(target.iterdir()):     # 空壳目录不携带任何信息，直接清掉
            print(f"清理空目录 {target}（无 .git、也无内容）")
            shutil.rmtree(target)
    if target.exists():
        ok, why, _ = verify_version_dir(target)
        if ok:
            print(f"复用 {target}（本地已有该版本，HEAD 已核对）")
            print(f"缓存：{describe_src(cache_root, where)}")
            print(str(target))
            return EXIT_OK
        if not args.force:
            return die(EXIT_LOCAL_MISMATCH,
                       f"本地已有 {target} 但核对不通过：{why}——"
                       "确认它就是该版本就加 --force 重拉（会删掉该目录后重新克隆）")
        print(f"--force：删除核对不通过的 {target}")
        shutil.rmtree(target)

    # ④ 拉取：临时目录 → 校验 → 原子 rename 进版本目录
    cleanup_stale_tmp(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)
    tmp = repo_dir / f"{TMP_PREFIX}{version_token(resolved)}-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"拉取 {resolved['name']}（{resolved['kind']}）→ {target}")
    if not clone_into(url_used, resolved, tmp, args.depth):
        shutil.rmtree(tmp, ignore_errors=True)
        return die(EXIT_FETCH_FAILED,
                   f"拉取失败：{url_used}（ref {resolved['name']}）——网络/私网不可达时用 --url 给可达地址；"
                   "注意：本地已有的**其他**版本仍在，但该版本确实没取到")
    head = head_sha(tmp)
    expect = str(resolved["sha"])
    ok_sha = bool(head) and (head == expect or (resolved["kind"] == "commit" and head.startswith(expect)))
    if not ok_sha:
        shutil.rmtree(tmp, ignore_errors=True)
        return die(EXIT_FETCH_FAILED,
                   f"拉到的 HEAD（{str(head)[:12]}）与 {resolved['name']} 解析出的提交（{expect[:12]}）不一致——"
                   "拒绝把它当成本版本源码")
    meta = {
        "repo": canonical, "url": url_used, "ref_requested": args.ref,
        "ref_kind": resolved["kind"], "ref_name": resolved["name"],
        "sha": head, "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    result, why = install_version(tmp, target, meta)
    if result == "conflict":
        return die(EXIT_LOCAL_MISMATCH,
                   f"目标目录 {target} 在本次拉取期间被其他进程产出且核对不通过：{why}（重试或 --force）")
    print(f"{'产出' if result == 'installed' else '复用'} {target}"
          + (f"（{why}）" if why else "（新增版本；其他版本目录保留不动）"))
    print(f"缓存：{describe_src(cache_root, where)}")
    print(str(target))
    return EXIT_OK


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
