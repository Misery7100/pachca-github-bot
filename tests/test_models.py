"""Tests for message models and rendering."""

from pachca_bot.models.messages import (
    CodeBlock,
    DividerBlock,
    FieldsBlock,
    GenericAlertMessage,
    GenericDeployMessage,
    GitHubCheckFailureMessage,
    GitHubDeploymentMessage,
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
        assert "x = 1" in out

    def test_quote_block(self):
        out = QuoteBlock(text="line1\nline2").render()
        assert out == "> line1\n> line2"

    def test_list_block_unordered(self):
        out = ListBlock(items=["a", "b"]).render()
        assert "• a" in out

    def test_list_block_ordered(self):
        out = ListBlock(items=["a", "b"], ordered=True).render()
        assert "1. a" in out
        assert "2. b" in out

    def test_divider(self):
        assert DividerBlock().render() == "---"


class TestStructuredMessage:
    def test_compose(self):
        msg = StructuredMessage()
        msg.add(HeaderBlock(text="Title"))
        msg.add(TextBlock(text="Body"))
        rendered = msg.render()
        assert "# Title" in rendered
        assert "Body" in rendered

    def test_empty(self):
        assert StructuredMessage().render() == ""


class TestReleaseMessage:
    def test_has_hyperlinks_no_tag_field(self):
        m = GitHubReleaseMessage(
            repo="org/repo",
            tag="v1.0.0",
            release_name="Release 1.0",
            author="alice",
            url="https://github.com/org/repo/releases/tag/v1.0.0",
            body="changelog here",
        )
        rendered = m.to_structured().render()
        assert "[Release 1.0](https://github.com/org/repo/releases/tag/v1.0.0)" in rendered
        assert "[org/repo](https://github.com/org/repo)" in rendered
        assert "[alice](https://github.com/alice)" in rendered
        assert "changelog here" in rendered
        assert "**Tag:**" not in rendered
        assert "`v1.0.0`" not in rendered

    def test_prerelease(self):
        m = GitHubReleaseMessage(
            repo="org/repo",
            tag="v2.0.0-rc1",
            release_name="RC1",
            author="bob",
            url="https://github.com/org/repo/releases/tag/v2.0.0-rc1",
            prerelease=True,
        )
        rendered = m.to_structured().render()
        assert "pre-release" in rendered


class TestCheckFailureMessage:
    def test_has_hyperlinks(self):
        m = GitHubCheckFailureMessage(
            repo="org/repo",
            workflow_name="CI",
            branch="main",
            commit_sha="abc12345678",
            conclusion="failure",
            url="https://github.com/org/repo/actions/runs/1",
            actor="alice",
        )
        rendered = m.to_structured().render()
        assert "CI" in rendered
        assert "failure" in rendered
        assert "[abc12345](https://github.com/org/repo/commit/abc12345678)" in rendered
        assert "[main](https://github.com/org/repo/tree/main)" in rendered
        assert "[alice](https://github.com/alice)" in rendered


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

    def test_parent_has_hyperlinks(self):
        pr = self._make_pr()
        rendered = pr.to_parent()
        assert "[#42](https://github.com/org/repo/pull/42)" in rendered
        assert "[org/repo](https://github.com/org/repo)" in rendered
        assert "[alice](https://github.com/alice)" in rendered
        assert "[fix-bug](https://github.com/org/repo/tree/fix-bug)" in rendered
        assert "[main](https://github.com/org/repo/tree/main)" in rendered
        assert "→" in rendered

    def test_parent_status_emoji(self):
        for status in PRStatus:
            pr = self._make_pr(status)
            rendered = pr.to_parent()
            assert status.emoji in rendered
            assert status.label in rendered

    def test_thread_update(self):
        pr = self._make_pr(PRStatus.READY_FOR_REVIEW)
        update = pr.to_thread_update(old_status=PRStatus.OPEN)
        assert PRStatus.OPEN.emoji in update
        assert PRStatus.READY_FOR_REVIEW.emoji in update

    def test_thread_update_no_old_status(self):
        pr = self._make_pr(PRStatus.OPEN)
        update = pr.to_thread_update()
        assert PRStatus.OPEN.emoji in update


class TestDeploymentMessage:
    def test_has_hyperlinks(self):
        m = GitHubDeploymentMessage(
            repo="org/repo",
            environment="production",
            state="success",
            creator="alice",
            sha="abc12345678",
            ref="main",
            url="https://github.com/org/repo/deployments",
        )
        rendered = m.to_structured().render()
        assert "production" in rendered
        assert "[org/repo](https://github.com/org/repo)" in rendered
        assert "[abc12345](https://github.com/org/repo/commit/abc12345678)" in rendered
        assert "[main](https://github.com/org/repo/tree/main)" in rendered
        assert "[alice](https://github.com/alice)" in rendered


class TestGenericMessages:
    def test_alert(self):
        m = GenericAlertMessage(
            source="vm-prod",
            title="Disk usage high",
            severity=Severity.WARNING,
            details="90% used on /data",
            fields={"Host": "vm-prod-01"},
            url="https://monitor.example.com/alert/1",
        )
        rendered = m.to_structured().render()
        assert "Disk usage high" in rendered
        assert "vm-prod" in rendered
        assert "90%" in rendered

    def test_deploy_no_backticks(self):
        m = GenericDeployMessage(
            source="api-service",
            environment="production",
            version="2.3.1",
            status="succeeded",
            actor="deployer",
            changelog=["Fixed login", "Added caching"],
        )
        rendered = m.to_structured().render()
        assert "2.3.1" in rendered
        assert "`2.3.1`" not in rendered
        assert "production" in rendered
        assert "Fixed login" in rendered
