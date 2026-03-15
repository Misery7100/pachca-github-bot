"""Structured message models for composing rich Pachca messages.

Pachca messages support markdown formatting. These models provide a
composable, parametrized way to build readable messages from typed blocks.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

GITHUB_BASE = "https://github.com"

_PR_HEADER_RE = re.compile(r"^(## .+ PR \[#\d+\]\([^)]+\)) .+$", re.MULTILINE)
_PR_STATUS_FIELD_RE = re.compile(r"^\*\*Status:\*\* .+$", re.MULTILINE)


def _gh_user_link(login: str) -> str:
    return f"[{login}]({GITHUB_BASE}/{login})"


def _gh_repo_link(full_name: str) -> str:
    return f"[{full_name}]({GITHUB_BASE}/{full_name})"


def _gh_branch_link(repo: str, branch: str) -> str:
    return f"[{branch}]({GITHUB_BASE}/{repo}/tree/{branch})"


def _gh_commit_link(repo: str, sha: str) -> str:
    return f"[{sha[:8]}]({GITHUB_BASE}/{repo}/commit/{sha})"


def _gh_release_link(url: str, label: str) -> str:
    return f"[{label}]({url})"


def _gh_pr_link(repo: str, number: int) -> str:
    return f"[#{number}]({GITHUB_BASE}/{repo}/pull/{number})"


class Severity(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def emoji(self) -> str:
        return {
            Severity.INFO: "ℹ️",
            Severity.SUCCESS: "✅",
            Severity.WARNING: "⚠️",
            Severity.ERROR: "❌",
            Severity.CRITICAL: "🔥",
        }[self]


class PRStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    READY_FOR_REVIEW = "ready_for_review"
    CHECKS_PASSED = "checks_passed"
    MERGED = "merged"
    CLOSED = "closed"

    @property
    def emoji(self) -> str:
        return {
            PRStatus.DRAFT: "📝",
            PRStatus.OPEN: "🆕",
            PRStatus.READY_FOR_REVIEW: "👀",
            PRStatus.CHECKS_PASSED: "✅",
            PRStatus.MERGED: "🟣",
            PRStatus.CLOSED: "🚫",
        }[self]

    @property
    def label(self) -> str:
        return {
            PRStatus.DRAFT: "Draft",
            PRStatus.OPEN: "Open",
            PRStatus.READY_FOR_REVIEW: "Ready for review",
            PRStatus.CHECKS_PASSED: "Ready to merge",
            PRStatus.MERGED: "Merged",
            PRStatus.CLOSED: "Closed",
        }[self]


class DeployStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"

    @property
    def emoji(self) -> str:
        return {
            DeployStatus.STARTED: "🚀",
            DeployStatus.SUCCEEDED: "✅",
            DeployStatus.FAILED: "❌",
            DeployStatus.ROLLED_BACK: "⏪",
        }[self]

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


_DEPLOY_STATUS_FIELD_RE = re.compile(r"^\*\*Status:\*\* .+$", re.MULTILINE)
_DEPLOY_HEADER_RE = re.compile(r"^(## [^ ]+ Deploy) .+$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Block primitives
# ---------------------------------------------------------------------------


class MessageBlock(BaseModel):
    """Base block — every block can render itself to markdown."""

    def render(self) -> str:
        raise NotImplementedError


class HeaderBlock(MessageBlock):
    text: str
    level: Literal[1, 2, 3] = 1

    def render(self) -> str:
        prefix = "#" * self.level
        return f"{prefix} {self.text}"


class TextBlock(MessageBlock):
    text: str
    bold: bool = False
    italic: bool = False

    def render(self) -> str:
        t = self.text
        if self.bold:
            t = f"**{t}**"
        if self.italic:
            t = f"*{t}*"
        return t


class LinkBlock(MessageBlock):
    text: str
    url: str

    def render(self) -> str:
        return f"[{self.text}]({self.url})"


class FieldsBlock(MessageBlock):
    fields: dict[str, str]

    def render(self) -> str:
        lines = [f"**{k}:** {v}" for k, v in self.fields.items()]
        return "\n".join(lines)


class CodeBlock(MessageBlock):
    code: str
    language: str = ""

    def render(self) -> str:
        return f"```{self.language}\n{self.code}\n```"


class QuoteBlock(MessageBlock):
    text: str

    def render(self) -> str:
        lines = self.text.split("\n")
        return "\n".join(f"> {line}" for line in lines)


class ListBlock(MessageBlock):
    items: list[str]
    ordered: bool = False

    def render(self) -> str:
        result: list[str] = []
        for i, item in enumerate(self.items, 1):
            prefix = f"{i}." if self.ordered else "•"
            result.append(f"{prefix} {item}")
        return "\n".join(result)


class DividerBlock(MessageBlock):
    def render(self) -> str:
        return "---"


class StructuredMessage(BaseModel):
    blocks: list[MessageBlock] = Field(default_factory=list)

    def render(self) -> str:
        return "\n\n".join(block.render() for block in self.blocks)

    def add(self, block: MessageBlock) -> StructuredMessage:
        self.blocks.append(block)
        return self


# ---------------------------------------------------------------------------
# Status update thread format (shared by PR and deploy trackers)
# ---------------------------------------------------------------------------


def render_status_update(
    before_emoji: str,
    before_label: str,
    after_emoji: str,
    after_label: str,
) -> str:
    return (
        f"**Status updated:**\n"
        f"Before: {before_emoji} {before_label}\n"
        f"After: {after_emoji} {after_label}"
    )


# ---------------------------------------------------------------------------
# GitHub message templates
# ---------------------------------------------------------------------------


class GitHubReleaseMessage(BaseModel):
    repo: str
    tag: str
    release_name: str
    author: str
    url: str
    body: str = ""
    prerelease: bool = False

    def to_structured(self) -> StructuredMessage:
        pre = "(pre-release) " if self.prerelease else ""
        release_link = _gh_release_link(self.url, self.tag)
        header = f"🔖 Release: {pre}{release_link}"

        msg = StructuredMessage()
        msg.add(HeaderBlock(text=header, level=2))
        msg.add(
            FieldsBlock(
                fields={
                    "Repository": _gh_repo_link(self.repo),
                    "Author": _gh_user_link(self.author),
                }
            )
        )
        if self.body:
            msg.add(QuoteBlock(text=self.body[:1000]))
        msg.add(LinkBlock(text="View release", url=self.url))
        return msg


class GitHubCIMessage(BaseModel):
    """CI check/workflow result — can be posted to channel or PR thread."""

    workflow_name: str
    commit_sha: str
    repo: str
    conclusion: str
    url: str
    for_pr_thread: bool = False

    def to_structured(self) -> StructuredMessage:
        severity = Severity.ERROR if self.conclusion == "failure" else Severity.WARNING
        header = f"{severity.emoji} CI: {self.workflow_name} — {self.conclusion}"

        msg = StructuredMessage()
        msg.add(HeaderBlock(text=header, level=2))
        fields: dict[str, str] = {}
        if not self.for_pr_thread:
            fields["Repository"] = _gh_repo_link(self.repo)
        fields["Commit"] = _gh_commit_link(self.repo, self.commit_sha)
        fields["Result"] = self.conclusion
        msg.add(FieldsBlock(fields=fields))
        msg.add(LinkBlock(text="View run", url=self.url))
        return msg


class GitHubPRMessage(BaseModel):
    repo: str
    number: int
    title: str
    author: str
    url: str
    base_branch: str
    head_branch: str
    status: PRStatus
    body: str = ""

    def to_parent(self) -> str:
        pr_link = _gh_pr_link(self.repo, self.number)
        header = f"{self.status.emoji} PR {pr_link} {self.status.label}: {self.title}"

        msg = StructuredMessage()
        msg.add(HeaderBlock(text=header, level=2))
        head_link = _gh_branch_link(self.repo, self.head_branch)
        base_link = _gh_branch_link(self.repo, self.base_branch)
        msg.add(
            FieldsBlock(
                fields={
                    "Repository": _gh_repo_link(self.repo),
                    "Author": _gh_user_link(self.author),
                    "Branch": f"{head_link} → {base_link}",
                }
            )
        )
        if self.body:
            msg.add(QuoteBlock(text=self.body[:500]))
        msg.add(LinkBlock(text="View pull request", url=self.url))
        return msg.render()

    def to_thread_update(self, old_status: PRStatus | None = None) -> str:
        if old_status:
            return render_status_update(
                old_status.emoji,
                old_status.label,
                self.status.emoji,
                self.status.label,
            )
        return f"{self.status.emoji} {self.status.label}"

    @staticmethod
    def patch_parent_status(content: str, new_status: PRStatus) -> str:
        """Update only the status-related parts of an existing parent message."""
        new_status_text = f"{new_status.emoji} {new_status.label}"

        result = _PR_HEADER_RE.sub(
            lambda m: f"{m.group(1)} {new_status_text}: ",
            content,
        )
        result = _PR_STATUS_FIELD_RE.sub(
            f"**Status:** {new_status_text}",
            result,
        )
        for old in PRStatus:
            if old == new_status:
                continue
            old_prefix = f"## {old.emoji} PR"
            new_prefix = f"## {new_status.emoji} PR"
            result = result.replace(old_prefix, new_prefix, 1)

        return result


class GitHubDeploymentMessage(BaseModel):
    repo: str
    environment: str
    description: str = ""
    state: str = ""
    creator: str = ""
    sha: str = ""
    ref: str = ""
    url: str = ""

    def to_structured(self) -> StructuredMessage:
        state_emoji = {
            "success": "✅",
            "failure": "❌",
            "error": "❌",
            "pending": "⏳",
            "in_progress": "🔄",
            "queued": "📋",
            "inactive": "💤",
        }
        emoji = state_emoji.get(self.state, "🚀")
        state_label = self.state or "created"
        header = f"{emoji} Deployment {state_label}: {self.environment}"

        msg = StructuredMessage()
        msg.add(HeaderBlock(text=header, level=2))
        fields: dict[str, str] = {
            "Repository": _gh_repo_link(self.repo),
            "Environment": self.environment,
        }
        if self.ref:
            fields["Ref"] = _gh_branch_link(self.repo, self.ref)
        if self.sha:
            fields["Commit"] = _gh_commit_link(self.repo, self.sha)
        if self.creator:
            fields["Deployed by"] = _gh_user_link(self.creator)
        if self.state:
            fields["Status"] = state_label
        msg.add(FieldsBlock(fields=fields))
        if self.description:
            msg.add(TextBlock(text=self.description))
        if self.url:
            msg.add(LinkBlock(text="View deployment", url=self.url))
        return msg


# ---------------------------------------------------------------------------
# Generic message templates
# ---------------------------------------------------------------------------


class GenericAlertMessage(BaseModel):
    source: str
    title: str
    severity: Severity = Severity.INFO
    details: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    url: str = ""

    def to_structured(self) -> StructuredMessage:
        header = f"{self.severity.emoji} {self.title}"
        msg = StructuredMessage()
        msg.add(HeaderBlock(text=header, level=2))
        combined: dict[str, str] = {"Source": self.source}
        combined.update(self.fields)
        msg.add(FieldsBlock(fields=combined))
        if self.details:
            msg.add(TextBlock(text=self.details))
        if self.url:
            msg.add(LinkBlock(text="Details", url=self.url))
        return msg


class GenericDeployMessage(BaseModel):
    source: str
    environment: str
    version: str
    status: DeployStatus
    deploy_id: str = ""
    actor: str = ""
    url: str = ""
    changelog: list[str] = Field(default_factory=list)

    def to_parent(self) -> str:
        header = f"{self.status.emoji} Deploy {self.status.label}: {self.source}"
        msg = StructuredMessage()
        msg.add(HeaderBlock(text=header, level=2))
        fields: dict[str, str] = {}
        if self.deploy_id:
            fields["ID"] = self.deploy_id
        fields["Environment"] = self.environment
        fields["Version"] = self.version
        msg.add(FieldsBlock(fields=fields))
        if self.actor:
            msg.add(FieldsBlock(fields={"Deployed by": self.actor}))
        if self.changelog:
            msg.add(ListBlock(items=self.changelog))
        if self.url:
            msg.add(LinkBlock(text="View deployment", url=self.url))
        return msg.render()

    def to_thread_update(self, old_status: DeployStatus) -> str:
        return render_status_update(
            old_status.emoji,
            old_status.label,
            self.status.emoji,
            self.status.label,
        )

    @staticmethod
    def patch_parent_status(content: str, new_status: DeployStatus) -> str:
        new_label = f"{new_status.emoji} Deploy {new_status.label}:"
        result = _DEPLOY_HEADER_RE.sub(
            lambda m: new_label,
            content,
        )
        return result
