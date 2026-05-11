"""User-level config-file schema and CRUD helpers.

The user config lives at ``platformdirs.user_config_path("africalim") /
"config.toml"`` — the same file :mod:`africalim.utils.consent` owns the
``[consent]`` section of. This module layers a broader schema on top
**without** clobbering anything the consent layer (or any other future
writer) put in there: the round-trip of :func:`save_user_config`
preserves any extra top-level keys/sections that aren't covered by the
:class:`UserConfig` model.

TOML round-trip strategy:

- Read the raw TOML on disk into a dict.
- Update only the keys/sections backed by :class:`UserConfig`.
- Merge the model dump on top of the on-disk dict and write back. Keys
  unknown to the model survive untouched.

API key material is **never** persisted here — that policy lives in
:mod:`africalim.utils.models` and the schema deliberately offers no
field for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py<3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from africalim.utils.consent import default_config_path
from africalim.utils.logger import ConsentStatus


class ConsentSection(BaseModel):
    """``[consent]`` section. Mirrors the keys :class:`ConsentManager` writes."""

    model_config = ConfigDict(extra="allow")

    status: ConsentStatus = "unset"
    prompt_shown: bool = False


class ModelSection(BaseModel):
    """``[model]`` section. Defaults match :mod:`africalim.utils.models`."""

    model_config = ConfigDict(extra="allow")

    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"


class CorpusSection(BaseModel):
    """``[corpus]`` section. Points at the corpus.toml file location."""

    model_config = ConfigDict(extra="allow")

    config_path: str = "~/.config/africalim/corpus.toml"


class UploadSection(BaseModel):
    """``[upload]`` section. The endpoint is *not* active in v0.1.0."""

    model_config = ConfigDict(extra="allow")

    endpoint: str = "https://api.africalim.net/interactions"
    batch_size: int = 50


class UserConfig(BaseModel):
    """Top-level user-config schema.

    ``extra="allow"`` lets unknown top-level sections survive a
    round-trip via the model dump; :func:`save_user_config` additionally
    preserves anything that lived in the on-disk TOML but never even
    reached the model (defensive belt-and-braces for forward
    compatibility).
    """

    model_config = ConfigDict(extra="allow")

    consent: ConsentSection = Field(default_factory=ConsentSection)
    model: ModelSection = Field(default_factory=ModelSection)
    corpus: CorpusSection = Field(default_factory=CorpusSection)
    upload: UploadSection = Field(default_factory=UploadSection)


# Top-level section names that are part of the schema. Used when
# resolving dotted keys: a section name not in here but already in the
# on-disk file is allowed; one that's not in either is rejected.
_KNOWN_SECTIONS: frozenset[str] = frozenset(
    {"consent", "model", "corpus", "upload"},
)


def default_user_config_path() -> Path:
    """Return the platform-default user-config file path.

    Identical to :func:`africalim.utils.consent.default_config_path`
    so the consent layer and the user-config layer share one file.
    """
    return default_config_path()


def _read_raw_toml(path: Path) -> dict[str, Any]:
    """Read ``path`` as a TOML mapping, returning ``{}`` if absent."""
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _write_raw_toml(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path``, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)


def load_user_config(path: Path | None = None) -> UserConfig:
    """Read the user config from ``path`` (default: platform path).

    Returns a fully-defaulted :class:`UserConfig` if the file is
    missing. Unknown top-level keys/sections are accepted and surfaced
    via the model's ``extra="allow"`` configuration so callers can
    introspect them; :func:`save_user_config` will preserve them on the
    next write.
    """
    target = path if path is not None else default_user_config_path()
    raw = _read_raw_toml(target)
    if not raw:
        return UserConfig()
    return UserConfig.model_validate(raw)


def save_user_config(config: UserConfig, path: Path | None = None) -> None:
    """Persist ``config`` to ``path`` (default: platform path).

    Preserves any top-level keys or sections that exist on disk but
    aren't part of :class:`UserConfig`. The merge strategy is shallow
    on top-level sections: known sections are *replaced* with the
    model's view, unknown sections are kept as-is.
    """
    target = path if path is not None else default_user_config_path()
    on_disk = _read_raw_toml(target)
    dumped = config.model_dump(mode="python")
    # Start from the on-disk view, overlay the model's known sections.
    # Anything in ``on_disk`` outside the model's known sections is left
    # alone. Anything in ``dumped`` (including ``extra``-allow fields)
    # overwrites the on-disk version of the same key.
    merged: dict[str, Any] = dict(on_disk)
    for key, value in dumped.items():
        merged[key] = value
    _write_raw_toml(target, merged)


class UnknownConfigKeyError(KeyError):
    """Raised when ``set_dotted`` is called with an unknown top-level section."""


class InvalidConfigValueError(ValueError):
    """Raised when ``set_dotted`` is called with a value rejected by the schema."""


def set_dotted(config_path: Path, key: str, value: str) -> UserConfig:
    """Update ``key`` (dotted path) to ``value`` and persist to ``config_path``.

    The dotted path must have exactly two components: ``section.field``.
    The top-level section must either be one of the schema's known
    sections or already exist in the on-disk file — silently creating a
    brand-new section is rejected so typos in section names surface
    immediately.

    The value is validated against the schema by re-constructing the
    full :class:`UserConfig` after the update; pydantic raises if the
    coercion (e.g. ``"opt_in"`` → ``ConsentStatus``) fails.

    Returns the resulting (validated and persisted) :class:`UserConfig`.
    """
    parts = key.split(".")
    if len(parts) != 2 or not all(parts):
        raise InvalidConfigValueError(
            f"expected dotted key of the form 'section.field', got {key!r}",
        )
    section, field = parts

    raw = _read_raw_toml(config_path)
    if section not in _KNOWN_SECTIONS and section not in raw:
        raise UnknownConfigKeyError(
            f"unknown top-level config section {section!r}; known sections: {sorted(_KNOWN_SECTIONS)}",
        )

    section_data = raw.get(section)
    if not isinstance(section_data, dict):
        section_data = {}
    section_data[field] = value
    raw[section] = section_data

    try:
        config = UserConfig.model_validate(raw)
    except ValidationError as exc:
        raise InvalidConfigValueError(
            f"invalid value for {key!r}: {exc.errors()[0]['msg']}",
        ) from exc

    save_user_config(config, config_path)
    return config
