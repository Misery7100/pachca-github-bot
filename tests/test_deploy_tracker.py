"""Tests for DeployTracker — thread-based deploy lifecycle."""

from unittest.mock import MagicMock

from pachca_bot.deploy_tracker import DeployTracker, _DeployEntry
from pachca_bot.models.messages import DeployStatus, GenericDeployMessage


def _make_tracker() -> tuple[DeployTracker, MagicMock]:
    client = MagicMock()
    client.send_message.return_value = {"id": 100}
    client.get_messages.return_value = []
    client.create_thread.return_value = {"id": 200}
    client.post_to_thread.return_value = {"id": 201}
    client.update_message.return_value = {"id": 100}
    tracker = DeployTracker(client)
    return tracker, client


def _make_deploy(
    deploy_id: str = "dep-1",
    status: DeployStatus = DeployStatus.STARTED,
) -> GenericDeployMessage:
    return GenericDeployMessage(
        source="api",
        environment="prod",
        version="1.0",
        status=status,
        deploy_id=deploy_id,
    )


class TestDeployTrackerNew:
    def test_creates_message(self):
        tracker, client = _make_tracker()
        result = tracker.handle_deploy_event(_make_deploy())
        assert result["id"] == 100
        client.send_message.assert_called_once()

    def test_no_id_posts_directly(self):
        tracker, client = _make_tracker()
        msg = _make_deploy(deploy_id="")
        result = tracker.handle_deploy_event(msg)
        assert result["id"] == 100
        assert ("api", "") not in tracker._store


class TestDeployTrackerUpdate:
    def test_thread_update_format(self):
        tracker, client = _make_tracker()
        content = _make_deploy().to_parent()
        tracker._store[("api", "dep-1")] = _DeployEntry(
            message_id=100, status=DeployStatus.STARTED, content=content
        )
        tracker.handle_deploy_event(_make_deploy(status=DeployStatus.SUCCEEDED))

        client.create_thread.assert_called_once()
        thread_text = client.post_to_thread.call_args[0][1]
        assert "**Status updated:**" in thread_text
        assert "Before:" in thread_text
        assert "After:" in thread_text

    def test_skips_same_status(self):
        tracker, client = _make_tracker()
        tracker._store[("api", "dep-1")] = _DeployEntry(
            message_id=100, status=DeployStatus.STARTED, content=""
        )
        result = tracker.handle_deploy_event(_make_deploy())
        assert result.get("unchanged") is True
        client.create_thread.assert_not_called()


class TestDeployTrackerChatFallback:
    def test_finds_deploy_in_chat(self):
        tracker, client = _make_tracker()
        client.get_messages.return_value = [
            {"id": 555, "content": "## 🚀 Deploy Started: api\n\n**ID:** dep-42"}
        ]
        tracker.handle_deploy_event(_make_deploy(deploy_id="dep-42", status=DeployStatus.SUCCEEDED))
        client.create_thread.assert_called_once_with(555)
