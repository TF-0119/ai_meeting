"""Shared default values for backend components."""

DEFAULT_AGENT_NAMES = ["Alice", "Bob", "Carol"]
"""List of default agent display names used across the project."""

DEFAULT_AGENT_STRING = " ".join(DEFAULT_AGENT_NAMES)
"""Whitespace separated default agents for text inputs and CLI passthrough."""

__all__ = ["DEFAULT_AGENT_NAMES", "DEFAULT_AGENT_STRING"]
