"""Read and write the files that dreamcatcher owns."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from dreamcatcher.errors import ReportableError

# What a whole write is written to before it takes its target's place.
WRITING = ".writing"


class Document(BaseModel):
    """A document that dreamcatcher reads or writes.

    Every document refuses a key that it does not expect. A typo is then a
    named error, not a setting that the tool quietly ignores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


def read_toml[DocumentT: Document](model: type[DocumentT], path: Path) -> DocumentT:
    """Return the document the TOML file holds, or raise ReportableError."""
    try:
        data = tomllib.loads(_read_text(path))
    except tomllib.TOMLDecodeError as error:
        raise ReportableError(f"{path} is not valid TOML: {error}.") from error
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise ReportableError(_report(path, error)) from error


def read_json[DocumentT: Document](model: type[DocumentT], path: Path) -> DocumentT:
    """Return the document the JSON file holds, or raise ReportableError.

    Every document the tool writes for itself is JSON, so this is how the tool
    reads its own records back. pydantic reads the JSON and checks the model in
    one step, so a file that is not JSON at all reports as the first fault the
    document has.
    """
    try:
        return model.model_validate_json(_read_text(path))
    except ValidationError as error:
        raise ReportableError(_report(path, error)) from error


def write_text(text: str, path: Path) -> None:
    """Write text to path as UTF-8, over whatever was there before.

    The write lands whole. The text goes to a file beside the target and then
    takes the target's place in one step, so a reader of the target reads the
    document that was there or the one that replaced it, and never half of
    one. A reader really does arrive mid-write: a round records how it ended
    on a thread of its own, while a tick is reading every round's record.

    Raise ReportableError when the write fails. A full disk or a read-only
    directory is not a bug in the tool, and the user can act on either, so it
    reads as a message.
    """
    beside = path.with_name(f"{path.name}{WRITING}")
    _write(text, beside, "w")
    try:
        beside.replace(path)
    except OSError as error:
        raise ReportableError(f"cannot write {path}: {error}.") from error


def append_text(text: str, path: Path) -> None:
    """Add text to the end of the file at path, as UTF-8.

    Raise ReportableError when the write fails, for the reason write_text does.

    A round's feed and its raw stream each grow by a line at a time while the
    round runs, so the round adds to them rather than rewriting them. Whoever
    reads one reads the lines that have landed, so an append needs no step of
    its own to land whole.
    """
    _write(text, path, "a")


def write_json(document: Document, path: Path) -> None:
    """Write the document to path as JSON."""
    write_text(document.model_dump_json(indent=2) + "\n", path)


def _read_text(path: Path) -> str:
    """Return the text the file at path holds, read as UTF-8.

    Raise ReportableError when the read fails. A document that is not there, or
    that nothing can read, is something the user can act on, so it reads as a
    message rather than a traceback.
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ReportableError(f"{path} does not exist.") from error
    except UnicodeDecodeError as error:
        raise ReportableError(f"{path} is not UTF-8 text.") from error
    except OSError as error:
        raise ReportableError(f"cannot read {path}: {error}.") from error


def _write(text: str, path: Path, mode: str) -> None:
    """Write text to path as UTF-8, making the directory that holds it.

    Making the directory here is what lets a caller write a file without
    creating the directory first.

    The line endings are the caller's. Left to itself Python turns every line
    ending into the one the platform prefers, which would put a carriage return
    into a round's copy of what a harness streamed.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open(mode, encoding="utf-8", newline="") as opened:
            opened.write(text)
    except OSError as error:
        raise ReportableError(f"cannot write {path}: {error}.") from error


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
