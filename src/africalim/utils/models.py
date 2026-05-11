"""Harness layer — pydantic-ai model identifier factory.

This module owns resolution of *which* LLM a given agent run will use. It
does **not** instantiate a ``pydantic_ai.models.Model`` directly; instead
:func:`build_model` returns the canonical pydantic-ai 1.x identifier
string ``"<provider>:<model_name>"`` which the caller passes to
``pydantic_ai.Agent(model=...)``. Pydantic-ai resolves that string lazily
at first request, which keeps unit tests using
``pydantic_ai.models.test.TestModel`` independent of real API keys.

Resolution order (highest precedence first):

1. Explicit ``provider`` / ``model_name`` arguments to :func:`build_model`.
2. Environment variables ``AFRICALIM_PROVIDER`` / ``AFRICALIM_MODEL``.
3. The user-config dict's ``[model]`` section
   (``default_provider`` / ``default_model``).
4. Hard-coded defaults: ``anthropic`` / ``claude-sonnet-4-6``.

API keys are **only** sourced from environment variables — never from the
user-config dict, since config files end up in dotfile repositories and
screenshots whereas env vars do not. If the env var for the resolved
provider is missing, :func:`build_model` raises
:class:`MissingAPIKeyError` with a multi-line message listing every
provider this module recognises and the env var each one expects.

The ``api_key_env`` keyword overrides the default env-var name for the
resolved provider so that callers can wire up enterprise key vaults or
rename variables for vendored installs without editing this module.
"""

from __future__ import annotations

import os
from typing import Any


class MissingAPIKeyError(RuntimeError):
    """Raised when the env var for the resolved provider is not set."""


# Mapping from pydantic-ai provider id to the canonical env-var name we
# consult for that provider's API key. Provider ids must match the strings
# pydantic-ai itself uses in its ``"<provider>:<model_name>"`` identifiers.
PROVIDER_ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google-gla": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
}


DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL_NAME = "claude-sonnet-4-6"


def _missing_key_message(provider: str, env_var: str | None) -> str:
    """Build the multi-line error message for a missing API key."""
    lines = [
        f"No API key found for provider {provider!r}.",
        "",
    ]
    if env_var is not None:
        lines.append(f"Expected environment variable: {env_var}")
    else:
        lines.append("No env var is registered for this provider.")
    lines.extend(
        [
            "",
            "Supported providers and their default env vars:",
        ]
    )
    for name, var in sorted(PROVIDER_ENV_VARS.items()):
        lines.append(f"  - {name}: {var}")
    lines.extend(
        [
            "",
            "Pass api_key_env=<NAME> to build_model() to override the default",
            "env var name for the resolved provider.",
        ]
    )
    return "\n".join(lines)


def _from_user_config(user_config: dict[str, Any] | None, key: str) -> str | None:
    """Pull ``user_config["model"][key]`` if present and a string, else None."""
    if not user_config:
        return None
    model_section = user_config.get("model")
    if not isinstance(model_section, dict):
        return None
    value = model_section.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def build_model(
    provider: str | None = None,
    model_name: str | None = None,
    user_config: dict[str, Any] | None = None,
    *,
    api_key_env: str | None = None,
) -> str:
    """Resolve a pydantic-ai model identifier.

    Resolution order (highest precedence first):

    1. Explicit ``provider`` / ``model_name`` arguments.
    2. Environment variables ``AFRICALIM_PROVIDER`` / ``AFRICALIM_MODEL``.
    3. ``user_config["model"]["default_provider"]`` / ``["default_model"]``.
    4. Defaults: anthropic / claude-sonnet-4-6.

    The function does *not* mint a Model instance — it returns the
    canonical ``"provider:model_name"`` string. The agent layer passes
    that to ``pydantic_ai.Agent(model=...)``, which performs lazy auth.

    Args:
        provider: Explicit pydantic-ai provider id (e.g. ``"anthropic"``).
        model_name: Explicit model name within that provider.
        user_config: Optional dict whose ``[model]`` section may carry
            ``default_provider`` / ``default_model`` keys. API keys are
            **never** read from this dict.
        api_key_env: Override the env-var name that is consulted for the
            resolved provider's API key.

    Returns:
        Canonical pydantic-ai model identifier ``"<provider>:<model>"``.

    Raises:
        MissingAPIKeyError: If the env var for the resolved provider is
            not set. The message lists every supported provider and the
            env var each one expects.
    """
    resolved_provider = (
        provider
        or os.environ.get("AFRICALIM_PROVIDER")
        or _from_user_config(user_config, "default_provider")
        or DEFAULT_PROVIDER
    )
    resolved_model = (
        model_name
        or os.environ.get("AFRICALIM_MODEL")
        or _from_user_config(user_config, "default_model")
        or DEFAULT_MODEL_NAME
    )

    env_var = api_key_env if api_key_env is not None else PROVIDER_ENV_VARS.get(resolved_provider)

    if env_var is None or not os.environ.get(env_var):
        raise MissingAPIKeyError(_missing_key_message(resolved_provider, env_var))

    return f"{resolved_provider}:{resolved_model}"
