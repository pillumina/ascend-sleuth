#!/usr/bin/env python3
"""src_fetch.py —— 确定性获取（复用 / 新拉）分析用源码（原则二：把「clone 到哪」从 agent 自觉变成可观测脚本）

背景：诊断源码分析依赖**对应版本**的源码（见 CLAUDE.md `source_ref` 与 diagnose SKILL 源码分析节）。此前
「源码放哪、同版本复用、URL 来自哪」是 SKILL 里的约定，agent 会漂移（曾 clone 到 /tmp 不落 src-code/）。
此脚本把这套约定变成**确定性操作**：agent 只需 `python3 scripts/src_fetch.py <repo> --ref <tag>`，拿到本地
路径去 grep/读，不再自行决定 clone 到哪、不再重复拉取同一版本。

设计（灵活，按问题背景定仓库来源）：
  - 仓库来源 flexible：已知仓库按仓库名/ org 定 host——vllm-ascend=GitHub、mindspeed-* =GitCode、
    torch-npu=GitCode（可 `--list` 查看已知表；不同仓库不同 host 是常态）。
  - 未知仓库：给 `org/repo` 默认走 GitHub；或 `--url <自定义>`（私有/内网由用户提供，脚本不碰凭据）。
  - 多候选自动回退：每个仓库维护有序候选 URL 列表，逐一尝试；失败即记（trace tool_calls 记"哪源不可达"）。
  - 复用优先：`<dest>/<org>/<repo>/` 已存在 → 核对版本（describe / log -1）后直接返回路径，不重复 clone；
    已有但版本不符 → 默认尝试 `git checkout --ref`（切到对应版本），`--force` 才重新 clone。

用法：
  python3 scripts/src_fetch.py vllm-ascend --ref v0.23.0
  python3 scripts/src_fetch.py vllm-project/vllm-ascend --ref v0.23.0
  python3 scripts/src_fetch.py Ascend/MindSpeed-LLM --ref v0.23.0          # gitcode
  python3 scripts/src_fetch.py torch-npu --ref v2.1.0                      # gitcode (Ascend/pytorch)
  python3 scripts/src_fetch.py --list
  python3 scripts/src_fetch.py my-org/my-repo --ref <commit> --url https://...  # 自定义/私有

非零退出 = 未能取得源码（agent 按 SKILL 标缺口 / 联系用户给 URL）。"哪个源不可达"由 stdout 打印供 trace tool_calls。
"""
import argparse
import subprocess
import sys
from pathlib import Path

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


def norm_repo(repo: str) -> str:
    """规范化仓库标识：去空白、尾部 .git、小写比较；返回用于查表的键。"""
    r = repo.strip().rstrip("/").removesuffix(".git")
    return r


def lookup(repo: str):
    """返回 (canonical_org/repo, [候选 (host, {owner,repo}), ...])；未知仓库返回 (repo, None)。"""
    key = norm_repo(repo)
    if key in KNOWN_REPOS:
        return KNOWN_REPOS[key]
    # 按尾段 / 全名再匹配一次（容忍大小写）
    for k, val in KNOWN_REPOS.items():
        if norm_repo(k).lower() == key.lower():
            return val
    return (key, None)


def clone_url(host: str, owner: str, repo: str) -> str:
    return HOSTS[host].format(owner=owner, repo=repo)


def run(cmd, check=False):
    print("  $", " ".join(cmd))
    try:
        subprocess.run(cmd, check=check)
        return True
    except subprocess.CalledProcessError:
        return False


def head_version(path: Path):
    """返回当前检出版本描述（tag 或短 hash），用于复用核对。"""
    for args in (["describe", "--tags", "--exact-match"], ["log", "-1", "--format=%h"]):
        p = subprocess.run(["git"] + args, cwd=path, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", nargs="?", help="仓库标识（已知名 / org/repo；未知需 --url）")
    ap.add_argument("--ref", default="", help="版本 tag/commit（源码分析依赖对应版本；空 = 默认分支）")
    ap.add_argument("--url", default="", help="自定义/私有 clone URL（内网、未知仓库时提供；脚本不碰凭据）")
    ap.add_argument("--dest", default=None, help="本地缓存根目录（默认 <repo>/src-code/）")
    ap.add_argument("--force", action="store_true", help="版本不符时强制重新 clone（否则尝试 checkout）")
    ap.add_argument("--depth", default="1", help="clone 深度（默认浅拉 1，够 grep/读）")
    ap.add_argument("--list", action="store_true", help="列出已知仓库与 host")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：本脚本上两级）")
    args = ap.parse_args()

    if args.list:
        print("已知仓库 → 候选 source：")
        for key, (canonical, cands) in KNOWN_REPOS.items():
            print(f"  {key:24s} -> {canonical}  ({'; '.join(c for c, _ in cands)})")
        return 0

    if not args.repo:
        print("未指定 repo（--list 可看已支持仓库）", file=sys.stderr)
        return 2

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    dest_root = Path(args.dest) if args.dest else root / "src-code"

    canonical, cands = lookup(args.repo)
    if args.url:
        cands = [("custom", {"url": args.url})]
        canonical = canonical or norm_repo(args.repo)
        print(f"自定义 URL：{args.url}")

    if cands is None:
        # 未知仓库：org/repo 缺省 GitHub；否则提示 --url
        if "/" in canonical:
            cands = [("github", {"owner": canonical.split("/")[0], "repo": canonical.split("/")[1]})]
            print(f"未知仓库，默认走 GitHub：{canonical}")
        else:
            print(f"未知仓库「{args.repo}」（无 / 且不在已知表）。请给 --url 或 org/repo。", file=sys.stderr)
            return 2

    org, repo = canonical.split("/", 1)
    # 单一目录 `<dest>/<org>/<repo>`：复用优先，换版本用 checkout（不重复 clone、不堆积版本目录）
    target = dest_root / org / repo

    # 复用优先：已存在 → 核对版本；--ref 不符默认尝试 checkout，--force 才重拉
    if target.exists() and (target / ".git").exists():
        current = head_version(target)
        if args.ref and not args.force and current != args.ref:
            if run(["git", "-C", str(target), "fetch", "--depth", args.depth, "origin", args.ref]) and \
               run(["git", "-C", str(target), "checkout", args.ref]):
                current = head_version(target)
        print(f"复用 {target}（当前检出 {current}）")
        print(str(target))
        return 0

    # 新拉：逐一尝试候选 URL
    target.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    ok = False
    for host, slot in cands:
        if host == "custom":
            url = slot["url"]
        else:
            url = clone_url(host, slot["owner"], slot["repo"])
        attempts.append(url)
        print(f"尝试 {url} -> {target}")
        cmd = ["git", "clone", "--depth", args.depth]
        if args.ref:
            cmd += ["--branch", args.ref]
        cmd += [url, str(target)]
        if run(cmd, check=False):
            ok = True
            break
        # 该源失败：问真实 tag（不同版本库 tag 命名不同），供 agent 记 tool_calls
        ls = subprocess.run(["git", "ls-remote", "--tags", url], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if ls.returncode == 0 and ls.stdout.strip():
            tags = [ln.split("refs/tags/")[-1] for ln in ls.stdout.strip().splitlines() if "refs/tags/" in ln]
            print(f"    该源可达，tag 名或异：可用 tag 示例（前10）: {', '.join(tags[:10])}")

    if not ok:
        print(f"未取得源码（尝试过：{attempts}）。可 --ref 用正确 tag，或 --url 提供私有/内网地址。", file=sys.stderr)
        return 1

    print("当前检出版本：", head_version(target))
    print(str(target))
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
