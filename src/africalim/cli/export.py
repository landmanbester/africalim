from pathlib import Path
from typing import Annotated, Literal, NewType

import typer
from hip_cargo import StimelaMeta, parse_upath, stimela_cab

File = NewType("File", Path)


@stimela_cab(
    name="export",
    info="Export logged interactions as JSONL.",
)
def export(
    output: Annotated[
        File | None,
        typer.Option(
            parser=parse_upath,
            help="JSONL output file (stdout if omitted).",
        ),
    ] = None,
    consent: Annotated[
        str,
        typer.Option(
            help="Consent filter: opt_in (default), opt_out, unset, all.",
        ),
    ] = "opt_in",
    agent: Annotated[
        str | None,
        typer.Option(
            help="Filter by agent name.",
        ),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option(
            help="ISO 8601 inclusive lower bound on timestamp.",
        ),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option(
            help="ISO 8601 inclusive upper bound on timestamp.",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            help="Max records to read from the log before filtering.",
        ),
    ] = 10000,
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
    Export logged interactions as JSONL.
    """
    if backend == "native" or backend == "auto":
        try:
            # Pre-flight must_exist for remote URIs before dispatching.
            from hip_cargo.utils.runner import preflight_remote_must_exist  # noqa: E402

            preflight_remote_must_exist(
                export,
                dict(
                    output=output,
                    consent=consent,
                    agent=agent,
                    since=since,
                    until=until,
                    limit=limit,
                ),
            )

            # Lazy import the core implementation
            from africalim.core.export import export as export_core  # noqa: E402

            # Call the core function with all parameters
            export_core(
                output=output,
                consent=consent,
                agent=agent,
                since=since,
                until=until,
                limit=limit,
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
        export,
        dict(
            output=output,
            consent=consent,
            agent=agent,
            since=since,
            until=until,
            limit=limit,
        ),
        image=image,
        backend=backend,
        always_pull_images=always_pull_images,
    )
