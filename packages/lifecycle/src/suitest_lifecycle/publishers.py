"""Comment publisher per forge. Nambah forge = satu entry _FORGES + satu class."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol

from suitest_lifecycle.ci_report import COMMENT_MARKER

# urutan penting: Gitea Actions juga men-set GITHUB_ACTIONS utk kompatibilitas,
# jadi cek marker gitea DULU.
_FORGES = [
    ("gitea", "GITEA_ACTIONS"),
    ("github", "GITHUB_ACTIONS"),
    ("gitlab", "GITLAB_CI"),
    ("bitbucket", "BITBUCKET_BUILD_NUMBER"),
]


def detect_forge() -> str | None:
    for forge, marker in _FORGES:
        if os.environ.get(marker):
            return forge
    return None


class CommentPublisher(Protocol):
    def publish(self, markdown: str) -> None:
        """Upsert comment ber-marker di PR/MR aktif."""
        ...


def _default_http(token: str):
    def _request(method: str, url: str, body: dict | None = None) -> object:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "null")

    return _request


class GitHubPublisher:
    """Upsert PR comment. GitLab/Bitbucket/Gitea: class serupa, endpoint beda."""

    def __init__(self, *, token: str, repo: str, pr_number: int,
                 api_base: str = "https://api.github.com", http=None) -> None:
        self._base = f"{api_base}/repos/{repo}/issues/{pr_number}/comments"
        self._http = http or _default_http(token)
        self._api_base = api_base
        self._repo = repo

    def publish(self, markdown: str) -> None:
        existing = self._http("GET", self._base) or []
        for comment in existing:
            if COMMENT_MARKER in str(comment.get("body", "")):
                url = f"{self._api_base}/repos/{self._repo}/issues/comments/{comment['id']}"
                self._http("PATCH", url, {"body": markdown})
                return
        self._http("POST", self._base, {"body": markdown})

    @classmethod
    def from_env(cls) -> GitHubPublisher | None:
        token = os.environ.get("GITHUB_TOKEN", "")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        pr = _pr_number_from_env()
        if not (token and repo and pr):
            return None
        return cls(token=token, repo=repo, pr_number=pr)


def _pr_number_from_env() -> int | None:
    # refs/pull/42/merge -> 42 ; fallback: event payload
    ref = os.environ.get("GITHUB_REF", "")
    parts = ref.split("/")
    if len(parts) >= 3 and parts[1] == "pull" and parts[2].isdigit():
        return int(parts[2])
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_path and os.path.isfile(event_path):
        with open(event_path, encoding="utf-8") as f:
            payload = json.load(f)
        number = (payload.get("pull_request") or {}).get("number")
        if isinstance(number, int):
            return number
    return None


def make_publisher() -> CommentPublisher | None:
    """Factory: forge terdeteksi -> publisher-nya. Forge baru: tambah case di sini."""
    forge = detect_forge()
    if forge == "github":
        return GitHubPublisher.from_env()
    return None  # gitlab/bitbucket/gitea: follow-up, satu class per forge
