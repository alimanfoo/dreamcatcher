"""Read and validate the documents dreamcatcher owns."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import ErrorDetails

from dreamcatcher.errors import DreamcatcherError


class Document(BaseModel):
    """A document dreamcatcher reads or writes.

    Every document forbids keys it does not declare. A typo is then a named
    error, not a setting the tool quietly ignores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentError(DreamcatcherError):
    """A document is missing, unreadable, or does not say what it must."""


def read_toml[DocumentT: Document](model: type[DocumentT], path: Path) -> DocumentT:
    """Return the document the TOML file holds, or raise DocumentError."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise DocumentError(f"{path} does not exist.") from error
    except UnicodeDecodeError as error:
        raise DocumentError(f"{path} is not UTF-8 text.") from error
    except OSError as error:
        raise DocumentError(f"dreamcatcher cannot read {path}: {error}.") from error
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise DocumentError(f"{path} is not valid TOML: {error}.") from error
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise DocumentError(_report(path, error)) from error


def write_json(document: Document, path: Path) -> None:
    """Write the document to path as JSON, in UTF-8."""
    path.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _report(path: Path, error: ValidationError) -> str:
    """Return the validation failures as one message, a line for each."""
    lines = [f"{path} is not valid:"]
    lines += [f"  {_phrase(detail)}" for detail in error.errors()]
    return "\n".join(lines)


def _phrase(detail: ErrorDetails) -> str:
    """Return one plain-words line for one validation failure."""
    location, setting = _split(detail["loc"])
    place = _place(location)
    fault = _fault(detail, setting)
    return f"{place}: {fault}" if place else fault


def _split(
    location: tuple[int | str, ...],
) -> tuple[tuple[int | str, ...], str | None]:
    """Split a failure's location into where it is and which setting it names."""
    if location and isinstance(location[-1], str):
        return location[:-1], location[-1]
    return location, None


def _place(location: tuple[int | str, ...]) -> str:
    """Return where the failure is, as prose: "dispatch entry 1, claude block"."""
    words = []
    # Pair each part with the one after it, so a part followed by an index reads
    # as an entry. zip stops at the shorter, so an empty location pairs nothing.
    for part, following in zip(location, [*location[1:], None], strict=False):
        if isinstance(part, int):
            continue
        if isinstance(following, int):
            words.append(f"{part} entry {following + 1}")
        else:
            words.append(f"{part} block")
    return ", ".join(words)


# Pydantic's own wording for these names a Python class or counts items, which
# says nothing to whoever wrote the file. Anything else passes through.
_FAULTS = {
    "missing": "{setting} is required",
    "extra_forbidden": "dreamcatcher has no setting called {setting}",
    "model_type": "{setting} must be a block of settings",
}


def _fault(detail: ErrorDetails, setting: str | None) -> str:
    """Return what is wrong, in plain words."""
    phrasing = _FAULTS.get(detail["type"])
    if phrasing is not None:
        return phrasing.format(setting=setting)
    message = detail["msg"].removeprefix("Value error, ")
    if setting is None:
        return message
    return f"{setting}: {message[:1].lower()}{message[1:]}"
