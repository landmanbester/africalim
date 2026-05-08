"""Unit tests for ``africalim.utils.consent``.

Sync tests (no asyncio). Each test gets an isolated config path via
``tmp_path`` so cases never see one another's writes.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs
import pytest
import typer

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from africalim.utils import consent as consent_module
from africalim.utils.consent import ConsentManager, default_config_path
from africalim.utils.consent_text import (
    FIRST_RUN_PROMPT,
    LINK_TO_PRIVACY_MD,
    OPT_IN_CONFIRMATION,
    OPT_OUT_CONFIRMATION,
    PRIVACY_SUMMARY,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def _read_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


# --------------------------------------------------------------------------- #
# get_status / prompt_shown defaults
# --------------------------------------------------------------------------- #


def test_fresh_path_returns_unset_and_prompt_not_shown(tmp_path: Path) -> None:
    """A non-existent config file looks like an unset, unshown manager."""
    cm = ConsentManager(_config_path(tmp_path))
    assert cm.get_status() == "unset"
    assert cm.prompt_shown is False


def test_init_does_not_create_file(tmp_path: Path) -> None:
    """``__init__`` must not write to disk — that's set_status' job."""
    path = _config_path(tmp_path)
    ConsentManager(path)
    assert not path.exists()


def test_get_status_falls_back_when_value_unknown(tmp_path: Path) -> None:
    """A hand-edited bogus status should not raise; treat as unset."""
    path = _config_path(tmp_path)
    path.write_text('[consent]\nstatus = "weird"\nprompt_shown = true\n')
    cm = ConsentManager(path)
    assert cm.get_status() == "unset"


# --------------------------------------------------------------------------- #
# set_status persistence
# --------------------------------------------------------------------------- #


def test_set_status_persists_across_instances(tmp_path: Path) -> None:
    """A second ConsentManager on the same path sees the persisted value."""
    path = _config_path(tmp_path)
    ConsentManager(path).set_status("opt_in")

    fresh = ConsentManager(path)
    assert fresh.get_status() == "opt_in"
    assert fresh.prompt_shown is True


def test_set_status_writes_expected_toml(tmp_path: Path) -> None:
    """The on-disk shape matches the documented ``[consent]`` schema."""
    path = _config_path(tmp_path)
    ConsentManager(path).set_status("opt_out")

    data = _read_toml(path)
    assert data == {"consent": {"status": "opt_out", "prompt_shown": True}}


def test_set_status_rejects_unknown_value(tmp_path: Path) -> None:
    cm = ConsentManager(_config_path(tmp_path))
    with pytest.raises(ValueError):
        cm.set_status("maybe")  # type: ignore[arg-type]


def test_set_status_creates_parent_dirs(tmp_path: Path) -> None:
    """Nested config dirs are created on demand."""
    path = tmp_path / "deeply" / "nested" / "config.toml"
    ConsentManager(path).set_status("opt_in")
    assert path.is_file()


# --------------------------------------------------------------------------- #
# Round-trip preservation of unrelated config sections
# --------------------------------------------------------------------------- #


def test_set_status_preserves_other_sections(tmp_path: Path) -> None:
    """M5 will share the file; we must not clobber its sections."""
    path = _config_path(tmp_path)
    path.write_text('[other]\nfoo = "bar"\n\n[deep]\nx = 1\n')

    ConsentManager(path).set_status("opt_out")

    data = _read_toml(path)
    assert data["other"] == {"foo": "bar"}
    assert data["deep"] == {"x": 1}
    assert data["consent"] == {"status": "opt_out", "prompt_shown": True}


def test_set_status_replaces_corrupt_consent_section(tmp_path: Path) -> None:
    """If [consent] was somehow set to a non-table, we recover gracefully."""
    path = _config_path(tmp_path)
    # Pre-write a file whose top-level "consent" is a string, simulating a
    # corrupt manual edit. ``set_status`` should overwrite it without raising.
    path.write_text('consent = "garbled"\n[other]\nfoo = "bar"\n')

    ConsentManager(path).set_status("opt_in")

    data = _read_toml(path)
    assert data["consent"] == {"status": "opt_in", "prompt_shown": True}
    assert data["other"] == {"foo": "bar"}


# --------------------------------------------------------------------------- #
# first_run_prompt — interactive paths
# --------------------------------------------------------------------------- #


def test_first_run_prompt_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """User answers yes → status becomes opt_in and confirmation echoed."""
    path = _config_path(tmp_path)
    cm = ConsentManager(path)

    seen_prompts: list[str] = []

    def fake_confirm(text: str, default: bool = False) -> bool:
        seen_prompts.append(text)
        assert default is False, "first-run default must be opt-out"
        return True

    echoed: list[str] = []
    monkeypatch.setattr(consent_module.typer, "confirm", fake_confirm)
    monkeypatch.setattr(consent_module.typer, "echo", lambda msg: echoed.append(msg))

    result = cm.first_run_prompt()

    assert result == "opt_in"
    assert cm.get_status() == "opt_in"
    assert cm.prompt_shown is True
    assert seen_prompts == [FIRST_RUN_PROMPT]
    assert echoed == [OPT_IN_CONFIRMATION]


def test_first_run_prompt_opt_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """User answers no → status becomes opt_out and confirmation echoed."""
    path = _config_path(tmp_path)
    cm = ConsentManager(path)

    monkeypatch.setattr(consent_module.typer, "confirm", lambda text, default=False: False)

    echoed: list[str] = []
    monkeypatch.setattr(consent_module.typer, "echo", lambda msg: echoed.append(msg))

    result = cm.first_run_prompt()

    assert result == "opt_out"
    assert cm.get_status() == "opt_out"
    assert cm.prompt_shown is True
    assert echoed == [OPT_OUT_CONFIRMATION]


def test_first_run_prompt_short_circuits_when_already_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second call must not re-prompt; verified by raising in ``confirm``."""
    path = _config_path(tmp_path)
    cm = ConsentManager(path)

    # First run: opt_in.
    monkeypatch.setattr(consent_module.typer, "confirm", lambda text, default=False: True)
    monkeypatch.setattr(consent_module.typer, "echo", lambda msg: None)
    assert cm.first_run_prompt() == "opt_in"

    # Second run: ``confirm`` must never be called.
    def boom(*args: object, **kwargs: object) -> bool:
        raise AssertionError("confirm should not be called once prompt_shown is True")

    monkeypatch.setattr(consent_module.typer, "confirm", boom)

    assert cm.first_run_prompt() == "opt_in"
    assert cm.prompt_shown is True


