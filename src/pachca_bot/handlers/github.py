"""GitHub webhook event handler.

Translates GitHub webhook payloads into structured Pachca messages.
Supports: releases, check_run / workflow_run failures, pull_request events.
"""

from __future__ import annotations

import logging

from pachca_bot.models.messages import (
    FieldsBlock,
    GitHubCheckFailureMessage,
    GitHubPullRequestMessage,
    GitHubReleaseMessage,
    HeaderBlock,
    Severity,
    StructuredMessage,
    TextBlock,
)
from pachca_bot.models.webhooks import GitHubWebhookPayload

logger = logging.getLogger(__name__)

SUPPORTED_EVENTS = {"release", "check_run", "workflow_run", "pull_request"}

_INTERESTING_PR_ACTIONS = {
    "opened",
    "closed",
    "reopened",
    "ready_for_review",
    "review_requested",
}


def handle_github_event(
    event_type: str,
    payload: GitHubWebhookPayload,
) -> StructuredMessage | None:
    """Route a GitHub event to the appropriate message builder.

    Returns ``None`` when the event should be silently ignored
    (e.g. a successful check run, or an unsupported event type).
    """
    repo = payload.repository.full_name

    if event_type == "release" and payload.release is not None:
        rel = payload.release
        return GitHubReleaseMessage(
            repo=repo,
            tag=rel.tag_name,
            release_name=rel.name or rel.tag_name,
            author=rel.author.login or payload.sender.login,
            url=rel.html_url,
            body=rel.body or "",
            prerelease=rel.prerelease,
        ).to_structured()

    if event_type == "workflow_run" and payload.workflow_run is not None:
        wr = payload.workflow_run
        if payload.action != "completed":
            return None
        if wr.conclusion in (None, "success", "neutral", "skipped"):
            return None
        return GitHubCheckFailureMessage(
            repo=repo,
            workflow_name=wr.name,
            branch=wr.head_branch,
            commit_sha=wr.head_sha,
            conclusion=wr.conclusion or "unknown",
            url=wr.html_url,
            actor=wr.actor.login,
        ).to_structured()

    if event_type == "check_run" and payload.check_run is not None:
        cr = payload.check_run
        if payload.action != "completed":
            return None
        if cr.conclusion in (None, "success", "neutral", "skipped"):
            return None
        return GitHubCheckFailureMessage(
            repo=repo,
            workflow_name=cr.name,
            branch=cr.check_suite.head_branch,
            commit_sha=cr.check_suite.head_sha,
            conclusion=cr.conclusion or "unknown",
            url=cr.html_url,
        ).to_structured()

    if event_type == "pull_request" and payload.pull_request is not None:
        pr = payload.pull_request
        if payload.action not in _INTERESTING_PR_ACTIONS:
            return None
        return GitHubPullRequestMessage(
            repo=repo,
            action=payload.action,
            number=pr.number,
            title=pr.title,
            author=pr.user.login or payload.sender.login,
            url=pr.html_url,
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            body=pr.body or "",
            merged=pr.merged,
            draft=pr.draft,
        ).to_structured()

    if event_type == "ping":
        msg = StructuredMessage()
        msg.add(HeaderBlock(text=f"{Severity.INFO.emoji} GitHub webhook connected", level=2))
        msg.add(FieldsBlock(fields={"Repository": repo}))
        msg.add(TextBlock(text="Webhook ping received successfully."))
        return msg

    logger.debug("Ignoring unsupported GitHub event: %s", event_type)
    return None
