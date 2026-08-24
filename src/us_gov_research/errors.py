"""Domain exceptions with intentionally redacted messages."""


class ResearchAgentError(Exception):
    """Base exception for safe, user-facing failures."""


class ConfigurationError(ResearchAgentError):
    """Raised when required environment configuration is missing or unsafe."""


class SourceError(ResearchAgentError):
    """Raised when an official source cannot satisfy a request."""

    def __init__(self, source: str, message: str, *, retryable: bool = False) -> None:
        self.source = source
        self.retryable = retryable
        super().__init__(f"{source}: {message}")


class BudgetExceeded(ResearchAgentError):
    """Raised before a configured request budget can be exceeded."""


class CitationValidationError(ResearchAgentError):
    """Raised when synthesis cites missing or non-official evidence."""
