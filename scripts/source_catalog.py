#!/usr/bin/env python3
"""source_catalog.py —— 源码仓目录：加载、校验、候选计算。

数据在仓库根的 `source-catalog.d/<层>.yaml`，一层一个文件。新增一个仓只改数据，
不改脚本；`python3 scripts/src_fetch.py --self-test` 校验结构并跑真实签名用例。

本模块不联网、不碰缓存，只做纯数据换算，供 `src_fetch.py` 调用。为什么单独成模块：
仓表以前写在 `src_fetch.py` 的常量里，补一个仓要改 Python；拆出来后
「数据面」（层、仓、别名、host、签名规则）与「引擎面」（解析版本、拉取、校验）分开。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DATA_DIR_NAME = "source-catalog.d"
HOSTS_ALLOWED = {"github", "gitcode", "gitee", "custom"}
RULE_KEYS = {"all_of", "any_of", "primary", "discriminators", "base", "fallback"}
KEYWORD_FIELDS = ("all_of", "any_of", "discriminators", "base", "primary")


def norm_key(text: str) -> str:
    """别名归一：去空白、尾部斜杠与 .git，转小写（已知表查询与去重都用它）。"""
    return (text or "").strip().rstrip("/").removesuffix(".git").lower()


@dataclass
class Repo:
    canonical: str
    sources: list
    aliases: list
    why: str
    fast_path: bool
    discover: dict | None
    layer: str

    @property
    def org(self) -> str:
        return self.canonical.split("/", 1)[0]

    @property
    def short(self) -> str:
        return self.canonical.split("/", 1)[1] if "/" in self.canonical else self.canonical


@dataclass
class Org:
    name: str
    host: str
    enumerable: bool
    note: str
    layers: set = field(default_factory=set)


class Catalog:
    """一次加载后的只读视图；所有查询都不再读盘。"""

    def __init__(self, base: Path | None = None):
        self.base = Path(base) if base else None
        self.problems: list[str] = []
        self.repos: dict[str, Repo] = {}
        self.known: dict[str, tuple[str, list]] = {}
        self.orgs: dict[str, Org] = {}
        self.self_tests: list[tuple[str, str, str]] = []   # (org, sig, expect canonical)
        self.layers: list[str] = []
        self.titles: dict[str, str] = {}
        self._alias_owner: dict[str, str] = {}
        self._load()

    # ---------------------------------------------------------------- 加载
    def _load(self) -> None:
        if self.base is None:
            self.problems.append("没有给数据目录")
            return
        files = sorted(self.base.glob("*.yaml"))
        if not files:
            self.problems.append(f"数据目录里没有 YAML 文件：{self.base}")
            return
        for path in files:
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as e:
                self.problems.append(f"{path.name}: 读不出 YAML（{e}）")
                continue
            if not isinstance(doc, dict):
                self.problems.append(f"{path.name}: 顶层不是映射")
                continue
            self._load_layer(path, doc)
        self._build_known()

    def _load_layer(self, path: Path, doc: dict) -> None:
        layer = str(doc.get("layer") or path.stem)
        if layer in self.layers:
            self.problems.append(f"{path.name}: layer「{layer}」重复")
        self.layers.append(layer)
        if doc.get("title"):
            self.titles[layer] = str(doc["title"])

        for org in doc.get("orgs") or []:
            if not isinstance(org, dict) or not org.get("name"):
                self.problems.append(f"{path.name}: orgs 条目缺 name")
                continue
            name = str(org["name"])
            host = str(org.get("host") or "")
            if host not in HOSTS_ALLOWED:
                self.problems.append(f"{path.name}: 组织「{name}」host 非法：{host!r}")
            prev = self.orgs.get(name)
            if prev and prev.host != host:
                self.problems.append(f"{path.name}: 组织「{name}」host 与已加载的层不一致")
            if prev is None:
                self.orgs[name] = Org(name, host, bool(org.get("enumerable")),
                                      str(org.get("note") or ""), {layer})
            else:
                prev.enumerable = prev.enumerable or bool(org.get("enumerable"))
                prev.layers.add(layer)

        for repo in doc.get("repos") or []:
            self._load_repo(path, layer, repo)

        for item in doc.get("self_test") or []:
            if not isinstance(item, dict) or not item.get("sig") or not item.get("expect"):
                self.problems.append(f"{path.name}: self_test 条目要同时有 sig 与 expect")
                continue
            expect = str(item["expect"])
            org = str(item.get("org") or expect.split("/", 1)[0])
            self.self_tests.append((org, str(item["sig"]), expect))

    def _load_repo(self, path: Path, layer: str, repo: dict) -> None:
        if not isinstance(repo, dict) or not repo.get("repo"):
            self.problems.append(f"{path.name}: repos 条目缺 repo")
            return
        canonical = str(repo["repo"])
        if canonical in self.repos:
            self.problems.append(f"{path.name}: 仓「{canonical}」重复声明")
            return
        sources = repo.get("sources") or []
        if not isinstance(sources, list) or not sources:
            self.problems.append(f"{path.name}: 仓「{canonical}」缺 sources")
            sources = []
        for src in sources:
            if not isinstance(src, dict):
                self.problems.append(f"{path.name}: 仓「{canonical}」的 sources 条目不是映射")
                continue
            host = str(src.get("host") or "")
            if host not in HOSTS_ALLOWED:
                self.problems.append(f"{path.name}: 仓「{canonical}」host 非法：{host!r}")
            if host == "custom":
                if not src.get("url"):
                    self.problems.append(f"{path.name}: 仓「{canonical}」custom host 缺 url")
            elif not (src.get("owner") and src.get("repo")):
                self.problems.append(f"{path.name}: 仓「{canonical}」的来源缺 owner 或 repo")
        aliases = [str(a) for a in (repo.get("aliases") or [])]
        discover = repo.get("discover")
        if discover is not None:
            if not isinstance(discover, dict):
                self.problems.append(f"{path.name}: 仓「{canonical}」discover 不是映射")
                discover = None
            else:
                unknown = set(discover) - RULE_KEYS
                if unknown:
                    self.problems.append(f"{path.name}: 仓「{canonical}」discover 未知字段：{sorted(unknown)}")
                for key in KEYWORD_FIELDS:
                    for kw in discover.get(key) or []:
                        if str(kw) != str(kw).lower():
                            self.problems.append(
                                f"{path.name}: 仓「{canonical}」discover.{key} 关键词含大写（会静默不匹配）：{kw}")
                if not (discover.get("all_of") or discover.get("any_of")):
                    self.problems.append(f"{path.name}: 仓「{canonical}」discover 至少要 all_of 或 any_of")
        self.repos[canonical] = Repo(
            canonical=canonical,
            sources=sources,
            aliases=aliases,
            why=str(repo.get("why") or ""),
            fast_path=bool(repo.get("fast_path", True)),
            discover=discover,
            layer=layer,
        )

    def _build_known(self) -> None:
        for repo in self.repos.values():
            if not repo.fast_path:
                continue
            for key in [repo.canonical, *repo.aliases]:
                norm = norm_key(key)
                if not norm:
                    continue
                owner = self._alias_owner.get(norm)
                if owner and owner != repo.canonical:
                    self.problems.append(
                        f"别名「{key}」同时指向 {owner} 与 {repo.canonical}（已知表查询会看运气）")
                    continue
                self._alias_owner[norm] = repo.canonical
                self.known[norm] = (repo.canonical, repo.sources)

    # ---------------------------------------------------------------- 查询
    def lookup(self, repo: str):
        """返回 (canonical, sources) 或 (输入原样, None)。

        未登记时保留调用方给的写法：GitCode 等 host 的仓路径可能区分大小写，
        静默转小写会把一个能取到的仓变成取不到。
        """
        key = norm_key(repo)
        hit = self.known.get(key)
        if hit is not None:
            return hit
        # 已知表是别名快表；目录里登记过的仓（fast_path: false 或仅候选）按 canonical 也能取地址。
        # 不这样做时，显式写 canonical 的仓会被当成未知仓默认去 GitHub 找，取不到正确的 host。
        for canonical, item in self.repos.items():
            if norm_key(canonical) == key:
                return (canonical, list(item.sources))
        return (repo.strip().rstrip("/").removesuffix(".git"), None)

    def sources_for(self, canonical: str) -> list | None:
        """按 canonical 名取 sources，**不看 fast_path**：签名候选里的仓（如 pyasc）也能拿到地址。"""
        repo = self.repos.get(canonical)
        return list(repo.sources) if repo else None

    def discover_repos(self, org: str) -> list[Repo]:
        return [r for r in self.repos.values() if r.org == org and r.discover]

    def org_repos(self, org: str) -> list[Repo]:
        return [r for r in self.repos.values() if r.org == org]

    def candidates(self, org: str, sig: str) -> list[tuple[str, str, int]]:
        """签名 → [(仓短名, why, 命中分)]：主候选优先、非兜底优先、分高优先、文件顺序。"""
        toks, flat = signature_tokens(sig)
        hits = []
        for order, repo in enumerate(self.discover_repos(org)):
            score, primary, fallback = _rule_score(repo.discover or {}, toks, flat)
            if score:
                hits.append((order, repo, score, primary, fallback))
        hits.sort(key=lambda h: (not h[3], h[4], -h[2], h[0]))
        return [(repo.short, repo.why, score) for _o, repo, score, _p, _f in hits]

    def is_fallback(self, org: str, sig: str, repo_short: str) -> bool:
        toks, flat = signature_tokens(sig)
        for repo in self.discover_repos(org):
            if repo.short == repo_short:
                _score, _primary, fallback = _rule_score(repo.discover or {}, toks, flat)
                return fallback
        return False

    def validate(self) -> list[str]:
        """结构校验：self_test 指向的仓必须在已知或候选表里，组织必须在 orgs 里声明。"""
        problems = list(self.problems)
        for org, sig, expect in self.self_tests:
            if expect not in self.repos:
                problems.append(f"self_test：期望仓「{expect}」不存在")
                continue
            if self.repos[expect].org != org:
                problems.append(f"self_test：「{expect}」不属于组织「{org}」")
            if org not in self.orgs:
                problems.append(f"self_test：组织「{org}」没有在 orgs 里声明")
        return problems

    def run_self_tests(self) -> list[str]:
        failures = []
        for org, sig, expect in self.self_tests:
            got = [c[0] for c in self.candidates(org, sig)]
            short = self.repos[expect].short if expect in self.repos else expect
            if short not in got:
                failures.append(f"签名「{sig}」应命中 {expect}，实际 {got or '无候选'}")
        return failures


# ---------------------------------------------------------------- 候选计算（纯函数）
def signature_tokens(sig: str):
    """报错签名 → 词元集合 + 归一文本。用词元边界匹配，不做子串匹配。"""
    tokens = set()
    for w in re.findall(r"[A-Za-z0-9]+", sig or ""):
        tokens.add(w.lower())
        parts = [p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", w)]
        tokens.update(parts)
        head, tail = "".join(parts), "_".join(parts)
        tokens.add(head)
        for i in range(len(parts)):
            for j in range(i + 1, len(parts) + 1):
                tokens.add("".join(parts[i:j]))
        for sep in ("_", "-", "::"):
            tokens.update(p.lower() for p in w.split(sep) if p)
    flat_all = "".join(sorted(tokens))
    return tokens, flat_all + (sig or "").lower().replace("_", "").replace("-", "")


def boundary_components(tok: str) -> set:
    """词元里真边界处的部件：`hcclAllReduce` → {hccl, hcclall, …}。

    用来挡假阳性：`geometry` 里的 `ge` 不是边界，不该命中 `ge` 层。
    """
    out = set()
    for m in re.finditer(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z0-9])(?=[A-Z][a-z])", tok):
        out.add(tok[:m.start()].lower())
    return out


def _kw_hit(kw: str, toks, flat: str) -> bool:
    """单关键词命中判定（宽松，用于算分排序）。"""
    if kw in toks:
        return True
    if len(kw) >= 6 and (kw in flat or f"::{kw}" in flat or f"_{kw}" in flat):
        return True
    for t in toks:
        if t == kw or t.startswith(kw + "_") or t.startswith(kw + "-"):
            return True
        if re.match(rf"^{re.escape(kw)}(?![a-z])", t):
            return True
        if len(t) >= 3 and t.endswith(kw):
            return True
        if kw in boundary_components(t):
            return True
    return False


def _kw_whole(kw: str, toks) -> bool:
    """严格命中：关键词必须是完整词元，用于判定主候选。"""
    return kw in toks


def _rule_score(rule: dict, toks, flat: str):
    """→ (命中分, 是否命中主关键词, 是否只是兜底命中)；all_of 缺一即为 (0, False, False)。"""
    allof = rule.get("all_of") or []
    anyof = rule.get("any_of") or []
    if not allof and not anyof:
        return 0, False, False
    if allof and not all(_kw_hit(k, toks, flat) for k in allof):
        return 0, False, False
    score = 2 * len(allof)
    if anyof and not any(_kw_hit(k, toks, flat) for k in anyof):
        return 0, False, False
    score += 2 if anyof else 0
    discrim_hit = any(_kw_hit(k, toks, flat) for k in (rule.get("discriminators") or []))
    if not discrim_hit:
        score += 2 if any(_kw_hit(k, toks, flat) for k in (rule.get("base") or [])) else 0
    primary = any(_kw_whole(k, toks) for k in (rule.get("primary") or []))
    return score, primary, (bool(rule.get("fallback")) and not discrim_hit)


def load_catalog(base: Path | str | None = None) -> Catalog:
    return Catalog(Path(base) if base else None)


def default_dir(root: Path) -> Path:
    return Path(root) / DATA_DIR_NAME
