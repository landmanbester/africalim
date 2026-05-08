"""CLI for africalim."""

import typer

app = typer.Typer(
    name="africalim",
    help="Radio astronomy tidbits",
    no_args_is_help=True,
)


@app.callback()
def callback() -> None:
    """Radio astronomy tidbits"""
    pass


# Register subcommands below. Imports go here (bottom) to avoid circular imports.
from africalim.cli.onboard import onboard  # noqa: E402

app.command(name="onboard")(onboard)

__all__ = ["app"]
