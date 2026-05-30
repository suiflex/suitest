"""Inbound webhook payload models.

M1d-18 ships the Jira ``issue_updated`` shape; M1d-16 (GitHub) and M1d-17
(GitLab) will extend this module with their own payload shapes when those PRs
land on this branch line.

Payloads are intentionally **permissive**: external systems shape their wire
freely and we only care about the discriminator fields needed to (a) decide
whether to act, and (b) link the event back to a local row. Fields we don't
read are accepted via ``model_config["extra"] = "allow"`` so new Jira fields
land silently rather than 422-ing.

Jira ``issue_updated`` payload shape per
https://developer.atlassian.com/cloud/jira/platform/webhooks/.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Jira issue_updated
# ---------------------------------------------------------------------------


class JiraStatusBlock(BaseModel):
    """The ``fields.status`` sub-object on a Jira issue.

    We only need ``name`` — Jira's status object also carries ``id``,
    ``description``, ``iconUrl``, ``statusCategory`` … none of which the
    receiver acts on.
    """

    model_config = ConfigDict(extra="allow")

    name: str | None = None


class JiraIssueFields(BaseModel):
    """The ``fields`` block of a Jira issue.

    Only the ``status`` block is required by the receiver; the rest of the
    Jira field universe (summary, description, priority, assignee, …) flows
    through as ``extra="allow"`` so a future receiver that wants to sync more
    can read them off the parsed model without a schema migration.
    """

    model_config = ConfigDict(extra="allow")

    status: JiraStatusBlock | None = None


class JiraIssue(BaseModel):
    """The ``issue`` block of a Jira webhook payload."""

    model_config = ConfigDict(extra="allow")

    # Jira's stable human-readable issue key (e.g. "PROJ-123"). Used to look
    # up the local ExternalIssue row.
    key: str
    # Numeric internal id — not used for lookup but kept around for audit.
    id: str | None = None
    fields: JiraIssueFields | None = None


class JiraChangelogItem(BaseModel):
    """One entry in the ``changelog.items`` array.

    Jira emits one item per field that changed in the triggering update; the
    receiver only looks at items where ``field == "status"`` to confirm the
    event actually concerns a status transition (vs. a summary edit, a label
    change, etc).
    """

    model_config = ConfigDict(extra="allow")

    field: str | None = None
    fromString: str | None = None
    toString: str | None = None


class JiraChangelog(BaseModel):
    """The ``changelog`` block of a Jira webhook payload.

    ``id`` is the per-change identifier Jira uses for at-least-once
    deduplication on its end — we key our Redis SETNX off it so a replay
    within the 60 s TTL window is a no-op.
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    items: list[JiraChangelogItem] = Field(default_factory=list)


class JiraIssueUpdatedPayload(BaseModel):
    """Top-level ``jira:issue_updated`` body.

    Any other ``webhookEvent`` value is accepted (``extra="allow"``) but the
    receiver short-circuits to a 200 ``ignored`` reply before model-level
    parsing — we never invoke the model when the discriminator doesn't match.
    """

    model_config = ConfigDict(extra="allow")

    webhookEvent: str
    issue: JiraIssue
    changelog: JiraChangelog | None = None


# ---------------------------------------------------------------------------
# Receiver response shapes
# ---------------------------------------------------------------------------


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
    * ``unsupported_event`` — webhook event kind isn't one the receiver acts on.
    * ``unknown_issue`` — no local defect carries the inbound issue key.
    * ``unmappable_status`` — adapter's status map returned ``None`` for the
      external status name.
    * ``no_status_change`` — mapped status already matches the local defect's
      status (idempotent replay).
    """

    ignored: bool = True
    reason: str
