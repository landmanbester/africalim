"""Implementation backing ``africalim config set``.

Updates a single dotted-key/value pair in the user-config TOML on
disk, validating the result against :class:`UserConfig`.

Owns the user-facing error reporting too: invalid input prints a clean
``Error: ...`` line to stderr and exits with code 1; the happy path
prints ``Set <key> = <value>`` to stdout. Putting this here (rather
than in ``cli/config_set.py``) lets the CLI wrapper stay pure
boilerplate and round-trip through the cab YAML.
"""

from __future__ import annotations

import sys

from africalim.utils.user_config import (
    InvalidConfigValueError,
    UnknownConfigKeyError,
    default_user_config_path,
    set_dotted,
)


def config_set(key: str, value: str) -> None:
    """Set ``key = value`` in the user config (dotted ``section.field``)."""
    try:
        set_dotted(default_user_config_path(), key, value)
    except (UnknownConfigKeyError, InvalidConfigValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Set {key} = {value}")
