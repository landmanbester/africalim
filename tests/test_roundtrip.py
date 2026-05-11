"""Round-trip tests: ``cli/X.py`` ↔ ``cabs/X.yml``.

For every ``src/africalim/cli/X.py`` (auto-discovered, except
``__init__.py``) we assert that:

1. ``hip_cargo.core.generate_cabs.generate_cabs`` produces
   ``src/africalim/cabs/<name>.yml``.
2. ``hip_cargo.core.generate_function.generate_function`` reads that
   cab and emits a Python source file.
3. After ruff-formatting both with ``pyproject.toml``, the generated
   source is byte-identical to the on-disk ``cli/<name>.py``.

This mirrors ``hip-cargo/tests/test_roundtrip.py`` and is the
load-bearing invariant the canonical CLI shape (see
``plans/hip_refactor.md`` §3) is designed around.

``cli/__init__.py`` is intentionally exempt: it's wiring (Typer subapp
mounting, command-name translation), not a cab target.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

CLI_DIR = Path("src/africalim/cli")
PROJECT_PYPROJECT = Path("pyproject.toml")

# Auto-discovered from `src/africalim/cli/*.py`. Adding a new command
# is therefore literally just adding the file — no test list to keep
# in sync. `__init__.py` is the wiring file and is exempt.
ROUNDTRIP_TARGETS: list[str] = sorted(p.stem for p in CLI_DIR.glob("*.py") if p.name != "__init__.py")


def _run_roundtrip(name: str) -> None:
    """Run the generate-cabs → generate-function loop for ``name`` and
    assert byte-identity after ruff format.

    Implementation lifted (with minor adjustments for the africalim
    layout) from ``hip-cargo/tests/test_roundtrip.py``.
    """
    from hip_cargo.core.generate_cabs import generate_cabs
    from hip_cargo.core.generate_function import generate_function

    cli_module = CLI_DIR / f"{name}.py"
    assert cli_module.exists(), f"missing CLI source: {cli_module}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        cab_dir = tmp / "cabs"
        cab_dir.mkdir()

        generate_cabs([cli_module], output_dir=cab_dir)

        cab_file = cab_dir / f"{name}.yml"
        assert cab_file.exists(), f"cab file not generated: {cab_file}"

        generated_file = tmp / f"{name}_roundtrip.py"
        generate_function(
            cab_file,
            output_file=generated_file,
            config_file=PROJECT_PYPROJECT,
        )

        assert generated_file.exists(), f"generated function not written: {generated_file}"
        generated_code = generated_file.read_text()

        # Sanity: generated source must compile.
        compile(generated_code, str(generated_file), "exec")

        original_code = cli_module.read_text()
        original_lines = original_code.splitlines()
        generated_lines = generated_code.splitlines()

        assert len(original_lines) == len(generated_lines), (
            f"line count mismatch for {name}: original={len(original_lines)}, generated={len(generated_lines)}"
        )
        for i, (orig, gen) in enumerate(zip(original_lines, generated_lines), 1):
            assert orig == gen, f"line {i} of {name} differs:\n  Original:  {orig}\n  Generated: {gen}"


@pytest.mark.parametrize("name", ROUNDTRIP_TARGETS)
def test_cli_roundtrip(name: str) -> None:
    """Round-trip ``cli/<name>.py`` through cab and back."""
    _run_roundtrip(name)


_INFO_HELP_PATTERN = re.compile(
    r"""(?:help|info)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
)
_BAD_SPACING = re.compile(r"\.[^\s\n]")


def test_help_strings_have_proper_spacing() -> None:
    """Every ``info=``/``help=`` literal must have a space after every period.

    Mirrors hip-cargo's ``test_roundtrip_preserves_spacing``. Catches
    things like ``"e.g.foo"`` or ``"sentence one.sentence two"`` that
    would survive Python parsing but break the cab YAML's sentence
    splitter, in turn breaking round-trip.
    """
    violations: list[str] = []
    for cli_file in sorted(CLI_DIR.glob("*.py")):
        if cli_file.name == "__init__.py":
            continue
        src = cli_file.read_text()
        for match in _INFO_HELP_PATTERN.finditer(src):
            for literal in match.groups():
                if not literal:
                    continue
                bad = _BAD_SPACING.search(literal)
                if bad is not None:
                    violations.append(
                        f"{cli_file.name}: {literal!r} contains period-followed-by-non-space at offset {bad.start()}",
                    )
    assert not violations, "\n".join(violations)
