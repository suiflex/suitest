"""Inbound webhook payload models (M1d-17 GitLab; M1d-16 GitHub to follow).

These are intentionally **permissive**: external systems shape their payloads
freely and we only care about the discriminator fields needed to (a) trigger a
gating run, and (b) attribute the run back to a commit / branch / MR.

GitLab payload shapes follow the public webhook docs at
https://docs.gitlab.com/ee/user/project/integrations/webhook_events.html —
fields we don't read are accepted via ``model_config["extra"] = "allow"`` so
new GitLab fields land silently rather than 422-ing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Push Hook
# ---------------------------------------------------------------------------


class GitlabCommit(BaseModel):
    """One entry in a Push Hook's ``commits`` array.

    ``id`` is the full SHA. The other fields are accepted but not consumed by
    the receiver — they're listed here as a hint for downstream consumers
    (defect filer, autopilot) that may rehydrate the payload from the audit log.
    """

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
    """``Push Hook`` body.

    GitLab sends ``object_kind="push"`` for branch updates and
    ``object_kind="tag_push"`` for tags. The tag variant is forwarded through
    the same handler — gating runs against tag pushes are a deliberate v1
    feature.
    """

    model_config = ConfigDict(extra="allow")

    object_kind: str
    ref: str | None = None
    before: str | None = None
    after: str | None = None
    project_id: int | None = None
    project: GitlabProjectRef | None = None
    commits: list[GitlabCommit] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Merge Request Hook
# ---------------------------------------------------------------------------


class GitlabMergeRequestAttributes(BaseModel):
    """The ``object_attributes`` block of a ``Merge Request Hook`` payload.

    ``action`` drives the gating decision: ``open`` / ``reopen`` / ``update``
    enqueue a run, everything else returns 200 ignored.
    """

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
# Receiver response shapes
# ---------------------------------------------------------------------------


class WebhookEnqueuedResponse(BaseModel):
    """202 response when the webhook successfully enqueues a gating run."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    public_id: str = Field(serialization_alias="publicId")
    status_url: str = Field(serialization_alias="statusUrl")


class WebhookIgnoredResponse(BaseModel):
    """200 response when the receiver intentionally drops the event.

    ``reason`` is a stable machine-readable string so dashboards and CI plugins
    can branch on it without parsing free-form messages. Known reasons:

    * ``duplicate`` — Redis SETNX dedup hit within the TTL window.
    * ``no_gating_suite`` — neither ``gating_suite_id`` nor any ``smoke``-tagged
      cases are configured for the project (Q4 default).
    * ``unsupported_event`` — webhook event kind isn't one the receiver acts on.
    * ``unsupported_action`` — Merge Request action that does not enqueue a run.
    """

    ignored: bool = True
    reason: str
