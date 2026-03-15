"""Thread-based PR tracking.

Maintains an in-memory mapping of (repo, pr_number) → pachca_message_id.
On each PR status change the tracker:
  1. Finds the existing parent message (in-memory or by scanning chat)
  2. Creates/gets the thread and posts a status-change reply
  3. Updates the parent message with the new status
  4. If no parent message exists, creates a new one
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pachca_bot.client import PachcaClient
from pachca_bot.config import DISPLAY_NAME_GITHUB
from pachca_bot.models.messages import GitHubPRMessage, PRStatus

logger = logging.getLogger(__name__)

PR_MARKER_RE = re.compile(r"PR \[#(\d+)\]\(https://github\.com/([^)]+)/pull/\d+\)")


@dataclass
class _PREntry:
    message_id: int
    status: PRStatus


class PRTracker:
    """In-memory PR → Pachca message tracker with chat-search fallback."""

    def __init__(self, client: PachcaClient) -> None:
        self._client = client
        self._store: dict[tuple[str, int], _PREntry] = field(default_factory=dict)
        self._store = {}

    def _make_key(self, repo: str, number: int) -> tuple[str, int]:
        return (repo, number)

    def _search_chat_for_pr(self, repo: str, number: int) -> int | None:
        """Scan recent chat messages for a PR parent message."""
        try:
            messages = self._client.get_messages()
        except Exception:
            logger.warning("Failed to fetch chat messages for PR lookup", exc_info=True)
            return None

        target = f"PR [#{number}](https://github.com/{repo}/pull/{number})"
        for msg in messages:
            content = msg.get("content", "")
            if target in content:
                return msg.get("id")
        return None

    def _infer_status_from_content(self, content: str) -> PRStatus | None:
        """Try to infer the current PR status from the parent message content."""
        for status in PRStatus:
            if f"{status.emoji} {status.label}" in content:
                return status
        return None

    def handle_pr_event(self, pr_msg: GitHubPRMessage) -> dict:
        """Process a PR status change. Returns the API response dict."""
        key = self._make_key(pr_msg.repo, pr_msg.number)
        entry = self._store.get(key)

        if entry is None:
            msg_id = self._search_chat_for_pr(pr_msg.repo, pr_msg.number)
            if msg_id is not None:
                try:
                    messages = self._client.get_messages()
                    for m in messages:
                        if m.get("id") == msg_id:
                            old_status = self._infer_status_from_content(m.get("content", ""))
                            entry = _PREntry(message_id=msg_id, status=old_status or PRStatus.OPEN)
                            self._store[key] = entry
                            break
                except Exception:
                    entry = _PREntry(message_id=msg_id, status=PRStatus.OPEN)
                    self._store[key] = entry

        if entry is None:
            content = pr_msg.to_parent()
            result = self._client.send_message(content, display_name=DISPLAY_NAME_GITHUB)
            msg_id = result.get("id")
            if msg_id:
                self._store[key] = _PREntry(message_id=msg_id, status=pr_msg.status)
            return result

        old_status = entry.status
        if old_status == pr_msg.status:
            return {"id": entry.message_id, "unchanged": True}

        try:
            thread = self._client.create_thread(entry.message_id)
            thread_id = thread.get("id")
            if thread_id:
                thread_content = pr_msg.to_thread_update(old_status=old_status)
                self._client.post_to_thread(
                    thread_id, thread_content, display_name=DISPLAY_NAME_GITHUB
                )
        except Exception:
            logger.warning("Failed to post thread update for PR #%s", pr_msg.number, exc_info=True)

        try:
            new_content = pr_msg.to_parent()
            self._client.update_message(entry.message_id, new_content)
        except Exception:
            logger.warning(
                "Failed to update parent message %s, creating new one",
                entry.message_id,
                exc_info=True,
            )
            result = self._client.send_message(pr_msg.to_parent(), display_name=DISPLAY_NAME_GITHUB)
            msg_id = result.get("id")
            if msg_id:
                self._store[key] = _PREntry(message_id=msg_id, status=pr_msg.status)
            return result

        entry.status = pr_msg.status
        return {"id": entry.message_id}