def test_first_run_prompt_eof_keeps_state_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """typer.Abort (EOF / non-interactive) leaves the manager re-promptable."""
    path = _config_path(tmp_path)
    cm = ConsentManager(path)

    def aborting(*_args: object, **_kwargs: object) -> bool:
        raise typer.Abort()

    monkeypatch.setattr(consent_module.typer, "confirm", aborting)

    # First call: aborts, no state change.
    result = cm.first_run_prompt()
    assert result == "unset"
    assert cm.get_status() == "unset"
    assert cm.prompt_shown is False

    # Next run: switch to a real answer; it must prompt again.
    calls: list[str] = []

    def now_answers(text: str, default: bool = False) -> bool:
        calls.append(text)
        return False

    monkeypatch.setattr(consent_module.typer, "confirm", now_answers)
    monkeypatch.setattr(consent_module.typer, "echo", lambda msg: None)

    assert cm.first_run_prompt() == "opt_out"
    assert calls == [FIRST_RUN_PROMPT]


# --------------------------------------------------------------------------- #
# default_config_path
# --------------------------------------------------------------------------- #


def test_default_config_path_shape() -> None:
    """Lives under the user-config dir and ends in config.toml."""
    path = default_config_path()
    assert isinstance(path, Path)
    assert path.name == "config.toml"
    assert "africalim" in {part for part in path.parts}
    # Must sit inside the platformdirs user-config root for our app.
    assert path.parent == platformdirs.user_config_path("africalim")


# --------------------------------------------------------------------------- #
# consent_text sanity
# --------------------------------------------------------------------------- #


def test_consent_text_constants_are_non_empty_strings() -> None:
    """Wording lives elsewhere; just guard that nothing went silently empty."""
    for name, value in (
        ("FIRST_RUN_PROMPT", FIRST_RUN_PROMPT),
        ("PRIVACY_SUMMARY", PRIVACY_SUMMARY),
        ("LINK_TO_PRIVACY_MD", LINK_TO_PRIVACY_MD),
        ("OPT_IN_CONFIRMATION", OPT_IN_CONFIRMATION),
        ("OPT_OUT_CONFIRMATION", OPT_OUT_CONFIRMATION),
    ):
        assert isinstance(value, str), name
        assert value.strip(), name

    # The prompt should embed the privacy URL and summary so users see
    # them inline even if they don't click through.
    assert LINK_TO_PRIVACY_MD in FIRST_RUN_PROMPT
    assert PRIVACY_SUMMARY in FIRST_RUN_PROMPT
