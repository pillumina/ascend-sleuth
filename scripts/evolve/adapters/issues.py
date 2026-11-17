"""GitHub issue → 诊断候选样本。

管线分三段，和 ``issue-ingest`` skill 的既有分工保持一致：

1. ``fetch_metadata`` 只拉精简元数据（不拉 body）；
2. ``filter_candidates`` 复用 ``issue_filter`` 的硬过滤与启发式排序；
3. 只对真正要建样本的候选调 ``fetch_body`` 取首帖正文，再交给 ``SampleStore``。

候选一律是 ``candidate``，``expected=None``：issue 的评论或 resolution 不是答案，
答案要维护者用 ``sample set-answer`` 补，之后才可能过 review。这样 ingest 不会把
“issue 里有人猜的根因”自动写成真值。
"""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import AdapterError, load_legacy
from ..samples import SampleStore, StoreError

MIN_BODY_CHARS = 20
SOURCE_PREFIX = "github/"
DEFAULT_AVOID_LABELS = ("stale", "wait-feedback")


def _labels(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    out: List[str] = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else item
        text = str(name or "").strip()
        if text:
            out.append(text)
    return out


def _processed_numbers(value: Any) -> set:
    numbers = set()
    for item in value or []:
        try:
            numbers.add(int(item))
        except (TypeError, ValueError):
            continue
    return numbers


def _wrap_gh_error(exc: BaseException) -> AdapterError:
    if isinstance(exc, FileNotFoundError):
        return AdapterError(
            "gh CLI not found; install GitHub CLI and run `gh auth login` before "
            "ingesting issues"
        )
    stderr = str(getattr(exc, "stderr", "") or "").strip()
    lowered = stderr.lower()
    if "auth" in lowered or "login" in lowered or "credential" in lowered:
        return AdapterError(
            "gh is not authenticated; run `gh auth login` before ingesting issues"
        )
    detail = stderr[-500:] if stderr else str(exc)
    return AdapterError(f"gh api failed: {detail}")


def _gh_api(url: str, module: Any = None) -> Any:
    module = module or load_legacy("fetch_issues")
    try:
        return module.gh_api(url)
    except (AdapterError, KeyboardInterrupt):
        raise
    except BaseException as exc:
        raise _wrap_gh_error(exc) from exc


def _url(repo: str, *, state: str, labels: Optional[Sequence[str]],
         since: Optional[str]) -> str:
    url = f"repos/{repo}/issues?state={state}&per_page=100"
    if labels:
        url += "&labels=" + ",".join(_labels(labels))
    if since:
        url += f"&since={since}"
    return url


def fetch_metadata(repo: str, labels: Optional[Sequence[str]] = None,
                   since: Optional[str] = None, state: str = "closed") -> List[Dict[str, Any]]:
    """拉精简元数据（number/title/comments/closed_at/state_reason/labels），不拉 body。

    与 ``scripts/fetch_issues.py`` 的 slim 输出一致，并在这里排除 PR；body 留给
    真正要建的候选按需单条取。
    """
    module = load_legacy("fetch_issues")
    items = _gh_api(
        _url(repo, state=state, labels=labels, since=since), module=module,
    )
    if not isinstance(items, list):
        raise AdapterError("gh issues response must be a list")
    return [module.slim(item) for item in items
            if item.get("pull_request") is None]


def fetch_body(repo: str, issue: Any) -> Dict[str, Any]:
    """只取首帖 title/body/closed_at；评论不进入样本 input。

    issue 可以是元数据字典或编号。评论里的 resolution 不是答案，本函数不读评论正文。
    """
    number = issue.get("number") if isinstance(issue, dict) else issue
    if number is None or str(number).strip() == "":
        raise AdapterError("cannot fetch issue body without a number")
    module = load_legacy("fetch_issues")
    payload = _gh_api(f"repos/{repo}/issues/{number}", module=module)
    if not isinstance(payload, dict):
        raise AdapterError(f"gh issue response for #{number} must be an object")
    return {
        "title": payload.get("title") or "",
        "body": payload.get("body") or "",
        "closed_at": payload.get("closed_at"),
    }


def _filter_with_stats(
    items: Iterable[Dict[str, Any]],
    processed: Any,
    labels: Optional[Sequence[str]],
    min_comments: int,
    avoid_labels: Sequence[str] = DEFAULT_AVOID_LABELS,
):
    module = load_legacy("issue_filter")
    want_labels = _labels(labels)
    done = _processed_numbers(processed)
    stats = {
        "skipped_pr": 0,
        "skipped_processed": 0,
        "skipped_no_label": 0,
        "skipped_low_comments": 0,
        "skipped_title": 0,
    }
    candidates = []
    for item in items:
        if not isinstance(item, dict):
            stats["skipped_pr"] += 1
            continue
        if not module.is_issue(item) and item.get("pull_request") is not None:
            stats["skipped_pr"] += 1
            continue
        number = item.get("number")
        try:
            number_int = int(number)
        except (TypeError, ValueError):
            number_int = None
        if number_int is not None and number_int in done:
            stats["skipped_processed"] += 1
            continue
        if want_labels and not module.has_label(item, want_labels):
            stats["skipped_no_label"] += 1
            continue
        if (item.get("comments") or 0) < min_comments:
            stats["skipped_low_comments"] += 1
            continue
        if module.title_skippable(item.get("title", "")):
            stats["skipped_title"] += 1
            continue
        candidates.append(item)
    candidates.sort(key=lambda item: module.heuristic_key(item, avoid_labels), reverse=True)
    return candidates, stats


def filter_candidates(
    items: Iterable[Dict[str, Any]],
    processed: Any,
    labels: Optional[Sequence[str]],
    min_comments: int = 3,
    limit: Optional[int] = 20,
    avoid_labels: Sequence[str] = DEFAULT_AVOID_LABELS,
) -> List[Dict[str, Any]]:
    """硬过滤 + 启发式排序；返回候选列表（limit 可为 None）。"""
    if not isinstance(min_comments, int) or isinstance(min_comments, bool) or min_comments < 0:
        raise AdapterError("min_comments must be a non-negative integer")
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
    ):
        raise AdapterError("limit must be a non-negative integer or None")
    candidates, _stats = _filter_with_stats(
        items, processed, labels, min_comments, avoid_labels=avoid_labels,
    )
    return candidates if limit is None else candidates[:limit]


