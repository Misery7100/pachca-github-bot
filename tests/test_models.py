"""Tests for message models and rendering."""

from pachca_bot.models.messages import (
    CodeBlock,
    DeployStatus,
    DividerBlock,
    FieldsBlock,
    GenericAlertMessage,
    GenericDeployMessage,
    GitHubCIMessage,
    GitHubPRMessage,
    GitHubReleaseMessage,
    HeaderBlock,
    LinkBlock,
    ListBlock,
    PRStatus,
    QuoteBlock,
    Severity,
    StructuredMessage,
    TextBlock,
    render_status_update,
)


class TestBlocks:
    def test_header_block(self):
        assert HeaderBlock(text="Hello", level=2).render() == "## Hello"

    def test_text_block_plain(self):
        assert TextBlock(text="hi").render() == "hi"

    def test_text_block_bold_italic(self):
        assert TextBlock(text="x", bold=True, italic=True).render() == "***x***"

    def test_link_block(self):
        assert LinkBlock(text="Go", url="https://x.co").render() == "[Go](https://x.co)"

    def test_fields_block(self):
        out = FieldsBlock(fields={"A": "1", "B": "2"}).render()
        assert "**A:** 1" in out
        assert "**B:** 2" in out

    def test_code_block(self):
        out = CodeBlock(code="x = 1", language="python").render()
        assert out.startswith("```python")

    def test_quote_block(self):
        out = QuoteBlock(text="line1\nline2").render()
        assert out == "> line1\n> line2"

    def test_list_block_unordered(self):
        assert "• a" in ListBlock(items=["a", "b"]).render()

    def test_list_block_ordered(self):
        out = ListBlock(items=["a", "b"], ordered=True).render()
        assert "1. a" in out
        assert "2. b" in out

    def test_divider(self):
        assert DividerBlock().render() == "---"

    def test_structured_message(self):
        msg = StructuredMessage()
        msg.add(HeaderBlock(text="Title"))
        msg.add(TextBlock(text="Body"))
        assert "# Title" in msg.render()

    def test_structured_empty(self):
        assert StructuredMessage().render() == ""


class TestStatusUpdate:
    def test_format(self):
        result = render_status_update("📝", "Draft", "🆕", "Open")
        assert "**Status updated:**" in result
        assert "Before: 📝 Draft" in result
        assert "After: 🆕 Open" in result


class TestReleaseMessage:
    def test_no_tag_no_duplicate_title(self):
        m = GitHubReleaseMessage(
            repo="org/repo",
            tag="v1.0.0",
            release_name="Release 1.0",
            author="alice",
            url="https://github.com/org/repo/releases/tag/v1.0.0",
            body="changelog here",
        )
        rendered = m.to_structured().render()
        assert "🔖 Release:" in rendered
        assert "[v1.0.0](https://github.com/org/repo/releases/tag/v1.0.0)" in rendered
        assert "[org/repo](https://github.com/org/repo)" in rendered
        assert "[alice](https://github.com/alice)" in rendered
        assert "**Tag:**" not in rendered
        assert "**Release:**" not in rendered
        assert "[View release](" in rendered
        assert "changelog here" in rendered

    def test_prerelease(self):
        m = GitHubReleaseMessage(
            repo="org/repo",
            tag="v2.0.0-rc1",
            release_name="RC1",
            author="bob",
            url="https://github.com/org/repo/releases/tag/v2.0.0-rc1",
            prerelease=True,
        )
        assert "pre-release" in m.to_structured().render()


class TestCIMessage:
    def test_channel_message(self):
        m = GitHubCIMessage(
            workflow_name="CI",
            commit_sha="abc12345678",
            repo="org/repo",
            conclusion="failure",
            url="https://github.com/org/repo/actions/runs/1",
        )
        rendered = m.to_structured().render()
        assert "CI" in rendered
        assert "[abc12345](" in rendered
        assert "[org/repo](" in rendered
        assert "**Triggered by:**" not in rendered

    def test_pr_thread_message(self):
        m = GitHubCIMessage(
            workflow_name="CI",
            commit_sha="abc12345678",
            repo="org/repo",
            conclusion="failure",
            url="https://github.com/org/repo/actions/runs/1",
            for_pr_thread=True,
        )
        rendered = m.to_structured().render()
        assert "[org/repo](" not in rendered
        assert "[abc12345](" in rendered


