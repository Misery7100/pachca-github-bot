"""Thread-based PR tracking.

Maintains an in-memory mapping of (repo, pr_number) → pachca_message_id.
On each PR status change the tracker:
  1. Finds the existing parent message (in-memory or by scanning chat)
  2. Creates/gets the thread and posts a status-change reply
  3. Patches the parent message header/status (preserving body when open)
  4. If no parent message exists, creates a new one
  5. REOPENED always creates a new parent message; further updates go to that message
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pachca_bot.core.client import PachcaClient
from pachca_bot.core.config import IntegrationConfig
from pachca_bot.integrations.github.models import (
    GitHubCheckSuitePassedMessage,
    GitHubPRMessage,
    PRStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class _PREntry:
    message_id: int
    status: PRStatus
    content: str = ""
    checks_passed: bool = False
    has_approval: bool = False


class PRTracker:
    """In-memory PR → Pachca message tracker with chat-search fallback."""

    def __init__(self, client: PachcaClient, integration: IntegrationConfig) -> None:
        self._client = client
        self._integration = integration
        self._store: dict[tuple[str, int], _PREntry] = {}

    def _make_key(self, repo: str, number: int) -> tuple[str, int]:
        return (repo, number)

    def _search_chat_for_pr(
        self, repo: str, number: int, max_messages: int | None = None
    ) -> _PREntry | None:
        try:
            messages = self._client.get_messages(
                self._integration.chat_id,
                max_messages=max_messages,
            )
        except Exception:
            logger.warning("Failed to fetch chat messages for PR lookup", exc_info=True)
            return None

        target = f"PR [#{number}](https://github.com/{repo}/pull/{number})"
        for msg in messages:
            content = msg.get("content", "")
            if target in content:
                status = self._infer_status_from_content(content) or PRStatus.OPEN
                return _PREntry(
                    message_id=msg.get("id", 0),
                    status=status,
                    content=content,
                )
        return None

    def _ensure_entry_content(self, entry: _PREntry) -> bool:
        """Fetch message content when empty. Returns True if content is now available."""
        if entry.content:
            return True
        msg = self._client.get_message(entry.message_id)
        if msg:
            content = msg.get("content", "")
            if content:
                entry.content = content
                return True
        return False

    @staticmethod
    def _infer_status_from_content(content: str) -> PRStatus | None:
        for status in PRStatus:
            if f"**Status:** {status.label}" in content:
                return status
        return None

    def get_thread_id_for_pr(self, repo: str, number: int) -> int | None:
        key = self._make_key(repo, number)
        entry = self._store.get(key)
        if entry is None:
            found = self._search_chat_for_pr(repo, number)
            if found is not None:
                entry = found
                self._store[key] = entry
        if entry is None:
            return None
        try:
            thread = self._client.create_thread(entry.message_id)
            return thread.get("id")
        except Exception:
            return None

    def handle_check_suite_pass(
        self, repo: str, number: int, commit_sha: str, checks_url: str = ""
    ) -> dict | None:
        """Post 'All checks passed' to thread, set checks_passed.
        Promote to Ready to merge only if has_approval."""
        key = self._make_key(repo, number)
        entry = self._store.get(key)
        if entry is None:
            found = self._search_chat_for_pr(repo, number)
            if found is not None:
                entry = found
                self._store[key] = entry
        if entry is None:
            return None
        entry.checks_passed = True
        check_msg = GitHubCheckSuitePassedMessage(
            repo=repo, commit_sha=commit_sha, url=checks_url
        )
        try:
            thread = self._client.create_thread(entry.message_id)
            thread_id = thread.get("id")
            if thread_id:
                self._client.post_to_thread(
                    thread_id,
                    check_msg.to_thread_content(),
                    display_name=self._integration.display_name,
                    display_avatar_url=self._integration.display_avatar_url,
                )
        except Exception:
            logger.warning(
                "Failed to post check suite pass to PR #%s thread", number, exc_info=True
            )
        if entry.has_approval and entry.status != PRStatus.CHECKS_PASSED:
            try:
                if not entry.content and not self._ensure_entry_content(entry):
                    refound = self._search_chat_for_pr(repo, number)
                    if refound and refound.content:
                        entry.content = refound.content
                if entry.content:
                    new_content = GitHubPRMessage.patch_parent_status(
                        entry.content, PRStatus.CHECKS_PASSED
                    )
                    self._client.update_message(entry.message_id, new_content)
                    entry.status = PRStatus.CHECKS_PASSED
                    entry.content = new_content
            except Exception:
                logger.warning(
                    "Failed to promote PR #%s to Ready to merge after check pass",
                    number,
                    exc_info=True,
                )
        return {"id": entry.message_id}

    def record_review_state(self, repo: str, number: int, state: str) -> bool:
        """Update has_approval from review state.
        Promote to Ready to merge if approved and checks_passed.
        state: approved, changes_requested, commented, or empty (dismissed).
        Returns True if promoted."""
        if state == "approved":
            return self.record_approval_and_maybe_promote(repo, number)
        if state in ("changes_requested", ""):
            self._clear_approval(repo, number)
        return False

    def _clear_approval(self, repo: str, number: int) -> None:
        key = self._make_key(repo, number)
        entry = self._store.get(key)
        if entry is None:
            found = self._search_chat_for_pr(repo, number)
            if found is not None:
                entry = found
                self._store[key] = entry
        if entry is None:
            return
        entry.has_approval = False
        if entry.status == PRStatus.CHECKS_PASSED:
            try:
                if not entry.content and not self._ensure_entry_content(entry):
                    refound = self._search_chat_for_pr(repo, number)
                    if refound and refound.content:
                        entry.content = refound.content
                if entry.content:
                    new_content = GitHubPRMessage.patch_parent_status(
                        entry.content, PRStatus.READY_FOR_REVIEW
                    )
                    self._client.update_message(entry.message_id, new_content)
                    entry.status = PRStatus.READY_FOR_REVIEW
                    entry.content = new_content
            except Exception:
                logger.warning(
                    "Failed to downgrade PR #%s after approval cleared",
                    number,
                    exc_info=True,
                )

    def record_approval_and_maybe_promote(self, repo: str, number: int) -> bool:
        """Set has_approval. Promote to Ready to merge only if checks_passed.
        Returns True if promoted."""
        key = self._make_key(repo, number)
        entry = self._store.get(key)
        if entry is None:
            found = self._search_chat_for_pr(repo, number)
            if found is not None:
                entry = found
                self._store[key] = entry
        if entry is None:
            return False
        entry.has_approval = True
        if not entry.checks_passed or entry.status == PRStatus.CHECKS_PASSED:
            return False
        try:
            if not entry.content and not self._ensure_entry_content(entry):
                refound = self._search_chat_for_pr(repo, number)
                if refound and refound.content:
                    entry.content = refound.content
            if not entry.content:
                return False
            new_content = GitHubPRMessage.patch_parent_status(
                entry.content, PRStatus.CHECKS_PASSED
            )
            self._client.update_message(entry.message_id, new_content)
            entry.status = PRStatus.CHECKS_PASSED
            entry.content = new_content
            return True
        except Exception:
            logger.warning(
                "Failed to promote PR #%s to Ready to merge after approval",
                number,
                exc_info=True,
            )
            return False

    def downgrade_status_on_ci_failure(self, repo: str, number: int) -> bool:
        """If PR is marked Ready to merge, downgrade to Ready for review when CI fails."""
        key = self._make_key(repo, number)
        entry = self._store.get(key)
        if entry is None:
            found = self._search_chat_for_pr(repo, number)
            if found is not None:
                entry = found
                self._store[key] = entry
        if entry is None or entry.status != PRStatus.CHECKS_PASSED:
            return False
        if not entry.content and not self._ensure_entry_content(entry):
            refound = self._search_chat_for_pr(repo, number)
            if refound and refound.content:
                entry.content = refound.content
            else:
                logger.warning("Skipping CI failure downgrade for PR #%s: no content", number)
                return False
        try:
            new_content = GitHubPRMessage.patch_parent_status(
                entry.content, PRStatus.READY_FOR_REVIEW
            )
            self._client.update_message(entry.message_id, new_content)
            entry.status = PRStatus.READY_FOR_REVIEW
            entry.content = new_content
            entry.checks_passed = False
            return True
        except Exception:
            logger.warning(
                "Failed to downgrade PR #%s status on CI failure",
                number,
                exc_info=True,
            )
            return False

    def _create_new(self, key: tuple[str, int], pr_msg: GitHubPRMessage) -> dict:
        content = pr_msg.to_parent()
        result = self._client.send_message(
            content,
            display_name=self._integration.display_name,
            display_avatar_url=self._integration.display_avatar_url,
            chat_id=self._integration.chat_id,
        )
        msg_id = result.get("id")
        if msg_id:
            self._store[key] = _PREntry(message_id=msg_id, status=pr_msg.status, content=content)
        return result

    def handle_pr_event(
        self, pr_msg: GitHubPRMessage, *, create_if_missing: bool = True
    ) -> dict | None:
        key = self._make_key(pr_msg.repo, pr_msg.number)

        if pr_msg.status == PRStatus.REOPENED:
            return self._create_new(key, pr_msg)

        entry = self._store.get(key)

        if entry is None:
            found = self._search_chat_for_pr(pr_msg.repo, pr_msg.number)
            if found is not None:
                entry = found
                self._store[key] = entry

        if entry is None:
            if not create_if_missing:
                return None
            return self._create_new(key, pr_msg)

        if pr_msg.status == PRStatus.READY_FOR_REVIEW:
            entry.checks_passed = False
            entry.has_approval = False

        old_status = entry.status
        if old_status == pr_msg.status:
            return {"id": entry.message_id, "unchanged": True}

        try:
            thread = self._client.create_thread(entry.message_id)
            thread_id = thread.get("id")
            if thread_id:
                thread_content = pr_msg.to_thread_update(old_status=old_status)
                self._client.post_to_thread(
                    thread_id,
                    thread_content,
                    display_name=self._integration.display_name,
                    display_avatar_url=self._integration.display_avatar_url,
                )
        except Exception:
            logger.warning("Failed to post thread update for PR #%s", pr_msg.number, exc_info=True)

        try:
            if not entry.content and not (pr_msg.author or pr_msg.title):
                # Minimal pr_msg: try to fetch content before giving up
                if self._ensure_entry_content(entry):
                    pass  # content now available, fall through to patch
                else:
                    # Retry scan in case list API had transient empty content
                    refound = self._search_chat_for_pr(pr_msg.repo, pr_msg.number)
                    if refound and refound.content:
                        entry.content = refound.content
                    else:
                        logger.warning(
                            "Skipping parent update for PR #%s: could not fetch content",
                            pr_msg.number,
                        )
                        return {"id": entry.message_id}
            if entry.content:
                new_content = GitHubPRMessage.patch_parent_status(entry.content, pr_msg.status)
            else:
                new_content = pr_msg.to_parent()
            self._client.update_message(entry.message_id, new_content)
            entry.status = pr_msg.status
            entry.content = new_content
        except Exception:
            logger.warning(
                "Failed to update parent message %s, creating new one",
                entry.message_id,
                exc_info=True,
            )
            return self._create_new(key, pr_msg)

        return {"id": entry.message_id}
