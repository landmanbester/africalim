from typing import Annotated, Literal

import typer
from hip_cargo import StimelaMeta, stimela_cab


@stimela_cab(
    name="config_show",
    info="Print the current user config as TOML.",
)
def config_show(
    backend: Annotated[
        Literal["auto", "native", "apptainer", "singularity", "docker", "podman"],
        typer.Option(
            help="Execution backend.",
        ),
        StimelaMeta(
            skip=True,
        ),
    ] = "auto",
    always_pull_images: Annotated[
        bool,
        typer.Option(
            help="Always pull container images, even if cached locally.",
        ),
        StimelaMeta(
            skip=True,
        ),
    ] = False,
):
    """
    Print the current user config as TOML.
    """
    if backend == "native" or backend == "auto":
        try:
            # Pre-flight must_exist for remote URIs before dispatching.
            from hip_cargo.utils.runner import preflight_remote_must_exist  # noqa: E402

            preflight_remote_must_exist(
                config_show,
                dict(),
            )

            # Lazy import the core implementation
            from africalim.core.config_show import config_show as config_show_core  # noqa: E402

            # Call the core function with all parameters
            config_show_core()
            return
        except ImportError:
            if backend == "native":
                raise

    # Resolve container image from installed package metadata
    from hip_cargo.utils.config import get_container_image  # noqa: E402
    from hip_cargo.utils.runner import run_in_container  # noqa: E402

    image = get_container_image("africalim")
    if image is None:
        raise RuntimeError("No Container URL in africalim metadata.")

    run_in_container(
        config_show,
        dict(),
        image=image,
        backend=backend,
        always_pull_images=always_pull_images,
    )
