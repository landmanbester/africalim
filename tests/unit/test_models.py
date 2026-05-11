"""Unit tests for ``africalim.utils.models``.

Sync tests (no asyncio). Each test isolates the environment via
``monkeypatch.setenv`` / ``monkeypatch.delenv`` so cases never see one
another's state.
"""

from __future__ import annotations

import pytest

from africalim.utils.models import (
    DEFAULT_MODEL_NAME,
    DEFAULT_PROVIDER,
    PROVIDER_ENV_VARS,
    MissingAPIKeyError,
    build_model,
)


def _clear_africalim_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the AFRICALIM_* env vars so they don't bleed in from the host."""
    monkeypatch.delenv("AFRICALIM_PROVIDER", raising=False)
    monkeypatch.delenv("AFRICALIM_MODEL", raising=False)


def _clear_provider_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every API-key env var the module knows about."""
    for var in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------------------- #
# Defaults / resolution order
# --------------------------------------------------------------------------- #


def test_default_provider_and_model_when_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no overrides the factory picks anthropic + claude-sonnet-4-6."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    identifier = build_model()

    assert identifier == f"{DEFAULT_PROVIDER}:{DEFAULT_MODEL_NAME}"
    assert DEFAULT_PROVIDER == "anthropic"
    assert DEFAULT_MODEL_NAME == "claude-sonnet-4-6"


def test_returns_provider_colon_model_string_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """The factory's return value is always ``"<provider>:<model>"``."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    identifier = build_model(provider="openai", model_name="gpt-4o-mini")

    assert isinstance(identifier, str)
    assert identifier == "openai:gpt-4o-mini"
    assert identifier.count(":") == 1


def test_explicit_args_win_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit ``provider`` / ``model_name`` beat AFRICALIM_* env vars."""
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("AFRICALIM_PROVIDER", "openai")
    monkeypatch.setenv("AFRICALIM_MODEL", "gpt-4o")
    monkeypatch.setenv("GROQ_API_KEY", "k")

    identifier = build_model(provider="groq", model_name="llama-3.1-70b")

    assert identifier == "groq:llama-3.1-70b"


def test_env_wins_over_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """AFRICALIM_* env vars beat user_config defaults."""
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("AFRICALIM_PROVIDER", "openrouter")
    monkeypatch.setenv("AFRICALIM_MODEL", "anthropic/claude-3.5-sonnet")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    user_config = {"model": {"default_provider": "openai", "default_model": "gpt-4o"}}

    identifier = build_model(user_config=user_config)

    assert identifier == "openrouter:anthropic/claude-3.5-sonnet"


def test_user_config_wins_over_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """user_config overrides hard-coded defaults when env is unset."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    user_config = {"model": {"default_provider": "openai", "default_model": "gpt-4o"}}

    identifier = build_model(user_config=user_config)

    assert identifier == "openai:gpt-4o"


def test_user_config_partial_provider_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting only the provider in user_config falls through to default model."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    user_config = {"model": {"default_provider": "openai"}}

    identifier = build_model(user_config=user_config)

    assert identifier == f"openai:{DEFAULT_MODEL_NAME}"


def test_user_config_with_no_model_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """A user_config without a ``[model]`` section is treated as no override."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    user_config: dict[str, object] = {"unrelated": {"foo": "bar"}}

    identifier = build_model(user_config=user_config)

    assert identifier == f"{DEFAULT_PROVIDER}:{DEFAULT_MODEL_NAME}"


def test_user_config_non_dict_model_section_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-dict ``[model]`` value is ignored without raising."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    user_config: dict[str, object] = {"model": "not-a-mapping"}

    identifier = build_model(user_config=user_config)

    assert identifier == f"{DEFAULT_PROVIDER}:{DEFAULT_MODEL_NAME}"


def test_user_config_non_string_default_provider_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-string ``default_provider`` falls through rather than raising."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    user_config: dict[str, object] = {"model": {"default_provider": 42}}

    identifier = build_model(user_config=user_config)

    assert identifier == f"{DEFAULT_PROVIDER}:{DEFAULT_MODEL_NAME}"


def test_user_config_empty_string_default_provider_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty-string overrides are treated as absent."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    user_config: dict[str, object] = {"model": {"default_provider": "", "default_model": ""}}

    identifier = build_model(user_config=user_config)

    assert identifier == f"{DEFAULT_PROVIDER}:{DEFAULT_MODEL_NAME}"


def test_none_user_config_treated_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passing ``user_config=None`` is fine and equivalent to omitting it."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    identifier = build_model(user_config=None)

    assert identifier == f"{DEFAULT_PROVIDER}:{DEFAULT_MODEL_NAME}"


# --------------------------------------------------------------------------- #
# Missing-API-key behaviour
# --------------------------------------------------------------------------- #


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the resolved provider's env var is unset, raise."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)

    with pytest.raises(MissingAPIKeyError):
        build_model()


def test_missing_api_key_message_lists_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error message lists every supported provider + env var."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)

    with pytest.raises(MissingAPIKeyError) as exc_info:
        build_model()
    message = str(exc_info.value)

    for provider, env_var in PROVIDER_ENV_VARS.items():
        assert provider in message
        assert env_var in message
    assert "api_key_env" in message


def test_missing_api_key_message_names_resolved_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error mentions the specific provider that failed to resolve."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)

    with pytest.raises(MissingAPIKeyError) as exc_info:
        build_model(provider="groq", model_name="llama-3.1-70b")

    assert "groq" in str(exc_info.value)


def test_unknown_provider_raises_with_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider that has no env-var mapping still raises a clear error."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)

    with pytest.raises(MissingAPIKeyError) as exc_info:
        build_model(provider="not-a-real-provider", model_name="x")

    message = str(exc_info.value)
    assert "not-a-real-provider" in message
    # Even unknown-provider errors list the known providers so the user
    # can see what they could have meant.
    for provider in PROVIDER_ENV_VARS:
        assert provider in message


# --------------------------------------------------------------------------- #
# api_key_env override
# --------------------------------------------------------------------------- #


def test_api_key_env_override_uses_custom_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """``api_key_env`` redirects which env var must be set."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("MY_VAULT_VAR", "secret")

    identifier = build_model(provider="anthropic", model_name="claude-sonnet-4-6", api_key_env="MY_VAULT_VAR")

    assert identifier == "anthropic:claude-sonnet-4-6"


def test_api_key_env_override_unset_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the override var is unset, the error still fires."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.delenv("MY_VAULT_VAR", raising=False)
    # Even if the default ANTHROPIC_API_KEY were present, the override wins.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ignored")

    with pytest.raises(MissingAPIKeyError) as exc_info:
        build_model(provider="anthropic", api_key_env="MY_VAULT_VAR")

    assert "MY_VAULT_VAR" in str(exc_info.value)


def test_api_key_env_override_works_for_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom api_key_env unlocks providers not in PROVIDER_ENV_VARS."""
    _clear_africalim_env(monkeypatch)
    _clear_provider_env_vars(monkeypatch)
    monkeypatch.setenv("CUSTOM_KEY", "secret")

    identifier = build_model(
        provider="custom-provider",
        model_name="custom-model",
        api_key_env="CUSTOM_KEY",
    )

    assert identifier == "custom-provider:custom-model"
