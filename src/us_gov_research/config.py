"""Environment-only application configuration."""

from __future__ import annotations

import re

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfigurationError

CONTACT_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
UNMONITORED_MAILBOX = re.compile(r"^(?:no[._-]?reply|do[._-]?not[._-]?reply)$", re.IGNORECASE)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local ignored `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_model: str = "openai-responses:gpt-5.6-luna"
    openai_api_key: SecretStr | None = None
    data_gov_api_key: SecretStr | None = None
    sec_user_agent: str = ""

    agent_max_tool_calls: int = Field(default=8, ge=1, le=20)
    agent_max_model_requests: int = Field(default=6, ge=2, le=20)
    agent_max_http_requests: int = Field(default=20, ge=1, le=100)
    agent_max_input_tokens: int = Field(default=20_000, ge=1_000, le=500_000)
    agent_max_output_tokens: int = Field(default=10_000, ge=500, le=100_000)
    agent_max_response_tokens: int = Field(default=2_000, ge=100, le=32_000)

    @field_validator("llm_model")
    @classmethod
    def require_provider_prefix(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("LLM_MODEL must use the provider:model form")
        return value

    def validate_for_question(self) -> None:
        provider = self.llm_model.split(":", 1)[0]
        if provider.startswith("openai") and self.openai_api_key is None:
            raise ConfigurationError(
                "OPENAI_API_KEY is required for the default OpenAI model. "
                "Copy .env.example to .env and add your own key."
            )
        self.validate_sec_user_agent()

    def validate_sec_user_agent(self) -> None:
        """Require a descriptive SEC identity only when an SEC call is made."""

        match = CONTACT_EMAIL.search(self.sec_user_agent)
        identity = CONTACT_EMAIL.sub("", self.sec_user_agent).strip(" ()[]<>-–—,;")
        email = match.group(0) if match else ""
        mailbox, _, domain = email.partition("@")
        if (
            not match
            or not re.search(r"[A-Za-z]{2}", identity)
            or "example.com" in self.sec_user_agent.lower()
            or UNMONITORED_MAILBOX.fullmatch(mailbox)
            or "noreply" in domain.lower()
        ):
            raise ConfigurationError(
                "SEC_USER_AGENT must identify a real person or organization and include a "
                "monitored contact email; placeholder and noreply addresses are not accepted."
            )

    def require_data_gov_key(self, source: str) -> str:
        if self.data_gov_api_key is None:
            raise ConfigurationError(
                f"DATA_GOV_API_KEY is required for {source}; obtain one free at "
                "https://api.data.gov/signup/."
            )
        return self.data_gov_api_key.get_secret_value()


def load_settings() -> Settings:
    """Load `.env` into the process so provider SDKs can use conventional variables."""

    load_dotenv(override=False)
    return Settings()
