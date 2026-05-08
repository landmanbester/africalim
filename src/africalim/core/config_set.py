"""Implementation backing ``africalim config set``.

Updates a single dotted-key/value pair in the user-config TOML on
disk, validating the result against :class:`UserConfig`. Raises
:class:`UnknownConfigKeyError` / :class:`InvalidConfigValueError` from
:mod:`africalim.utils.user_config` on bad input — the CLI wrapper at
:mod:`africalim.cli.config_set` catches those and converts to a
typer-friendly exit code.
"""

from __future__ import annotations

from africalim.utils.user_config import default_user_config_path, set_dotted


def config_set(key: str, value: str) -> None:
    """Set ``key = value`` in the user config (dotted ``section.field``)."""
    set_dotted(default_user_config_path(), key, value)