def _slug(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "")).strip("-").upper()
    return cleaned or "REPO"


def candidate_id(repo: str, issue: Any) -> str:
    return f"GH-{_slug(repo)}-{str(issue).strip()}"


def issue_to_candidate(item: Dict[str, Any], body: Any, repo: str) -> Dict[str, Any]:
    """一条 issue 的 ``SampleStore.new`` 参数；纯函数，expected 留空给 review 补。

    ``body`` 可以是 ``fetch_body`` 的字典，也可以是正文字符串；只取 title/body，
    不把 comments/resolution 当答案。
    """
    if not isinstance(item, dict):
        raise AdapterError("issue metadata must be an object")
    number = item.get("number")
    if number is None or str(number).strip() == "":
        raise AdapterError("issue metadata must contain number")
    if isinstance(body, dict):
        body_text = body.get("body") or ""
        title = body.get("title") or item.get("title") or ""
        closed_at = body.get("closed_at") or item.get("closed_at")
    else:
        body_text = body or ""
        title = item.get("title") or ""
        closed_at = item.get("closed_at")
    labels = _labels(item.get("labels"))
    number_text = str(number).strip()
    return {
        "id": candidate_id(repo, number_text),
        "object_type": "diagnosis",
        "origin": "field",
        "purpose": "evaluation",
        "source": f"{SOURCE_PREFIX}{repo}#{number_text}",
        "input": {"title": str(title), "body": str(body_text)},
        "expected": None,
        "expected_kind": "resolution",
        "proposed": {
            "repo": repo,
            "issue": number,
            "labels": labels,
            "closed_at": closed_at,
            "url": f"https://github.com/{repo}/issues/{number_text}",
        },
    }


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"sources": {}}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot read ingest state {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise AdapterError(f"ingest state must be an object: {path}")
    if not isinstance(document.get("sources"), dict):
        document["sources"] = {}
    return document


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def ingest_issues(
    root: Any,
    repo: str,
    labels: Optional[Sequence[str]] = None,
    since: Optional[str] = None,
    min_comments: int = 3,
    limit: Optional[int] = 20,
    state_path: Any = None,
    store: Optional[SampleStore] = None,
    dry_run: bool = False,
    fetch_metadata_fn=None,
    fetch_body_fn=None,
) -> Dict[str, Any]:
    """拉元数据 → 硬过滤 → 按需取 body → 建候选。

    ``fetch_metadata_fn`` / ``fetch_body_fn`` 可注入；测试不联网。``dry_run`` 不写
    样本库也不写 state；成功后只把实际创建的编号追加 processed（原子写）。
    """
    if not isinstance(min_comments, int) or isinstance(min_comments, bool) or min_comments < 0:
        raise AdapterError("min_comments must be a non-negative integer")
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
    ):
        raise AdapterError("limit must be a non-negative integer or None")
    root_path = Path(root)
    store = store or SampleStore(root_path)
    state_file = Path(state_path) if state_path is not None else root_path / "ingest-state.json"
    if not state_file.is_absolute():
        state_file = root_path / state_file
    state = _load_state(state_file)
    source = f"{SOURCE_PREFIX}{repo}"
    source_state = state.setdefault("sources", {}).setdefault(source, {})
    processed = _processed_numbers(source_state.get("processed"))

    fetch_metadata_fn = fetch_metadata_fn or fetch_metadata
    fetch_body_fn = fetch_body_fn or fetch_body
    try:
        items = fetch_metadata_fn(repo, labels, since)
    except AdapterError:
        raise
    except Exception as exc:
        raise _wrap_gh_error(exc) from exc
    if not isinstance(items, list):
        raise AdapterError("fetch_metadata_fn must return a list")

    candidates, filter_stats = _filter_with_stats(
        items, processed, labels, min_comments,
    )

    stats: Dict[str, Any] = {
        "repo": repo,
        "source": source,
        "state_path": str(state_file),
        "total": len(items),
        "filtered": len(candidates),
        "created": 0,
        "created_ids": [],
        "created_paths": [],
        "would_create": [],
        "skipped_duplicate_source": 0,
        "skipped_duplicate_id": 0,
        "skipped_empty_body": 0,
        "skipped_short_body": 0,
        "skipped_feature_title": 0,
        "limit_reached": False,
        "dry_run": bool(dry_run),
        "state_updated": False,
        **filter_stats,
    }
    seen_sources = set()
    created_numbers = []
    for index, item in enumerate(candidates):
        planned = stats["created"] + len(stats["would_create"])
        if limit is not None and planned >= limit:
            stats["limit_reached"] = index < len(candidates)
            break
        try:
            body = fetch_body_fn(repo, item)
        except AdapterError:
            raise
        except Exception as exc:
            raise _wrap_gh_error(exc) from exc
        if not isinstance(body, dict):
            raise AdapterError("fetch_body_fn must return an object")
        body_text = str(body.get("body") or "").strip()
        if not body_text:
            stats["skipped_empty_body"] += 1
            continue
        if len(body_text) < MIN_BODY_CHARS:
            stats["skipped_short_body"] += 1
            continue
        title = body.get("title") or item.get("title") or ""
        module = load_legacy("issue_filter")
        if module.title_skippable(title):
            stats["skipped_feature_title"] += 1
            continue
        candidate = issue_to_candidate(item, body, repo)
        sample_id = candidate["id"]
        sample_source = candidate["source"]
        if sample_source in seen_sources or store.find_by_source(sample_source):
            stats["skipped_duplicate_source"] += 1
            continue
        if store.load(sample_id) is not None:
            stats["skipped_duplicate_id"] += 1
            continue
        if dry_run:
            stats["would_create"].append(sample_id)
            seen_sources.add(sample_source)
            continue
        try:
            sample = store.new(**candidate)
        except StoreError as exc:
            message = str(exc)
            if "duplicate source" in message:
                stats["skipped_duplicate_source"] += 1
                continue
            if "duplicate sample id" in message:
                stats["skipped_duplicate_id"] += 1
                continue
            raise AdapterError(f"cannot create issue candidate {sample_id}: {message}") from exc
        seen_sources.add(sample_source)
        stats["created"] += 1
        stats["created_ids"].append(sample.id)
        stats["created_paths"].append(str(store.path_for(sample.id)))
        created_numbers.append(int(item["number"]))
    if created_numbers and not dry_run:
        processed.update(created_numbers)
        source_state["processed"] = sorted(processed)
        try:
            _save_state(state_file, state)
        except OSError as exc:
            raise AdapterError(f"cannot write ingest state {state_file}: {exc}") from exc
        stats["state_updated"] = True
    return stats
