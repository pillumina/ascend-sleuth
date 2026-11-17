"""GitHub issue 源：包现有 ``gh`` / ``fetch_issues`` 逻辑。"""

from typing import Any, Dict, List

from ..adapters import AdapterError, load_legacy


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


class GitHubSource:
    """GitHub 实现；``source_id`` 带 repo，避免不同仓的 state/来源撞键。"""

    def __init__(self, repo: str, loader=None) -> None:
        self.repo = str(repo)
        self._loader = loader or load_legacy

    @property
    def source_id(self) -> str:
        return f"github/{self.repo}"

    def _module(self):
        return self._loader("fetch_issues")

    def _gh_api(self, url: str) -> Any:
        module = self._module()
        try:
            return module.gh_api(url)
        except (AdapterError, KeyboardInterrupt):
            raise
        except BaseException as exc:
            raise _wrap_gh_error(exc) from exc

    def list_issues(self, repo: str, labels=None, since=None,
                    state: str = "closed") -> List[Dict[str, Any]]:
        repo = repo or self.repo
        url = f"repos/{repo}/issues?state={state}&per_page=100"
        wanted = _labels(labels)
        if wanted:
            url += "&labels=" + ",".join(wanted)
        if since:
            url += f"&since={since}"
        items = self._gh_api(url)
        if not isinstance(items, list):
            raise AdapterError("gh issues response must be a list")
        module = self._module()
        return [module.slim(item) for item in items
                if item.get("pull_request") is None]

    def fetch_issue(self, repo: str, number: Any) -> Dict[str, Any]:
        repo = repo or self.repo
        if number is None or str(number).strip() == "":
            raise AdapterError("cannot fetch issue body without a number")
        payload = self._gh_api(f"repos/{repo}/issues/{number}")
        if not isinstance(payload, dict):
            raise AdapterError(f"gh issue response for #{number} must be an object")
        return {
            "title": payload.get("title") or "",
            "body": payload.get("body") or "",
            "closed_at": payload.get("closed_at"),
        }
