"""Read and validate the documents dreamcatcher owns."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from dreamcatcher.errors import DreamcatcherError


class Document(BaseModel):
    """A document dreamcatcher reads or writes.

    Every document refuses a key it does not expect. A typo is then a named
    error, not a setting the tool quietly ignores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentError(DreamcatcherError):
    """A document is missing, unreadable, or does not match its model."""


def read_toml[DocumentT: Document](model: type[DocumentT], path: Path) -> DocumentT:
    """Return the document the TOML file holds, or raise DocumentError."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise DocumentError(f"{path} does not exist.") from error
    except UnicodeDecodeError as error:
        raise DocumentError(f"{path} is not UTF-8 text.") from error
    except OSError as error:
        raise DocumentError(f"cannot read {path}: {error}.") from error
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
    """Return the validation failures as one message, a line for each.

    Each line is the path to the setting, as the document nests it, and
    pydantic's own account of what is wrong with it.
    """
    lines = [f"{path} is not valid:"]
    for detail in error.errors(include_url=False, include_input=False):
        setting = ".".join(str(part) for part in detail["loc"])
        lines.append(
            f"  {setting}: {detail['msg']}" if setting else f"  {detail['msg']}"
        )
    return "\n".join(lines)
