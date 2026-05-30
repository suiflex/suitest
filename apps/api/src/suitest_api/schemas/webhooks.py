"""Inbound webhook payload models (M1d-16 GitHub + M1d-17 GitLab + M1d-18 Jira).

These are intentionally **permissive**: external systems shape their payloads
freely and we only care about the discriminator fields needed to (a) trigger a
gating run, and (b) attribute the run / sync back to a commit / branch / MR /
PR / Jira issue. Fields we don't read are accepted via
``model_config["extra"] = "allow"`` so new provider fields land silently
rather than 422-ing.

GitLab payload shapes follow the public webhook docs at
https://docs.gitlab.com/ee/user/project/integrations/webhook_events.html.
GitHub payload shapes follow https://docs.github.com/en/webhooks.
Jira ``issue_updated`` payload shape per
https://developer.atlassian.com/cloud/jira/platform/webhooks/.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# GitLab — Push Hook
# ---------------------------------------------------------------------------


class GitlabCommit(BaseModel):
    """One entry in a Push Hook's ``commits`` array."""

    model_config = ConfigDict(extra="allow")

    id: str
    message: str | None = None
    timestamp: str | None = None
    url: str | None = None


class GitlabProjectRef(BaseModel):
    """The ``project`` sub-object embedded in every GitLab webhook payload."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int
    path_with_namespace: str | None = Field(default=None, alias="path_with_namespace")
    web_url: str | None = Field(default=None, alias="web_url")


class GitlabPushPayload(BaseModel):
    """``Push Hook`` body."""

    model_config = ConfigDict(extra="allow")

    object_kind: str
    ref: str | None = None
    before: str | None = None
    after: str | None = None
    project_id: int | None = None
    project: GitlabProjectRef | None = None
    commits: list[GitlabCommit] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# GitLab — Merge Request Hook
# ---------------------------------------------------------------------------


class GitlabMergeRequestAttributes(BaseModel):
    """The ``object_attributes`` block of a ``Merge Request Hook`` payload."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    iid: int | None = None
    action: str | None = None
    source_branch: str | None = Field(default=None, alias="source_branch")
    target_branch: str | None = Field(default=None, alias="target_branch")
    last_commit: dict[str, object] | None = Field(default=None, alias="last_commit")


class GitlabMergeRequestPayload(BaseModel):
    """``Merge Request Hook`` body."""

    model_config = ConfigDict(extra="allow")

    object_kind: str
    project: GitlabProjectRef | None = None
    object_attributes: GitlabMergeRequestAttributes


# ---------------------------------------------------------------------------
# GitHub — Push event
# ---------------------------------------------------------------------------


class GithubRepositoryRef(BaseModel):
    """The ``repository`` block embedded in every GitHub webhook payload."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int | None = None
    full_name: str | None = Field(default=None, alias="full_name")
    name: str | None = None


class GithubPushPayload(BaseModel):
    """GitHub ``push`` event body."""

    model_config = ConfigDict(extra="allow")

    ref: str | None = None
    before: str | None = None
    after: str | None = None
    deleted: bool | None = None
    repository: GithubRepositoryRef | None = None


# ---------------------------------------------------------------------------
# GitHub — Pull Request event
# ---------------------------------------------------------------------------


class GithubPullRequestHead(BaseModel):
    """The ``pull_request.head`` block (source side of the PR)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    sha: str | None = None
    ref: str | None = None


class GithubPullRequest(BaseModel):
    """The ``pull_request`` block — only the fields the receiver consumes."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    number: int | None = None
    head: GithubPullRequestHead | None = None


class GithubPullRequestPayload(BaseModel):
    """GitHub ``pull_request`` event body."""

    model_config = ConfigDict(extra="allow")

    action: str | None = None
    number: int | None = None
    pull_request: GithubPullRequest | None = None
    repository: GithubRepositoryRef | None = None


# ---------------------------------------------------------------------------
# Jira — issue_updated
# ---------------------------------------------------------------------------


class JiraStatusBlock(BaseModel):
    """The ``fields.status`` sub-object on a Jira issue."""

    model_config = ConfigDict(extra="allow")

    name: str | None = None


class JiraIssueFields(BaseModel):
    """The ``fields`` block of a Jira issue."""

    model_config = ConfigDict(extra="allow")

    status: JiraStatusBlock | None = None


class JiraIssue(BaseModel):
    """The ``issue`` block of a Jira webhook payload."""

    model_config = ConfigDict(extra="allow")

    key: str
    id: str | None = None
    fields: JiraIssueFields | None = None


class JiraChangelogItem(BaseModel):
    """One entry in the ``changelog.items`` array."""

    model_config = ConfigDict(extra="allow")

    field: str | None = None
    fromString: str | None = None
    toString: str | None = None


class JiraChangelog(BaseModel):
    """The ``changelog`` block of a Jira webhook payload."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    items: list[JiraChangelogItem] = Field(default_factory=list)


class JiraIssueUpdatedPayload(BaseModel):
    """Top-level ``jira:issue_updated`` body."""

    model_config = ConfigDict(extra="allow")

    webhookEvent: str
    issue: JiraIssue
    changelog: JiraChangelog | None = None


# ---------------------------------------------------------------------------
# Receiver response shapes
# ---------------------------------------------------------------------------


class WebhookEnqueuedResponse(BaseModel):
    """202 response when the webhook successfully enqueues a gating run."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    public_id: str = Field(serialization_alias="publicId")
    status_url: str = Field(serialization_alias="statusUrl")


class WebhookPingResponse(BaseModel):
    """200 response to a GitHub ``ping`` event."""

    pong: bool = True


class JiraSyncedResponse(BaseModel):
    """202 response when the Jira webhook successfully syncs a defect status."""

    model_config = ConfigDict(populate_by_name=True)

    defect_id: str = Field(serialization_alias="defectId")
    from_status: str = Field(serialization_alias="fromStatus")
    to_status: str = Field(serialization_alias="toStatus")


class WebhookIgnoredResponse(BaseModel):
    """200 response when the receiver intentionally drops the event.

    ``reason`` is a stable machine-readable string so dashboards and CI plugins
    can branch on it without parsing free-form messages. Known reasons:

    * ``duplicate`` — Redis SETNX dedup hit within the TTL window.
    * ``no_gating_suite`` — no gating selection for the project.
    * ``unsupported_event`` — webhook event kind isn't one the receiver acts on.
    * ``unsupported_action`` — Merge Request / PR action that does not enqueue a run.
    * ``branch_deleted`` — GitHub push with ``deleted=true``.
    * ``unknown_issue`` — Jira inbound issue key has no local defect link.
    * ``unmappable_status`` — Jira adapter status map returned ``None``.
    * ``no_status_change`` — Jira mapped status equals current defect status.
    """

    ignored: bool = True
    reason: str