class TestPRMessage:
    def _make_pr(self, status: PRStatus = PRStatus.OPEN) -> GitHubPRMessage:
        return GitHubPRMessage(
            repo="org/repo",
            number=42,
            title="Fix bug",
            author="alice",
            url="https://github.com/org/repo/pull/42",
            base_branch="main",
            head_branch="fix-bug",
            body="Description",
            status=status,
        )

    def test_parent_hyperlinks(self):
        rendered = self._make_pr().to_parent()
        assert "[#42](https://github.com/org/repo/pull/42)" in rendered
        assert "[org/repo](https://github.com/org/repo)" in rendered
        assert "[alice](https://github.com/alice)" in rendered
        assert "[fix-bug](" in rendered
        assert "[main](" in rendered
        assert "→" in rendered

    def test_parent_no_status_field(self):
        rendered = self._make_pr().to_parent()
        assert "**Status:**" not in rendered

    def test_parent_status_in_header(self):
        for status in PRStatus:
            rendered = self._make_pr(status).to_parent()
            assert status.emoji in rendered
            assert status.label in rendered

    def test_thread_update_format(self):
        pr = self._make_pr(PRStatus.READY_FOR_REVIEW)
        update = pr.to_thread_update(old_status=PRStatus.OPEN)
        assert "**Status updated:**" in update
        assert "Before: 🆕 Open" in update
        assert "After: 👀 Ready for review" in update

    def test_patch_parent_status(self):
        pr = self._make_pr(PRStatus.OPEN)
        original = pr.to_parent()
        assert "🆕" in original
        patched = GitHubPRMessage.patch_parent_status(original, PRStatus.MERGED)
        assert "🟣" in patched
        assert "🆕" not in patched
        assert "[alice](" in patched
        assert "[fix-bug](" in patched


class TestGenericAlert:
    def test_source_as_field(self):
        m = GenericAlertMessage(
            source="monitoring",
            title="Disk usage high",
            severity=Severity.WARNING,
            details="90% used",
            fields={"Host": "vm-01"},
        )
        rendered = m.to_structured().render()
        assert "**Source:** monitoring" in rendered
        assert "[monitoring]" not in rendered
        assert "Disk usage high" in rendered


class TestGenericDeploy:
    def test_with_id(self):
        m = GenericDeployMessage(
            source="api",
            environment="production",
            version="2.3.1",
            status=DeployStatus.SUCCEEDED,
            deploy_id="deploy-42",
        )
        rendered = m.to_parent()
        assert "**ID:** deploy-42" in rendered
        assert "production" in rendered

    def test_without_id(self):
        m = GenericDeployMessage(
            source="api",
            environment="prod",
            version="1.0",
            status=DeployStatus.STARTED,
        )
        rendered = m.to_parent()
        assert "**ID:**" not in rendered

    def test_thread_update(self):
        m = GenericDeployMessage(
            source="api",
            environment="prod",
            version="1.0",
            status=DeployStatus.SUCCEEDED,
        )
        update = m.to_thread_update(DeployStatus.STARTED)
        assert "**Status updated:**" in update
        assert "Before:" in update
        assert "After:" in update

    def test_patch_parent_status(self):
        m = GenericDeployMessage(
            source="api",
            environment="prod",
            version="1.0",
            status=DeployStatus.STARTED,
        )
        original = m.to_parent()
        patched = GenericDeployMessage.patch_parent_status(original, DeployStatus.SUCCEEDED)
        assert "✅ Deploy Succeeded:" in patched
        assert "🚀" not in patched
