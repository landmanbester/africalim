from typing import Annotated, Literal

import typer
from hip_cargo import StimelaMeta, stimela_cab


@stimela_cab(
    name="janskie",
    info="Ask janskie a question about radio interferometry tooling.",
)
def janskie(
    question: Annotated[
        str,
        typer.Option(
            ...,
            help="Question to ask janskie",
        ),
    ],
    provider: Annotated[
        str | None,
        typer.Option(
            help="LLM provider override (for example anthropic or openai).",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            help="Model name override within the provider.",
        ),
    ] = None,
    no_log: Annotated[
        bool,
        typer.Option(
            help="Skip logging this interaction.",
        ),
    ] = False,
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
    Ask janskie a question about radio interferometry tooling.
    """
    if backend == "native" or backend == "auto":
        try:
            # Pre-flight must_exist for remote URIs before dispatching.
            from hip_cargo.utils.runner import preflight_remote_must_exist  # noqa: E402

            preflight_remote_must_exist(
                janskie,
                dict(
                    question=question,
                    provider=provider,
                    model=model,
                    no_log=no_log,
                ),
            )

            # Lazy import the core implementation
            from africalim.core.janskie import janskie as janskie_core  # noqa: E402

            # Call the core function with all parameters
            janskie_core(
                question,
                provider=provider,
                model=model,
                no_log=no_log,
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
        janskie,
        dict(
            question=question,
            provider=provider,
            model=model,
            no_log=no_log,
        ),
        image=image,
        backend=backend,
        always_pull_images=always_pull_images,
    )
