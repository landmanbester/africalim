from typing import Annotated, Literal

import typer
from hip_cargo import StimelaMeta, stimela_cab


@stimela_cab(
    name="config_set",
    info="Update a single user-config value.",
)
def config_set(
    key: Annotated[
        str,
        typer.Option(
            ...,
            help="Dotted config key (section + field).",
        ),
    ],
    value: Annotated[
        str,
        typer.Option(
            ...,
            help="Value to assign, validated against the schema.",
        ),
    ],
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
    Update a single user-config value.
    """
    if backend == "native" or backend == "auto":
        try:
            # Pre-flight must_exist for remote URIs before dispatching.
            from hip_cargo.utils.runner import preflight_remote_must_exist  # noqa: E402

            preflight_remote_must_exist(
                config_set,
                dict(
                    key=key,
                    value=value,
                ),
            )

            # Lazy import the core implementation
            from africalim.core.config_set import config_set as config_set_core  # noqa: E402

            # Call the core function with all parameters
            config_set_core(
                key,
                value,
            )
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
        config_set,
        dict(
            key=key,
            value=value,
        ),
        image=image,
        backend=backend,
        always_pull_images=always_pull_images,
    )
