from dataclasses import dataclass

from pydantic import model_validator
from pydantic_settings import BaseSettings

DEFAULT_GITHUB_AVATAR = (
    "https://raw.githubusercontent.com/Misery7100/pachca-bot/main/images/github-bot.png"
)
DEFAULT_GENERIC_AVATAR = (
    "https://raw.githubusercontent.com/Misery7100/pachca-bot/main/images/events-bot.png"
)
DEFAULT_GITHUB_BOT_NAME = "GitHub Bot"
DEFAULT_GENERIC_BOT_NAME = "Events Bot"


class Settings(BaseSettings):
    pachca_access_token: str
    pachca_chat_id: int | None = None  # Fallback when integration-specific ID not set
    pachca_bot_user_id: int | None = None

    github_pachca_chat_id: int | None = None
    generic_pachca_chat_id: int | None = None

    github_webhook_secret: str = ""
    generic_webhook_secret: str = ""

    github_bot_display_name: str = DEFAULT_GITHUB_BOT_NAME
    generic_bot_display_name: str = DEFAULT_GENERIC_BOT_NAME

    github_bot_display_avatar_url: str | None = None
    generic_bot_display_avatar_url: str | None = None

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    model_config = {"env_prefix": "", "case_sensitive": False}

    @model_validator(mode="after")
    def _require_chat_id(self) -> "Settings":
        if not any(
            (
                self.pachca_chat_id,
                self.github_pachca_chat_id,
                self.generic_pachca_chat_id,
            )
        ):
            raise ValueError(
                "At least one of PACHCA_CHAT_ID, GITHUB_PACHCA_CHAT_ID, "
                "or GENERIC_PACHCA_CHAT_ID must be set"
            )
        return self

    def has_github_chat(self) -> bool:
        return (self.github_pachca_chat_id or self.pachca_chat_id) is not None

    def has_generic_chat(self) -> bool:
        return (self.generic_pachca_chat_id or self.pachca_chat_id) is not None

    def get_github_chat_id(self) -> int:
        chat_id = self.github_pachca_chat_id or self.pachca_chat_id
        if chat_id is None:
            raise ValueError(
                "GITHUB_PACHCA_CHAT_ID or PACHCA_CHAT_ID required for GitHub integration"
            )
        return chat_id

    def get_generic_chat_id(self) -> int:
        chat_id = self.generic_pachca_chat_id or self.pachca_chat_id
        if chat_id is None:
            raise ValueError(
                "GENERIC_PACHCA_CHAT_ID or PACHCA_CHAT_ID required for generic integration"
            )
        return chat_id

    def get_github_avatar_url(self) -> str:
        return self.github_bot_display_avatar_url or DEFAULT_GITHUB_AVATAR

    def get_generic_avatar_url(self) -> str:
        return self.generic_bot_display_avatar_url or DEFAULT_GENERIC_AVATAR

    def github_integration(self) -> "IntegrationConfig | None":
        if not self.has_github_chat():
            return None
        return IntegrationConfig(
            chat_id=self.get_github_chat_id(),
            display_name=self.github_bot_display_name,
            display_avatar_url=self.get_github_avatar_url(),
        )

    def generic_integration(self) -> "IntegrationConfig | None":
        if not self.has_generic_chat():
            return None
        return IntegrationConfig(
            chat_id=self.get_generic_chat_id(),
            display_name=self.generic_bot_display_name,
            display_avatar_url=self.get_generic_avatar_url(),
        )


@dataclass(frozen=True)
class IntegrationConfig:
    """Per-integration settings for chat ID, display name, and avatar."""

    chat_id: int
    display_name: str
    display_avatar_url: str


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
