"""Implementation backing ``africalim config show``.

Loads the user config from the platform-default path and prints it as
canonical TOML. Pure Python — no Typer dependency — so the same
function services both the runtime CLI and direct Stimela cab calls.
"""

from __future__ import annotations

import io

import tomli_w

from africalim.utils.user_config import default_user_config_path, load_user_config


def config_show() -> None:
    """Print the current user config as TOML."""
    config = load_user_config(default_user_config_path())
    payload = config.model_dump(mode="python")
    buf = io.BytesIO()
    tomli_w.dump(payload, buf)
    print(buf.getvalue().decode("utf-8"), end="")
