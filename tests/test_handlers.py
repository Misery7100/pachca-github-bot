"""Tests for GitHub and generic webhook handlers."""

from unittest.mock import MagicMock

from pachca_bot.handlers.generic import handle_generic_event
from pachca_bot.handlers.github import handle_github_event
from pachca_bot.models.messages import PRStatus, Severity, StructuredMessage
from pachca_bot.models.webhooks import GenericWebhookPayload, GitHubWebhookPayload
from pachca_bot.pr_tracker import PRTracker


def _make_mock_tracker() -> PRTracker:
    client = MagicMock()
    client.send_message.return_value = {"id": 100}
    client.get_messages.return_value = []
    client.create_thread.return_value = {"id": 200}
    client.post_to_thread.return_value = {"id": 201}
    client.update_message.return_value = {"id": 100}
    return PRTracker(client)


class TestGitHubHandler:
    def test_release(self):
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "published",
                "repository": {"full_name": "org/repo"},
                "sender": {"login": "alice"},
                "release": {
                    "tag_name": "v1.0.0",
                    "name": "Version 1.0",
                    "body": "Changelog",
                    "html_url": "https://github.com/org/repo/releases/tag/v1.0.0",
                    "author": {"login": "alice"},
                },
            }
        )
        result = handle_github_event("release", payload)
        assert isinstance(result, StructuredMessage)
        rendered = result.render()
        assert "🔖" in rendered
        assert "**Tag:**" not in rendered
        assert "**Release:**" not in rendered
        assert "[View release](" in rendered

    def test_workflow_failure(self):
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "completed",
                "repository": {"full_name": "org/repo"},
                "workflow_run": {
                    "name": "CI",
                    "head_branch": "main",
                    "head_sha": "abc123",
                    "conclusion": "failure",
                    "html_url": "https://github.com/org/repo/actions/runs/1",
                    "actor": {"login": "alice"},
                },
            }
        )
        result = handle_github_event("workflow_run", payload)
        assert isinstance(result, StructuredMessage)
        rendered = result.render()
        assert "CI" in rendered
        assert "**Triggered by:**" not in rendered

    def test_workflow_failure_posted_to_pr_thread(self):
        tracker = _make_mock_tracker()
        tracker._store[("org/repo", 5)] = MagicMock(
            message_id=100, status=PRStatus.OPEN, content=""
        )
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "completed",
                "repository": {"full_name": "org/repo"},
                "workflow_run": {
                    "name": "CI",
                    "head_branch": "feat",
                    "head_sha": "abc123",
                    "conclusion": "failure",
                    "html_url": "https://github.com/org/repo/actions/runs/1",
                    "actor": {"login": "alice"},
                    "pull_requests": [{"number": 5}],
                },
            }
        )
        result = handle_github_event("workflow_run", payload, pr_tracker=tracker)
        assert isinstance(result, dict)
        assert result.get("posted_to_pr_thread") is True

    def test_pr_opened(self):
        tracker = _make_mock_tracker()
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "opened",
                "repository": {"full_name": "org/repo"},
                "pull_request": {
                    "number": 7,
                    "title": "Feature",
                    "html_url": "https://github.com/org/repo/pull/7",
                    "user": {"login": "alice"},
                    "head": {"ref": "feat"},
                    "base": {"ref": "main"},
                    "draft": False,
                },
            }
        )
        result = handle_github_event("pull_request", payload, pr_tracker=tracker)
        assert isinstance(result, dict)
        assert result["id"] == 100

    def test_pr_labeled_ignored(self):
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "labeled",
                "repository": {"full_name": "org/repo"},
                "pull_request": {
                    "number": 1,
                    "title": "PR",
                    "html_url": "https://github.com/org/repo/pull/1",
                    "user": {"login": "x"},
                    "head": {"ref": "a"},
                    "base": {"ref": "main"},
                },
            }
        )
        assert handle_github_event("pull_request", payload) is None

    def test_ping(self):
        payload = GitHubWebhookPayload.model_validate(
            {"zen": "...", "repository": {"full_name": "org/repo"}}
        )
        result = handle_github_event("ping", payload)
        assert isinstance(result, StructuredMessage)
        assert "connected" in result.render()


class TestGenericHandler:
    def test_alert_source_as_field(self):
        payload = GenericWebhookPayload(
            event_type="alert",
            source="monitor",
            title="CPU spike",
            severity=Severity.WARNING,
            fields={"Host": "vm-01"},
        )
        result = handle_generic_event(payload)
        assert isinstance(result, StructuredMessage)
        rendered = result.render()
        assert "**Source:** monitor" in rendered
        assert "[monitor]" not in rendered

    def test_deploy_without_id(self):
        payload = GenericWebhookPayload(
            event_type="deploy",
            source="api",
            title="",
            environment="staging",
            version="1.2.3",
            status="succeeded",
        )
        result = handle_generic_event(payload)
        assert isinstance(result, StructuredMessage)
        assert "1.2.3" in result.render()

    def test_deploy_with_id_no_tracker(self):
        payload = GenericWebhookPayload(
            event_type="deploy",
            source="api",
            title="",
            environment="prod",
            version="1.0",
            status="started",
            deploy_id="dep-42",
        )
        result = handle_generic_event(payload, deploy_tracker=None)
        assert isinstance(result, StructuredMessage)
