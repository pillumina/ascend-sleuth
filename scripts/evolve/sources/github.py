"""GitHub issue 源：包现有 ``gh`` / ``fetch_issues`` 逻辑。"""

from typing import Any, Dict, List

from ..adapters import AdapterError, load_legacy
from .gh import gh_error, label_names


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
            raise gh_error(exc) from exc

    def list_issues(self, repo: str, labels=None, since=None,
                    state: str = "closed") -> List[Dict[str, Any]]:
        repo = repo or self.repo
        url = f"repos/{repo}/issues?state={state}&per_page=100"
        wanted = label_names(labels)
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
