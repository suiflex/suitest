import os
from unittest import mock

from suitest_lifecycle.publishers import GitHubPublisher, detect_forge


def test_detects_github() -> None:
    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
        assert detect_forge() == "github"


def test_detects_gitlab() -> None:
    with mock.patch.dict(os.environ, {"GITLAB_CI": "true"}, clear=True):
        assert detect_forge() == "gitlab"


def test_detects_bitbucket_and_gitea() -> None:
    with mock.patch.dict(os.environ, {"BITBUCKET_BUILD_NUMBER": "7"}, clear=True):
        assert detect_forge() == "bitbucket"
    with mock.patch.dict(os.environ, {"GITEA_ACTIONS": "true"}, clear=True):
        assert detect_forge() == "gitea"


def test_no_ci_returns_none() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        assert detect_forge() is None


# --------------------------------------------------------------------------- #
# GitHubPublisher — HTTP mocked, no network
# --------------------------------------------------------------------------- #


class _FakeHttp:
    """Rekam request; balas sesuai skenario."""

    def __init__(self, existing_comments: list[dict]) -> None:
        self.existing = existing_comments
        self.requests: list[tuple[str, str, dict | None]] = []  # (method, url, body)

    def __call__(self, method: str, url: str, body: dict | None = None) -> object:
        self.requests.append((method, url, body))
        if method == "GET":
            return self.existing
        return {"id": 999}


def _publisher(http) -> GitHubPublisher:
    return GitHubPublisher(
        token="ghs_x", repo="acme/shop", pr_number=42,
        api_base="https://api.github.com", http=http,
    )


def test_creates_new_comment_when_no_marker_found() -> None:
    http = _FakeHttp(existing_comments=[{"id": 1, "body": "unrelated"}])
    _publisher(http).publish("<!-- suitest-report -->\nhasil")
    methods_urls = [(m, u) for m, u, _ in http.requests]
    assert ("GET", "https://api.github.com/repos/acme/shop/issues/42/comments") in methods_urls
    assert ("POST", "https://api.github.com/repos/acme/shop/issues/42/comments") in methods_urls


def test_updates_existing_marker_comment() -> None:
    http = _FakeHttp(existing_comments=[
        {"id": 7, "body": "<!-- suitest-report -->\nlama"},
    ])
    _publisher(http).publish("<!-- suitest-report -->\nbaru")
    assert ("PATCH", "https://api.github.com/repos/acme/shop/issues/comments/7",
            {"body": "<!-- suitest-report -->\nbaru"}) in http.requests
    # TIDAK membuat comment baru (anti-spam)
    assert not any(m == "POST" for m, _, _ in http.requests)


def test_pr_number_from_ref() -> None:
    from suitest_lifecycle.publishers import _pr_number_from_env

    with mock.patch.dict(os.environ, {"GITHUB_REF": "refs/pull/42/merge"}, clear=True):
        assert _pr_number_from_env() == 42
    with mock.patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main"}, clear=True):
        assert _pr_number_from_env() is None
