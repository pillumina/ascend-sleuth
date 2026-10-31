#!/usr/bin/env python3
# groom_common.py —— Agent Groom 的确定性公共层（无模型调用、无网络调用）
#
# 这一层只做四件事，四个脚本共用同一份口径：
#   1. 找到仓库、找到"共享 inbox"（草稿与评估状态都锚在主检出，worktree 里跑也写同一份）；
#   2. 草稿发现（兼容现有平铺 `<id>.case.yaml` 与 V2 目录形态 `<uuid>/case.yaml`）；
#   3. 评估状态文件的读写（原子写 + 同克隆写锁 + 人决定与 agent 建议分家）；
#   4. git / YAML 的小工具。
#
# 为什么状态文件落在 inbox 下而不是 case 文件里：
#   - 草稿是**产出物**，评估是**过程状态**。把 assessment 写进 case.yaml 会让"草稿内容"
#     与"读过它的哪一版知识"耦合，重跑 groom 就会改草稿字节（草稿一旦提交过 PR，
#     字节变化意味着 PR diff 变化），而且人决定会与 agent 建议互相覆盖。
#   - inbox 是 .gitignore 的本地队列（`postmortems/inbox/*`），sidecar 天然不进 git，
#     符合"本地状态只在本机"的边界；要进 PR 的是**marker**（groom_record.py --pr-marker），
#     不是整个状态文件。

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 环境问题，明确报错而不是静默
    sys.exit("需要 PyYAML：pip install pyyaml")

from exec_log_path import log_lock, resolve_checkout_dir  # noqa: E402

SCHEMA_ASSESSMENT = "groom-assessment/v1"
SCHEMA_SNAPSHOT = "groom-snapshot/v1"
SCHEMA_WORK_ORDER = "groom-work-order/v1"
SCHEMA_RESULT = "groom-result/v1"

VALID_CLASSIFICATIONS = ("duplicate", "covered", "variant", "new_pattern", "ambiguous")
VALID_CONFIDENCE = ("high", "medium", "low")
VALID_AXES = ("root_cause", "mechanism", "trigger", "symptoms", "fix", "environment", "verification")
VALID_AXIS_VERDICTS = ("same", "different", "unknown")
VALID_HUMAN_DECISIONS = ("new_pattern", "variant", "covered", "defer", "reject")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run_git(args, cwd, check=True, timeout=120):
    """跑一条 git 命令。stdout/stderr 一律 UTF-8 解码（Windows 控制台代码页不参与）。"""
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败（{proc.returncode}）：{proc.stderr.strip()}")
    return proc


def repo_root(path: Path) -> Path:
    p = run_git(["rev-parse", "--show-toplevel"], cwd=path)
    return Path(p.stdout.strip()).resolve()


