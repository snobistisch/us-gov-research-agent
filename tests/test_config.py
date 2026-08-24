from __future__ import annotations

import pytest

from us_gov_research.config import Settings
from us_gov_research.errors import ConfigurationError


def test_sec_user_agent_accepts_descriptive_monitored_contact() -> None:
    settings = Settings(
        _env_file=None,
        sec_user_agent="Public Policy Lab research@valid.test",
    )

    settings.validate_sec_user_agent()


@pytest.mark.parametrize(
    "user_agent",
    [
        "Public Policy Lab noreply@valid.test",
        "Public Policy Lab no-reply@valid.test",
        "Public Policy Lab do.not.reply@valid.test",
        "Public Policy Lab contributor@users.noreply.github.com",
        "Public Policy Lab research@example.com",
        "research@valid.test",
        "Mozilla/5.0",
    ],
)
def test_sec_user_agent_rejects_unmonitored_or_undescriptive_identity(
    user_agent: str,
) -> None:
    settings = Settings(_env_file=None, sec_user_agent=user_agent)

    with pytest.raises(ConfigurationError, match="monitored contact email"):
        settings.validate_sec_user_agent()
