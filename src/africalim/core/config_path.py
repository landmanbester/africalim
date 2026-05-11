"""Implementation backing ``africalim config path``.

Prints the path of the user-config file (whether or not it exists).
"""

from __future__ import annotations

from africalim.utils.user_config import default_user_config_path


def config_path() -> None:
    """Print the path of the user-config file."""
    print(default_user_config_path())
