"""Domain errors. Each one maps to a safe, specific outcome; none are swallowed silently."""


class AgentError(Exception):
    """Base class for errors raised inside the agent service."""


class ProviderUnavailable(AgentError):
    """The LLM provider could not be reached after bounded retries."""


class ToolNotFound(AgentError):
    """The model asked for a tool that is not in the registry."""


class ToolArgumentsInvalid(AgentError):
    """The model sent arguments that fail the tool's schema."""


class ToolDisabled(AgentError):
    """The tool exists but is switched off server-side."""


class WhatsAppSendFailed(AgentError):
    """The reply could not be delivered to the WhatsApp Cloud API."""


class InvalidSignature(AgentError):
    """The webhook body was not signed with the Meta App Secret."""
