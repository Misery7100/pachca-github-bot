"""Tests for PRTracker — thread-based PR lifecycle management."""

from unittest.mock import MagicMock

from pachca_bot.models.messages import GitHubPRMessage, PRStatus
from pachca_bot.pr_tracker import PRTracker, _PREntry


def _make_tracker() -> tuple[PRTracker, MagicMock]:
    client = MagicMock()
    client.send_message.return_value = {"id": 100}
    client.get_messages.return_value = []
    client.create_thread.return_value = {"id": 200}
    client.post_to_thread.return_value = {"id": 201}
    client.update_message.return_value = {"id": 100}
    tracker = PRTracker(client)
    return tracker, client


def _make_pr(
    number: int = 1,
    status: PRStatus = PRStatus.OPEN,
    title: str = "Test PR",
) -> GitHubPRMessage:
    return GitHubPRMessage(
        repo="org/repo",
        number=number,
        title=title,
        author="alice",
        url=f"https://github.com/org/repo/pull/{number}",
        base_branch="main",
        head_branch="feat",
        status=status,
    )


class TestPRTrackerNewPR:
    def test_creates_new_message(self):
        tracker, client = _make_tracker()
        pr = _make_pr(status=PRStatus.DRAFT)
        result = tracker.handle_pr_event(pr)
        assert result["id"] == 100
        client.send_message.assert_called_once()
        content = client.send_message.call_args[0][0]
        assert PRStatus.DRAFT.emoji in content

    def test_stores_entry(self):
        tracker, _ = _make_tracker()
        pr = _make_pr(number=42)
        tracker.handle_pr_event(pr)
        assert ("org/repo", 42) in tracker._store


class TestPRTrackerUpdate:
    def test_creates_thread_and_updates_parent(self):
        tracker, client = _make_tracker()
        tracker._store[("org/repo", 1)] = _PREntry(message_id=100, status=PRStatus.DRAFT)
        pr = _make_pr(status=PRStatus.OPEN)
        tracker.handle_pr_event(pr)

        client.create_thread.assert_called_once_with(100)
        client.post_to_thread.assert_called_once()
        client.update_message.assert_called_once()

        thread_content = client.post_to_thread.call_args[0][1]
        assert PRStatus.DRAFT.emoji in thread_content
        assert PRStatus.OPEN.emoji in thread_content

    def test_skips_if_same_status(self):
        tracker, client = _make_tracker()
        tracker._store[("org/repo", 1)] = _PREntry(message_id=100, status=PRStatus.OPEN)
        pr = _make_pr(status=PRStatus.OPEN)
        result = tracker.handle_pr_event(pr)

        assert result.get("unchanged") is True
        client.create_thread.assert_not_called()
        client.update_message.assert_not_called()


class TestPRTrackerChatFallback:
    def test_finds_pr_in_chat(self):
        tracker, client = _make_tracker()
        client.get_messages.return_value = [
            {
                "id": 555,
                "content": "## 🆕 PR [#7](https://github.com/org/repo/pull/7) Open: Feature\n\n"
                "**Status:** 🆕 Open",
            }
        ]
        pr = _make_pr(number=7, status=PRStatus.MERGED)
        tracker.handle_pr_event(pr)

        client.create_thread.assert_called_once_with(555)
        client.update_message.assert_called_once()

    def test_creates_new_if_not_found(self):
        tracker, client = _make_tracker()
        client.get_messages.return_value = []
        pr = _make_pr(number=99, status=PRStatus.OPEN)
        tracker.handle_pr_event(pr)

        client.send_message.assert_called_once()


class TestPRTrackerFullLifecycle:
    def test_draft_to_open_to_review_to_merged(self):
        tracker, client = _make_tracker()

        pr_draft = _make_pr(status=PRStatus.DRAFT)
        tracker.handle_pr_event(pr_draft)
        client.send_message.assert_called_once()

        pr_open = _make_pr(status=PRStatus.OPEN)
        tracker.handle_pr_event(pr_open)
        assert client.create_thread.call_count == 1

        pr_review = _make_pr(status=PRStatus.READY_FOR_REVIEW)
        tracker.handle_pr_event(pr_review)
        assert client.create_thread.call_count == 2

        pr_merged = _make_pr(status=PRStatus.MERGED)
        tracker.handle_pr_event(pr_merged)
        assert client.create_thread.call_count == 3
        assert client.update_message.call_count == 3
