#!/usr/bin/env python3
"""gc_docs.py —— GitCode 文档面摄取：清单化扫描 → 增量判定 → 按需抓正文 → 记账

与 issue 摄取（fetch_issues.py / issue_filter.py）的分工与差别：

  同：两者都是"外部来源 → 知识库"的批量注入入口，都用一份状态文件做幂等
      （issue 用 ingest-state.json 的 processed issue 号；本脚本用 reference-ingest-state.json
      的 path × blob sha）。判定都在脚本里做，不花模型 token。

  异（为什么不能共用一份状态）：issue 面的单位是"一条 issue"，判过即封；文档面的单位是
      "一个文件路径"，而**文件会变**。所以键必须是 (path, sha) 而不是 path——否则上游改了一篇
      已经沉淀过的文档，第二轮既不会重抓也不会重判（改动静默丢失）。另外文档面必须记
      **"判过但决定不沉淀"**（`skipped` + 理由）：issue 面没有这一半，而一个文档仓里绝大多数
      文件属于此类；不记就会在每一轮被重新拿出来评估（重复烧 token，正是要防的事）。

三层成本结构（token 节省是设计目标，不是副产品）：

  ① scan   —— 只拉目录树（路径 + blob sha），不拉正文；增量结果打印成表。
               这一步与"读了多少字"无关，纯路径面，成本≈0。
  ② fetch  —— 只抓**筛过的**候选正文到本地缓存（ref-docs/，.gitignore），抓完按 git blob
              sha 逐字节校验（上游改过 / 抓到页壳都会当场报错，不静默入库）；
               之后 agent 读的是本地文件，重跑不重抓。
  ③ mark   —— 把判定与产出写回状态（幂等），下一轮 scan 直接跳过。

  正文缓存锚到**主检出**（scripts/exec_log_path.py 的 resolve_ref_docs，同 src-code 语义）：
  同一克隆的所有 worktree 共读一份，worktree 清理不丢。

用法：

  python3 scripts/gc_docs.py repos --org cann                 # 组织仓库清单（含 star/更新时间的选面依据）
  python3 scripts/gc_docs.py scan hccl --rank --top 40        # 增量扫描（新增/变更/未变），按路径关键词排序
  python3 scripts/gc_docs.py fetch hccl --paths a.md,b.md     # 抓候选正文到 ref-docs/，sha 校验
  python3 scripts/gc_docs.py fetch hccl --from-scan /tmp/x.txt # 抓 scan --json 落下的候选表
  python3 scripts/gc_docs.py mark hccl --path a.md --decision harvested --refs hccl-fault-diagnosis
  python3 scripts/gc_docs.py mark hccl --path b.md --decision skipped --note "纯 API 参考，无诊断判据"
  python3 scripts/gc_docs.py status                            # 各源决策分布（防重复抓取的可观测面）
  python3 scripts/gc_docs.py status hccl --decision pending    # 某源待评估清单

退出码：0 成功；2 用法/参数；3 源或路径不存在（ref 解析不到 / 路径不在树里）；4 网络或校验失败。

并发纪律（对齐 CLAUDE.md「串行操作」）：fetch / mark 是 read-modify-write，**同一克隆内必须串行**；
状态写入用临时文件 + 原子替换，避免半截 JSON。别手工改状态文件——`mark` 是唯一写入口。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from _stdio import pin_utf8_stdio

from exec_log_path import REF_DOCS_REL, describe_ref, resolve_ref_docs  # noqa: E402

API = "https://gitcode.com/api/v5"
RAW = "https://raw.gitcode.com"
STATE_REL = Path("reference-ingest-state.json")
ROOT = Path(__file__).resolve().parent.parent

# 文档面扩展名（默认口径）：只认"人写给人看的正文"，源码/构建/二进制一律不入
DOC_EXTS = (".md", ".rst", ".txt")
# 默认排除：这些路径是代码、生成物或与诊断无关的门面文件。
# 不排除 `docs/en/`（曾误列）：语言目录不是"重复内容"的同义词——实测 cann/runtime 的错误码参考
# **只在 docs/en/error_code_ref 下有**（docs/zh 只有 FAQ 与 api_ref），按语言一刀切会把整族文档静默漏掉。
# 真正的同内容双语重复由**每源 config.exclude** 处理（哪一侧是权威副本是逐仓事实，不是全局规则）。
DEFAULT_EXCLUDE = (
    ".gitcode/", ".github/", ".gitlab/", ".devcontainer/", "LICENSE", "SECURITY",
    "CHANGELOG", "CONTRIBUTING", "CODE_OF_CONDUCT", "third_party/", "cmake/", "tests/",
    "test/", "benchmark/", "translations/", "node_modules/", ".dsh/",
)
# 候选排序用的关键词（诊断相关性；命中即在路径层面已值得一看）。排序只影响"先看哪篇"，
# 不构成沉淀判据——判定一律在读过正文之后。
KW = re.compile(
    r"(error|err_|err-|fault|fail|troubleshoot|diagnos|faq|debug|precision|accurac|determinis"
    r"|perf|profil|tun(e|ing)|optimi|bottleneck|threshold|limit|restrict|constraint|support"
    r"|env|overflow|nan|hang|timeout|deadlock|oob|越界|故障|诊断|精度|性能|调优|定位|报错|错误码|排查|约束|限制)",
    re.I,
)


# ---------------------------------------------------------------- HTTP
def _http(url: str, retries: int = 4, timeout: int = 45) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ascend-sleuth/gc_docs"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429):          # 限流：退避后重试
                time.sleep(2 ** i)
                continue
            if e.code == 404:
                raise
            time.sleep(1 + i)
        except Exception as e:                # 网络抖动
            last = e
            time.sleep(1 + i)
    raise last if last else RuntimeError(f"unreachable: {url}")


def api_get(path: str, **params) -> dict:
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    return json.loads(_http(f"{API}{path}{q}").decode("utf-8", "replace"))


def api_pages(path: str, per_page: int = 100, max_pages: int = 40, **params) -> list:
    """分页拉全（GitCode trees API 默认每页 20，必须显式 per_page=100）。"""
    out, page = [], 1
    while page <= max_pages:
        d = api_get(path, per_page=per_page, page=page, **params)
        items = d.get("tree") if "tree" in d else d
        if not isinstance(items, list):
            break
        out += items
        if len(items) < per_page:
            break
        page += 1
    return out


def get_commit(owner: str, repo: str, ref: str):
    """ref（分支/tag）→ commit sha。**trees API 顶层的 `sha` 字段是 ref 名不是 commit**
    （实测：`/git/trees/master` 返回 `"sha": "master"`），所以缓存的版本目录与状态游标都必须
    从这里取，否则缓存目录会随分支漂移、"抓的是哪一版"不可判定。"""
    try:
        d = api_get(f"/repos/{owner}/{repo}/commits", sha=ref, per_page=1)
    except Exception:
        return None
    if isinstance(d, list) and d:
        return d[0].get("sha")
    return None


def get_tree(owner: str, repo: str, ref: str):
    """→ (commit_sha, [blob entries])；ref 解析不到 → (None, None)。"""
    items = []
    page = 1
    while page <= 40:
        try:
            d = api_get(f"/repos/{owner}/{repo}/git/trees/{ref}",
                        recursive=1, per_page=100, page=page)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, None
            raise
        t = d.get("tree") or []
        items += t
        if len(t) < 100:
            break
        page += 1
    if not items:
        return None, None
    return get_commit(owner, repo, ref), [x for x in items if x.get("type") == "blob"]


def blob_sha(raw: bytes) -> str:
    """本地算 git blob sha（sha1 of `blob <len>\0<content>`）——目录树里的 `sha` 就是它。

    为什么用它当完整性判据：树的 `md5` 字段与本文件内容**对不上**（实测同一文件 md5 三个值互不
    相等），拿它校验会把每一篇都判成"抓到了页壳"；而 git blob sha 本地可重算且逐字节敏感，
    正好覆盖两种真实事故——上游在扫描后改了文件、以及 raw 路径返回 HTML 页壳。
    """
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def default_branch(owner: str, repo: str) -> str:
    """仓库默认分支：先问元数据，问不到再按 master/main 探测（CANN 组织以 master 为主）。"""
    for cand in ("master", "main"):
        c, _ = get_tree(owner, repo, cand)
        if c:
            return cand
    return "master"


# ---------------------------------------------------------------- 状态
def load_state() -> dict:
    if STATE_REL.exists():
        return json.loads(STATE_REL.read_text(encoding="utf-8"))
    return {"version": 1, "sources": {}}


DOC_KEYS = ("sha", "decision", "at", "refs", "note")


def save_state(st: dict) -> None:
    """原子写 + 字段收口：doc 条目只保留 DOC_KEYS。

    为什么要在写侧收口：这份状态会被多轮批量写入，早期版本写过的字段（如已废弃的 `md5`——
    目录树的 md5 与文件内容对不上，改用 git blob sha 后不该留）会在文件里越积越多，
    而读者分不清哪个字段还有语义。收口让"状态里出现的字段"恒等于"当前有语义的字段"。
    """
    for src in (st.get("sources") or {}).values():
        for path, e in list((src.get("docs") or {}).items()):
            src["docs"][path] = {k: v for k, v in e.items() if k in DOC_KEYS}
    tmp = STATE_REL.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, STATE_REL)


def src_key(owner: str, repo: str) -> str:
    return f"gitcode/{owner}/{repo}"


def get_src(st: dict, owner: str, repo: str) -> dict:
    return st["sources"].setdefault(
        src_key(owner, repo),
        {"branch": None, "head_sha": None, "last_scan": None, "docs": {}},
    )


def doc_exts(src: dict) -> tuple:
    cfg = (src.get("config") or {}).get("exts")
    return tuple(cfg) if cfg else DOC_EXTS


def excluded(src: dict, path: str) -> bool:
    pats = tuple((src.get("config") or {}).get("exclude", DEFAULT_EXCLUDE))
    return any(p in path for p in pats)


# ---------------------------------------------------------------- 子命令
def cmd_repos(a) -> int:
    repos = api_pages(f"/orgs/{a.org}/repos")
    rows = []
    for r in repos:
        rows.append((r.get("stargazers_count") or 0, r.get("path") or r.get("name"),
                     (r.get("description") or "").replace("\n", " "), str(r.get("updated_at"))[:10]))
    rows.sort(reverse=True)
    if a.json:
        print(json.dumps([{"repo": p, "star": s, "updated": u, "desc": d}
                          for s, p, d, u in rows], ensure_ascii=False, indent=1))
    else:
        print(f"{a.org} 组织共 {len(rows)} 仓：")
        for s, p, d, u in rows:
            print(f"  {s:5d}★ {p:36s} {u}  {d[:70]}")
    return 0


def cmd_scan(a) -> int:
    st = load_state()
    owner, repo = a.owner, a.repo
    src = get_src(st, owner, repo)
    ref = a.ref or src.get("branch") or default_branch(owner, repo)
    commit, blobs = get_tree(owner, repo, ref)
    if commit is None:
        print(f"✗ {owner}/{repo} 的 ref「{ref}」解析不到（源可达但无该分支）", file=sys.stderr)
        return 3

    docs = {p: e for p, e in src["docs"].items()}
    cands, new, changed, unchanged, skipped_before = [], [], [], [], []
    for b in blobs:
        p = b["path"]
        if not p.endswith(doc_exts(src)) or excluded(src, p):
            continue
        if a.prefix and not p.startswith(tuple(a.prefix)):
            continue
        e = docs.get(p)
        if e is None:
            new.append((p, b))
        elif e.get("sha") != b.get("sha"):
            changed.append((p, b))
        else:
            (skipped_before if e.get("decision") in ("skipped", "harvested") else unchanged).append((p, b))
        cands.append((p, b, e))

    todo = new + changed
    scored = sorted(todo, key=lambda t: (-len(KW.findall(t[0])), t[0]))
    if a.top:
        scored = scored[:a.top]

    print(f"{owner}/{repo}@{ref}  commit={commit[:12]}  文档候选={len(cands)} "
          f"新增={len(new)} 变更={len(changed)} 已定={len(skipped_before)} 未变待评={len(unchanged)}")
    for p, b in scored:
        tag = "NEW " if any(p == x[0] for x in new) else "CHG "
        print(f"  {tag}[{len(KW.findall(p)):2d}] {p}")
    if not a.json and len(todo) > len(scored):
        print(f"  … 其余 {len(todo) - len(scored)} 条未列（--top 调整）")
    if a.json:
        print(json.dumps([{"path": p, "sha": b.get("sha"),
                           "state": "new" if any(p == x[0] for x in new) else "changed"}
                          for p, b in scored], ensure_ascii=False, indent=1))

    if not a.dry_run:
        src["branch"], src["head_sha"] = ref, commit
        src["last_scan"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        for p, b in todo:
            src["docs"].setdefault(p, {}).update({"sha": b.get("sha"), "decision": "pending"})
        save_state(st)
    return 0


def cmd_fetch(a) -> int:
    st = load_state()
    owner, repo = a.owner, a.repo
    src = get_src(st, owner, repo)
    ref = a.ref or src.get("branch") or default_branch(owner, repo)
    commit, blobs = get_tree(owner, repo, ref)
    if commit is None:
        print(f"✗ {owner}/{repo} 的 ref「{ref}」解析不到", file=sys.stderr)
        return 3
    by_path = {b["path"]: b for b in blobs}

    paths = []
    if a.from_scan:
        data = json.loads(Path(a.from_scan).read_text(encoding="utf-8"))
        paths += [d["path"] for d in data]
    if a.paths:
        paths += [p.strip() for p in a.paths.split(",") if p.strip()]
    if not paths:
        print("✗ 未给候选：用 --paths a.md,b.md 或 --from-scan <scan --json 输出>", file=sys.stderr)
        return 2

    cache_root, where = resolve_ref_docs(ROOT, explicit=Path(a.dest) if a.dest else None,
                                         local=a.local)
    dest = cache_root / owner / repo / commit[:12]
    print(f"缓存根：{describe_ref(cache_root, where)}")

    rc, fetched, missing = 0, 0, []
    for p in paths[: a.max_files]:
        b = by_path.get(p)
        if b is None:
            missing.append(p)
            continue
        out = dest / p
        if out.exists() and not a.force:
            print(f"  复用 {p}（{out.stat().st_size}B）")
            fetched += 1
            continue
        try:
            raw = _http(f"{RAW}/{owner}/{repo}/raw/{ref}/{urllib.parse.quote(p)}")
        except Exception as e:
            print(f"  ✗ {p} 抓取失败：{e}", file=sys.stderr)
            rc = 4
            continue
        if blob_sha(raw) != b.get("sha"):
            print(f"  ✗ {p} 内容 sha 与目录树不符（上游在扫描后改过 / 抓到了页壳）", file=sys.stderr)
            rc = 4
            continue
        if raw.lstrip().startswith(b"<!DOCTYPE html") or raw.lstrip().startswith(b"<html"):
            print(f"  ✗ {p} 抓到 HTML 页壳而非正文（该路径不是纯文本文件）", file=sys.stderr)
            rc = 4
            continue
        if len(raw) > a.max_bytes:
            print(f"  ! {p} 超 --max-bytes（{len(raw)}B）跳过——大文件按章节单独取", file=sys.stderr)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)
        print(f"  抓取 {p}（{len(raw)}B）→ {out}")
        fetched += 1
    print(f"完成：{fetched} 篇（缓存 {dest}）" + (f"，路径不在树里 {len(missing)}：{missing}" if missing else ""))
    return rc


def cmd_mark(a) -> int:
    st = load_state()
    owner, repo = a.owner, a.repo
    src = get_src(st, owner, repo)
    ref = a.ref or src.get("branch") or default_branch(owner, repo)
    for p in [x.strip() for x in a.path.split(",") if x.strip()]:
        e = src["docs"].setdefault(p, {})
        if not e.get("sha"):
            commit, blobs = get_tree(owner, repo, ref)
            b = next((x for x in (blobs or []) if x["path"] == p), None)
            if b is None:
                print(f"✗ {p} 不在 {owner}/{repo}@{ref} 的树里——路径写错或分支不对", file=sys.stderr)
                return 3
            e.update({"sha": b.get("sha")})
        e["decision"] = a.decision
        e["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if a.refs:
            e["refs"] = [r.strip() for r in a.refs.split(",") if r.strip()]
        if a.note:
            e["note"] = a.note
        print(f"  {a.decision:9s} {p}" + (f"  refs={e.get('refs')}" if e.get("refs") else ""))
    save_state(st)
    return 0


def cmd_triage(a) -> int:
    """仓级判定：这个仓整体纳不纳入先验层（不逐文档标记）。

    为什么需要它：文档级 mark 要求先把仓扫进台账（拉全树 + 逐文档记账），对**整仓不纳入**的仓
    （源码/模板/治理/行业/agent 知识仓）是纯浪费——扫大仓可能几分钟，而结论早就由仓的类别决定。
    仓级判定把"这个仓不纳入，理由是什么"变成一条可审计记录，同样是幂等台账的一部分：
    下一轮不必再扫、也不必再判。文档级 decision 与仓级 triage 并存，互不覆盖。
    """
    st = load_state()
    src = get_src(st, a.owner, a.repo)
    src["triage"] = {"decision": a.decision, "note": a.note,
                     "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    save_state(st)
    print(f"  {a.decision:9s} {a.owner}/{a.repo}" + (f"  [{a.note}]" if a.note else ""))
    return 0


def cmd_status(a) -> int:
    st = load_state()
    keys = [src_key(a.owner, a.repo)] if a.repo else sorted(st["sources"])
    if a.repo and keys[0] not in st["sources"]:
        print(f"✗ 状态里没有 {keys[0]}（先 scan）", file=sys.stderr)
        return 3
    for k in keys:
        s = st["sources"][k]
        docs = s.get("docs") or {}
        counts = {}
        for e in docs.values():
            counts[e.get("decision", "pending")] = counts.get(e.get("decision", "pending"), 0) + 1
        tri = (s.get("triage") or {}).get("decision")
        head = (s.get("head_sha") or "-")[:12]
        dist = " ".join(f"{d}={n}" for d, n in sorted(counts.items())) or "-"
        print(f"{k:34s} triage={tri or '-':10s} {s.get('branch')}@{head:12s} 扫描={s.get('last_scan') or '-'} 文档={len(docs)} {dist}")
        if a.decision:
            shown = 0
            for p, e in sorted(docs.items()):
                if e.get("decision") != a.decision:
                    continue
                if a.limit and shown >= a.limit:
                    print(f"    …（--limit {a.limit} 截断）")
                    break
                print(f"    {p}" + (f"  [{e.get('note')}]" if e.get("note") else ""))
                shown += 1
    print(f"\n状态文件：{STATE_REL}（唯一写入口是 mark；别手工改）")
    return 0


# ---------------------------------------------------------------- CLI
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--org", default="cann", help="GitCode 组织（默认 cann）")
    ap.add_argument("--owner", default=None, help="仓库 owner（默认同 --org）")
    ap.add_argument("--local", action="store_true", help="正文缓存用当前检出（默认锚主检出）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("repos", help="列组织仓库")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_repos)

    p = sub.add_parser("scan", help="增量扫描文档面（新增/变更/未变）")
    p.add_argument("repo")
    p.add_argument("--ref", help="分支/tag/commit（默认仓库默认分支）")
    p.add_argument("--prefix", action="append", help="只扫该路径前缀（可多次）")
    p.add_argument("--rank", action="store_true", help="按路径关键词排序（默认即按分排序）")
    p.add_argument("--top", type=int, default=0, help="只列前 N 条")
    p.add_argument("--json", action="store_true", help="候选表以 JSON 输出（供 fetch --from-scan）")
    p.add_argument("--dry-run", action="store_true", help="不更新状态游标")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("fetch", help="抓候选正文到 ref-docs/ 缓存")
    p.add_argument("repo")
    p.add_argument("--ref")
    p.add_argument("--paths", help="逗号分隔的路径")
    p.add_argument("--from-scan", help="scan --json 的输出文件")
    p.add_argument("--dest", help="缓存根（默认解析到主检出 ref-docs/）")
    p.add_argument("--force", action="store_true", help="缓存已存在也重抓")
    p.add_argument("--max-bytes", type=int, default=1_500_000)
    p.add_argument("--max-files", type=int, default=60)
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("mark", help="写回判定与产出（幂等）")
    p.add_argument("repo")
    p.add_argument("--ref")
    p.add_argument("--path", required=True, help="逗号分隔的路径")
    p.add_argument("--decision", required=True,
                   choices=["pending", "harvested", "skipped"])
    p.add_argument("--refs", help="逗号分隔的 reference id（harvested 时填）")
    p.add_argument("--note", help="一句话理由（skipped 必填，便于下一轮不复核）")
    p.set_defaults(fn=cmd_mark)

    p = sub.add_parser("triage", help="仓级判定（整仓纳不纳入，不逐文档标记）")
    p.add_argument("repo")
    p.add_argument("--decision", required=True, choices=["selected", "candidate", "rejected"])
    p.add_argument("--note", required=True, help="一句话理由（可审计：下一轮据此不再评估）")
    p.set_defaults(fn=cmd_triage)

    p = sub.add_parser("status", help="各源决策分布 / 某源待评估清单")
    p.add_argument("repo", nargs="?")
    p.add_argument("--decision", help="列该判定的路径（如 pending / skipped）")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(fn=cmd_status)

    a = ap.parse_args()
    a.owner = a.owner or a.org
    if a.cmd == "mark" and a.decision == "skipped" and not a.note:
        print("✗ skipped 必须带 --note（一句话理由）——否则下一轮会重新评估同一篇", file=sys.stderr)
        return 2
    return a.fn(a)


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