def short_sha(sha: str) -> str:
    return (sha or "")[:12]


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def atomic_write_text(path: Path, text: str) -> None:
    """同目录临时文件 + fsync + os.replace；崩溃点最多留下 `.tmp`，读者不会看到半份。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def dump_yaml(obj) -> str:
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=1000)


def load_yaml(path: Path):
    with open(path, encoding="utf-8-sig") as fh:
        return yaml.safe_load(fh)


def load_json(path: Path):
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def dump_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def sanitize_key(key: str) -> str:
    """草稿 key → 文件名安全形式。保留可读前缀，后缀加内容哈希防碰撞。"""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", key).strip("-") or "draft"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"{safe[:80]}-{digest}"


def shared_inbox(root: Path) -> Path:
    """草稿队列与 groom 状态都落在**主检出**的 inbox（worktree 里跑也一致）。"""
    path, _where, _rel = resolve_checkout_dir("inbox", root)
    return Path(path)


@dataclass
class Draft:
    key: str
    case_path: Path
    layout: str                  # flat | directory
    postmortem_path: Path = None
    sources_path: Path = None

    def relative_case(self, root: Path) -> str:
        try:
            return str(self.case_path.resolve().relative_to(root.resolve())).replace("\\", "/")
        except ValueError:
            return str(self.case_path)


def find_drafts(inbox: Path) -> list:
    """扫描 inbox，返回可消费草稿。

    两种形态：
      - flat：`<case-id>.case.yaml`（现有 to-postmortem 的落点）+ 可选同名 `.md`；
      - directory：`<uuid>/case.yaml`（V2 预留形态）+ 可选 `postmortem.md` / `sources.yaml`。
    刻意不读 `<uuid>/sources.yaml` 当作草稿：它是来源说明，不承载 case 内容。
    """
    drafts = []
    if not inbox.is_dir():
        return drafts
    for path in sorted(inbox.glob("*.case.yaml")):
        if path.name.startswith("_"):
            continue
        stem = path.name[: -len(".case.yaml")]
        md = inbox / f"{stem}.md"
        drafts.append(Draft(key=stem, case_path=path, layout="flat",
                            postmortem_path=md if md.exists() else None))
    for child in sorted(inbox.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
            continue
        case = child / "case.yaml"
        if not case.exists():
            continue
        pm = child / "postmortem.md"
        src = child / "sources.yaml"
        drafts.append(Draft(key=child.name, case_path=case, layout="directory",
                            postmortem_path=pm if pm.exists() else None,
                            sources_path=src if src.exists() else None))
    return drafts


def draft_cases(draft: Draft) -> list:
    data = load_yaml(draft.case_path)
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"{draft.case_path}: 顶层缺 `cases` 列表")
    return [c for c in data["cases"] if isinstance(c, dict)]


def assessment_path(inbox: Path, key: str) -> Path:
    return inbox / ".groom" / "assessments" / f"{sanitize_key(key)}.yaml"


def load_assessment(inbox: Path, key: str) -> dict:
    path = assessment_path(inbox, key)
    if not path.exists():
        return {}
    data = load_yaml(path)
    return data if isinstance(data, dict) else {}


def write_assessment(inbox: Path, key: str, doc: dict) -> Path:
    """写评估状态：同克隆写锁 + 原子替换。人决定由调用方原样带回来，本函数不生成它。"""
    path = assessment_path(inbox, key)
    with log_lock(path):
        atomic_write_text(path, dump_yaml(doc))
    return path


def case_id_of(case: dict) -> str:
    return str(case.get("id") or "").strip()


def draft_text_of(case: dict) -> str:
    """给候选检索用的草稿文本：症状与根因/修复都进，标签与标题进。

    为什么把 root_cause/fix 也放进检索：措辞完全不同的两条知识，症状可能只共享
    `HCCL` 一个词，但根因里的"collective timeout"与修复里的"重配 IP"是对得上的。
    检索只负责**把候选端到人/agent 面前**，不负责判重。
    """
    symptoms = case.get("symptoms") or []
    if isinstance(symptoms, str):
        symptoms = [symptoms]
    parts = [
        str(case.get("title") or ""),
        " ".join(str(s) for s in symptoms),
        str(case.get("root_cause") or ""),
        str(case.get("fix") or ""),
        " ".join(str(t) for t in (case.get("tags") or [])),
    ]
    # diagnosis 的命令与期望里常带错误码/环境变量，是强检索信号
    for step in case.get("diagnosis") or []:
        if isinstance(step, dict):
            parts.append(str(step.get("command_template") or ""))
            parts.append(str(step.get("expected") or ""))
    return "\n".join(p for p in parts if p)


def sha_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def case_fingerprint(case: dict) -> str:
    """草稿 case 的内容指纹（用于判断评估之后草稿是否被改过）。"""
    return sha_of_text(json.dumps(case, ensure_ascii=False, sort_keys=True))


# 评估授权绑定的是**安全相关的 Case 内容**，不是文件字节：升格时 id / 文件名 / title 可以变，
# 但根因、修复、适用条件、严重度、诊断/修复步骤（含顺序与 rollback）变了，旧评估就不再授权。
CANONICAL_CONTENT_FIELDS = (
    "category", "tags", "symptoms", "root_cause", "fix", "compat", "platforms",
    "severity", "fix_side_effects", "fix_type",
    "quickly_check", "diagnosis", "verification",
)
#: 这些列表的顺序没有语义（集合），可以排序；其余列表（尤其 diagnosis）必须保序。
SET_LIKE_FIELDS = {"tags", "platforms", "fix_side_effects"}


def _canon_value(value, id_token=None, sort_list=False):
    if isinstance(value, str):
        text = value  # 命令、正则与修复中的空白可能有语义，必须逐字绑定。
        if id_token:
            # 升格时草稿建议 id → 最终 Case ID 是允许的变化；判据里的 id 只是占位符。
            text = re.sub(rf"(?<![A-Za-z0-9_-]){re.escape(str(id_token))}(?![A-Za-z0-9_-])",
                          "<CASE_ID>", text)
        return text
    if isinstance(value, list):
        items = [_canon_value(v, id_token, sort_list=False) for v in value]
        if sort_list:
            return sorted(items, key=lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True))
        return items
    if isinstance(value, dict):
        return {str(k): _canon_value(v, id_token) for k, v in sorted(value.items())}
    return value


def canonical_case_content(case: dict) -> dict:
    """把 case 压成可比较的安全内容（不含 id / 文件名 / title / 观测字段）。

    `quickly_check` / `diagnosis` 里出现本 case 的 id 时，先换成 `<CASE_ID>`：
    升格允许改 id，同一条判据不应因为 id 改名而被判成"内容变了"。
    `diagnosis` 的步骤顺序、`fix_on_mismatch`、`rollback`、`severity`、`fix_side_effects`
    都进入绑定；只对 tags / platforms / fix_side_effects 这类集合列表排序。
    """
    id_token = case.get("id")
    out = {}
    for field in CANONICAL_CONTENT_FIELDS:
        if field in case:
            out[field] = _canon_value(case[field], id_token,
                                      sort_list=field in SET_LIKE_FIELDS)
    return out


def sha256_full(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_content_sha(case: dict) -> str:
    return sha256_full(json.dumps(canonical_case_content(case), ensure_ascii=False, sort_keys=True))


def stable_sha(obj) -> str:
    return sha256_full(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def work_order_id(order: dict) -> str:
    """工作单的身份：快照 commit + 草稿指纹 + 候选集。结果必须回显它。"""
    return stable_sha({
        "schema": order.get("schema"),
        "snapshot_commit": (order.get("snapshot") or {}).get("commit"),
        "draft_key": (order.get("draft") or {}).get("draft_key"),
        "draft_sha256": (order.get("draft") or {}).get("case_sha256"),
        "candidates": sorted(
            [{"id": str(c.get("id")), "content_sha256": c.get("content_sha256")}
             for c in order.get("candidates") or []],
            key=lambda c: c["id"],
        ),
    })


def compute_assessment_id(commit: str, draft_key: str, draft_sha: str, content_sha: str,
                          candidate_bindings: list, result_hashes: list, reviewer_hashes: list) -> str:
    """一次评估的身份：同一 commit + 同一草稿内容 + 同一候选内容 + 同一结果字节。"""
    return stable_sha({
        "schema": "groom-assessment-id/v2",
        "commit": commit,
        "draft_key": draft_key,
        "draft_sha256": draft_sha,
        "content_sha256": content_sha,
        "candidates": sorted(candidate_bindings, key=lambda c: str(c.get("id"))),
        "results": sorted(result_hashes),
        "reviewers": sorted(reviewer_hashes),
    })


def normalize_commit(repo: Path, ref: str):
    """ref → commit（失败返回 None）。"""
    proc = run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo, check=False)
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    if not older or not newer:
        return False
    return run_git(["merge-base", "--is-ancestor", older, newer], cwd=repo, check=False).returncode == 0


def knowledge_changes(repo: Path, older: str, newer: str) -> list:
    proc = run_git(["diff", "--name-only", f"{older}..{newer}", "--", "knowledge"], cwd=repo, check=False)
    if proc.returncode != 0:
        return []
    # 生成物不是知识内容：索引重建不应把评估判成 stale。
    return [l for l in proc.stdout.splitlines()
            if l.strip() and "knowledge/_index" not in l.replace("\\", "/")]
