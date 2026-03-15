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
    def test_release_published(self):
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "published",
                "repository": {"full_name": "org/repo", "html_url": "https://github.com/org/repo"},
                "sender": {"login": "alice"},
                "release": {
                    "tag_name": "v1.0.0",
                    "name": "Version 1.0",
                    "body": "Changelog",
                    "html_url": "https://github.com/org/repo/releases/tag/v1.0.0",
                    "prerelease": False,
                    "author": {"login": "alice"},
                },
            }
        )
        result = handle_github_event("release", payload)
        assert isinstance(result, StructuredMessage)
        rendered = result.render()
        assert "v1.0.0" in rendered
        assert "[org/repo](" in rendered
        assert "[alice](" in rendered
        assert "**Tag:**" not in rendered

    def test_workflow_run_failure(self):
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "completed",
                "repository": {"full_name": "org/repo"},
                "sender": {"login": "ci-bot"},
                "workflow_run": {
                    "name": "CI Pipeline",
                    "head_branch": "main",
                    "head_sha": "abc1234567890",
                    "conclusion": "failure",
                    "html_url": "https://github.com/org/repo/actions/runs/123",
                    "actor": {"login": "alice"},
                },
            }
        )
        result = handle_github_event("workflow_run", payload)
        assert isinstance(result, StructuredMessage)
        rendered = result.render()
        assert "CI Pipeline" in rendered
        assert "failure" in rendered

    def test_workflow_run_success_ignored(self):
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "completed",
                "repository": {"full_name": "org/repo"},
                "workflow_run": {
                    "name": "CI",
                    "head_branch": "main",
                    "head_sha": "abc123",
                    "conclusion": "success",
                    "html_url": "https://github.com/org/repo/actions/runs/1",
                },
            }
        )
        assert handle_github_event("workflow_run", payload) is None

    def test_pr_opened_creates_message(self):
        tracker = _make_mock_tracker()
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "opened",
                "repository": {"full_name": "org/repo"},
                "sender": {"login": "alice"},
                "pull_request": {
                    "number": 7,
                    "title": "Add feature",
                    "body": "Desc",
                    "html_url": "https://github.com/org/repo/pull/7",
                    "user": {"login": "alice"},
                    "head": {"ref": "feature-x"},
                    "base": {"ref": "main"},
                    "merged": False,
                    "draft": False,
                },
            }
        )
        result = handle_github_event("pull_request", payload, pr_tracker=tracker)
        assert isinstance(result, dict)
        assert result.get("id") == 100
        tracker._client.send_message.assert_called_once()

    def test_pr_draft_status(self):
        tracker = _make_mock_tracker()
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "opened",
                "repository": {"full_name": "org/repo"},
                "pull_request": {
                    "number": 1,
                    "title": "WIP",
                    "html_url": "https://github.com/org/repo/pull/1",
                    "user": {"login": "bob"},
                    "head": {"ref": "wip"},
                    "base": {"ref": "main"},
                    "draft": True,
                },
            }
        )
        result = handle_github_event("pull_request", payload, pr_tracker=tracker)
        assert isinstance(result, dict)
        content = tracker._client.send_message.call_args[0][0]
        assert PRStatus.DRAFT.emoji in content

    def test_pr_closed_merged(self):
        tracker = _make_mock_tracker()
        tracker._store[("org/repo", 7)] = MagicMock(message_id=100, status=PRStatus.OPEN)
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "closed",
                "repository": {"full_name": "org/repo"},
                "pull_request": {
                    "number": 7,
                    "title": "Feature",
                    "html_url": "https://github.com/org/repo/pull/7",
                    "user": {"login": "alice"},
                    "head": {"ref": "feat"},
                    "base": {"ref": "main"},
                    "merged": True,
                },
            }
        )
        result = handle_github_event("pull_request", payload, pr_tracker=tracker)
        assert isinstance(result, dict)
        tracker._client.create_thread.assert_called_once()
        tracker._client.update_message.assert_called_once()

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

    def test_check_suite_marks_pr_checks_passed(self):
        tracker = _make_mock_tracker()
        tracker._store[("org/repo", 5)] = MagicMock(message_id=100, status=PRStatus.OPEN)
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "completed",
                "repository": {"full_name": "org/repo"},
                "check_suite": {
                    "id": 1,
                    "head_branch": "feat",
                    "head_sha": "abc123",
                    "status": "completed",
                    "conclusion": "success",
                    "pull_requests": [{"number": 5}],
                },
            }
        )
        result = handle_github_event("check_suite", payload, pr_tracker=tracker)
        assert result is not None

    def test_deployment_created(self):
        payload = GitHubWebhookPayload.model_validate(
            {
                "action": "created",
                "repository": {"full_name": "org/repo", "html_url": "https://github.com/org/repo"},
                "sender": {"login": "alice"},
                "deployment": {
                    "id": 1,
                    "sha": "abc123def456",
                    "ref": "main",
                    "environment": "production",
                    "creator": {"login": "alice"},
                },
            }
        )
        result = handle_github_event("deployment", payload)
        assert isinstance(result, StructuredMessage)
        rendered = result.render()
        assert "production" in rendered
        assert "[alice](" in rendered

    def test_ping(self):
        payload = GitHubWebhookPayload.model_validate(
            {"zen": "Keep it logically awesome.", "repository": {"full_name": "org/repo"}}
        )
        result = handle_github_event("ping", payload)
        assert isinstance(result, StructuredMessage)
        assert "connected" in result.render()

    def test_unsupported_event_ignored(self):
        payload = GitHubWebhookPayload.model_validate(
            {"action": "created", "repository": {"full_name": "org/repo"}}
        )
        assert handle_github_event("star", payload) is None


class TestGenericHandler:
    def test_alert_event(self):
        payload = GenericWebhookPayload(
            event_type="alert",
            source="monitor",
            title="CPU spike",
            severity=Severity.WARNING,
            details="CPU at 95%",
            fields={"Host": "vm-01"},
        )
        result = handle_generic_event(payload)
        rendered = result.render()
        assert "CPU spike" in rendered

    def test_deploy_event(self):
        payload = GenericWebhookPayload(
            event_type="deploy",
            source="api",
            title="",
            environment="staging",
            version="1.2.3",
            status="succeeded",
            actor="deployer",
            changelog=["Fixed login"],
        )
        result = handle_generic_event(payload)
        rendered = result.render()
        assert "1.2.3" in rendered
        assert "staging" in rendered

    def test_custom_event(self):
        payload = GenericWebhookPayload(
            event_type="custom",
            source="scheduler",
            title="Backup completed",
        )
        result = handle_generic_event(payload)
        assert "Backup completed" in result.render()
