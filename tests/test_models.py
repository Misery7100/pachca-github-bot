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
    Severity,
    StructuredMessage,
    TextBlock,
    patch_status_in_content,
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

    def test_list_block_unordered(self):
        assert "• a" in ListBlock(items=["a", "b"]).render()

    def test_list_block_ordered(self):
        out = ListBlock(items=["a", "b"], ordered=True).render()
        assert "1. a" in out

    def test_divider(self):
        assert DividerBlock().render() == "---"

    def test_structured_message(self):
        msg = StructuredMessage()
        msg.add(HeaderBlock(text="Title"))
        msg.add(TextBlock(text="Body"))
        assert "# Title" in msg.render()


class TestStatusUpdate:
    def test_format_has_blank_line_and_bold(self):
        result = render_status_update("Draft", "Open")
        assert "Status updated:\n\n**Before:** Draft\n**After:** Open" == result


class TestPatchStatus:
    def test_replaces_emoji_and_status_field(self):
        content = "## 📝 PR [#1](https://github.com/o/r/pull/1): Title\n\n**Status:** Draft"
        patched = patch_status_in_content(content, "🟣", "Merged")
        assert patched.startswith("## 🟣 ")
        assert "📝" not in patched
        assert "**Status:** Merged" in patched
        assert "Draft" not in patched


class TestReleaseMessage:
    def test_no_tag_field_view_release_link(self):
        m = GitHubReleaseMessage(
            repo="org/repo",
            tag="v1.0.0",
            release_name="Release 1.0",
            author="alice",
            url="https://github.com/org/repo/releases/tag/v1.0.0",
            body="- Fixed auth\n- Added caching",
        )
        rendered = m.to_structured().render()
        assert "🔖 Release:" in rendered
        assert "[v1.0.0](" in rendered
        assert "**Tag:**" not in rendered
        assert "**Release:**" not in rendered
        assert "[View release](" in rendered
        assert "[alice](https://github.com/alice)" in rendered
        assert "- Fixed auth" in rendered
        assert "> " not in rendered

    def test_prerelease(self):
        m = GitHubReleaseMessage(
            repo="o/r",
            tag="v2-rc1",
            release_name="RC1",
            author="b",
            url="https://github.com/o/r/releases/tag/v2-rc1",
            prerelease=True,
        )
        assert "pre-release" in m.to_structured().render()


class TestCIMessage:
    def test_channel_has_repo(self):
        m = GitHubCIMessage(
            workflow_name="CI",
            commit_sha="abc12345678",
            repo="org/repo",
            conclusion="failure",
            url="https://github.com/org/repo/actions/runs/1",
        )
        rendered = m.to_structured().render()
        assert "[org/repo](" in rendered
        assert "**Triggered by:**" not in rendered

    def test_pr_thread_no_repo(self):
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
        rendered = self._make_pr().to_parent()
        assert "[#42](https://github.com/org/repo/pull/42)" in rendered
        assert "[org/repo](https://github.com/org/repo)" in rendered
        assert "[alice](https://github.com/alice)" in rendered
        assert "[fix-bug](" in rendered
        assert "[main](" in rendered
        assert "→" in rendered

    def test_parent_status_field_plain_text(self):
        rendered = self._make_pr(PRStatus.OPEN).to_parent()
        assert "**Status:** Open" in rendered
        assert "**Status:** 🆕" not in rendered

    def test_parent_emoji_only_in_header(self):
        rendered = self._make_pr(PRStatus.MERGED).to_parent()
        assert "## 🟣 PR" in rendered
        assert "**Status:** Merged" in rendered

    def test_thread_update_format(self):
        pr = self._make_pr(PRStatus.READY_FOR_REVIEW)
        update = pr.to_thread_update(old_status=PRStatus.OPEN)
        assert "Status updated:\n\n**Before:** Open\n**After:** Ready for review" == update

    def test_patch_preserves_content(self):
        pr = self._make_pr(PRStatus.OPEN)
        original = pr.to_parent()
        patched = GitHubPRMessage.patch_parent_status(original, PRStatus.MERGED)
        assert "## 🟣 " in patched
        assert "🆕" not in patched
        assert "**Status:** Merged" in patched
        assert "[alice](" in patched
        assert "[fix-bug](" in patched
        assert "Fix bug" in patched


class TestGenericAlert:
    def test_source_as_field(self):
        m = GenericAlertMessage(
            source="monitoring",
            title="Disk usage high",
            severity=Severity.WARNING,
            fields={"Host": "vm-01"},
        )
        rendered = m.to_structured().render()
        assert "**Source:** monitoring" in rendered
        assert "Disk usage high" in rendered


class TestGenericDeploy:
    def test_format(self):
        m = GenericDeployMessage(
            source="api",
            environment="production",
            version="2.3.1",
            status=DeployStatus.STARTED,
            deploy_id="dep-42",
            actor="deployer",
        )
        rendered = m.to_parent()
        assert "## 🚀 Deployment: api" in rendered
        assert "**ID:** dep-42" in rendered
        assert "**Status:** Started" in rendered
        assert "**Deployed by:** deployer" in rendered
        lines = rendered.split("\n")
        field_lines = [line for line in lines if line.startswith("**")]
        id_idx = next(i for i, fl in enumerate(field_lines) if "**ID:**" in fl)
        deploy_idx = next(i for i, fl in enumerate(field_lines) if "**Deployed by:**" in fl)
        assert deploy_idx > id_idx

    def test_without_id(self):
        m = GenericDeployMessage(
            source="api",
            environment="prod",
            version="1.0",
            status=DeployStatus.STARTED,
        )
        assert "**ID:**" not in m.to_parent()

    def test_thread_update(self):
        m = GenericDeployMessage(
            source="api",
            environment="prod",
            version="1.0",
            status=DeployStatus.SUCCEEDED,
        )
        update = m.to_thread_update(DeployStatus.STARTED)
        assert "Status updated:\n\n**Before:** Started\n**After:** Succeeded" == update

    def test_patch_parent_status(self):
        m = GenericDeployMessage(
            source="api",
            environment="prod",
            version="1.0",
            status=DeployStatus.STARTED,
        )
        original = m.to_parent()
        patched = GenericDeployMessage.patch_parent_status(original, DeployStatus.SUCCEEDED)
        assert "## ✅ " in patched
        assert "🚀" not in patched
        assert "**Status:** Succeeded" in patched
        assert "api" in patched
