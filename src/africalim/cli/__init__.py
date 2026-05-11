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
from africalim.cli.janskie import janskie  # noqa: E402

app.command(name="janskie")(janskie)

from africalim.cli.export import export  # noqa: E402

app.command(name="export")(export)

# ``africalim config {show,set,path}`` is a Typer subgroup assembled from
# three sibling files so each cab gets its own one-to-one cli/core pair
# per the hip-cargo convention.
from africalim.cli.config_path import config_path  # noqa: E402
from africalim.cli.config_set import config_set  # noqa: E402
from africalim.cli.config_show import config_show  # noqa: E402

config_app = typer.Typer(
    name="config",
    help="View/edit africalim user config.",
    no_args_is_help=True,
)
config_app.command(name="show")(config_show)
config_app.command(name="set")(config_set)
config_app.command(name="path")(config_path)
app.add_typer(config_app, name="config")

__all__ = ["app"]
