"""Read and write the files that dreamcatcher owns."""

import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from io import SEEK_END, BytesIO
from pathlib import Path
from typing import IO

from pydantic import BaseModel, ConfigDict, ValidationError

from dreamcatcher.errors import ReportableError

# What a whole write is written to before it takes its target's place.
ATOMIC_WRITE_SUFFIX = ".writing"

# How much of the end of a file each read of a backward search takes. A last
# line longer than this takes another read to find, and nothing else turns on
# the size.
BACKWARD_READ_SIZE = 4096


class DreamcatcherDocument(BaseModel):
    """Model a document that Dreamcatcher owns.

    Every document refuses a key that it does not expect. A typo is then a
    named error, not a setting that the tool quietly ignores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def read_toml[DocumentT: DreamcatcherDocument](
    *, model: type[DocumentT], path: Path
) -> DocumentT:
    """Return the document the TOML file holds, or raise ReportableError."""
    try:
        data = tomllib.loads(read_text(path=path))
    except tomllib.TOMLDecodeError as error:
        raise ReportableError(f"{path} is not valid TOML: {error}.") from error
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise ReportableError(
            _describe_validation_error(path=path, error=error)
        ) from error


def read_json[DocumentT: DreamcatcherDocument](
    *, model: type[DocumentT], path: Path
) -> DocumentT:
    """Return the JSON document, or raise ReportableError.

    Every document the tool writes for itself is JSON, so this is how the tool
    reads its own records back. pydantic reads the JSON and checks the model in
    one step, so a file that is not JSON at all reports as the first fault the
    document has.
    """
    try:
        return model.model_validate_json(read_text(path=path))
    except ValidationError as error:
        raise ReportableError(
            _describe_validation_error(path=path, error=error)
        ) from error


def read_text(*, path: Path) -> str:
    """Return the text the file at path holds, read as UTF-8.

    The line endings come as the file holds them, which is how `_write` leaves
    them. Left to itself Python turns each of them into a newline, and then a
    read and a write of one file would not agree on what is in it.

    Raise ReportableError when the read fails. A document that is not there, or
    that nothing can read, is something the user can act on, so it reads as a
    message rather than a traceback.
    """
    try:
        return _decode(contents=path.read_bytes(), path=path)
    except FileNotFoundError as error:
        raise ReportableError(f"{path} does not exist.") from error
    except OSError as error:
        raise ReportableError(f"cannot read {path}: {error}.") from error


def read_lines_from(*, path: Path, position: int) -> tuple[list[str], int]:
    """Return complete lines after a byte position and the next byte position.

    A file that something appends to grows a line at a time, and the last line
    of it carries no ending until the append that writes it lands. A line with
    no ending is not one the file holds, so the position that comes back stops
    just past the last line ending rather than wherever the file happens to
    end, and a read that starts there shows that line whole once the rest of
    it lands.

    A file that is not there holds no lines, and neither does one that nothing
    has finished a line of yet, so each reads as nothing rather than as a
    failure.

    The returned position counts bytes so that it remains valid across platforms.

    Raise ReportableError when the read fails, for the reason read_text does.
    """
    with _open_bytes(path=path) as opened:
        opened.seek(position)
        landed, ending, _ = opened.read().rpartition(b"\n")
    if not ending:
        return [], position
    return _decode(contents=landed, path=path).split("\n"), position + len(
        landed
    ) + len(ending)


def read_last_line(*, path: Path) -> str | None:
    """Return the last complete line without its line ending.

    A line with no ending is not one the file holds, for the reason
    `read_lines_from` gives, so the line before it is the last that the file
    does hold.

    A file with no whole line in it holds no last line, and neither does a file
    that is not there, so each reads as nothing rather than as a failure.

    The end of the file is what this reads. A file that something keeps
    appending to grows without limit, so a read that took the whole of it would
    cost everything ever written, and a caller that asks again on a timer would
    pay that again each time.

    Raise ReportableError when the read fails, for the reason read_text does.
    """
    with _open_bytes(path=path) as opened:
        end_of_line = _find_line_ending(opened=opened, before=opened.seek(0, SEEK_END))
        if end_of_line is None:
            return None
        ending_before = _find_line_ending(opened=opened, before=end_of_line)
        start_of_line = 0 if ending_before is None else ending_before + 1
        opened.seek(start_of_line)
        return _decode(contents=opened.read(end_of_line - start_of_line), path=path)


def write_text(*, text: str, path: Path) -> None:
    """Write text to path as UTF-8, over whatever was there before.

    The write lands whole. The text goes to a file beside the target and then
    takes the target's place in one step, so a reader of the target reads the
    document that was there or the one that replaced it, and never a partial
    document.

    Raise ReportableError when the write fails. A full disk or a read-only
    directory is not a bug in the tool, and the user can act on either, so it
    reads as a message.
    """
    beside = path.with_name(f"{path.name}{ATOMIC_WRITE_SUFFIX}")
    _write(text=text, path=beside, mode="w")
    try:
        beside.replace(path)
    except OSError as error:
        raise ReportableError(f"cannot write {path}: {error}.") from error


def append_text(*, text: str, path: Path) -> None:
    """Append UTF-8 text without translating line endings.

    Raise ReportableError when the write fails, for the reason write_text does.

    Feeds and raw harness streams grow one complete line at a time.
    """
    _write(text=text, path=path, mode="a")


def write_json(*, document: DreamcatcherDocument, path: Path) -> None:
    """Write the document to path as JSON."""
    write_text(text=document.model_dump_json(indent=2, by_alias=True) + "\n", path=path)


@contextmanager
def _open_bytes(*, path: Path) -> Iterator[IO[bytes]]:
    """Open the file for byte reads, or provide an empty stream if it is absent.

    Finding one part of a file takes more than one read of it, so whoever
    reads holds the file open across them.

    The bytes come as the file holds them, which is how `_write` leaves them.
    A text-mode read turns each line ending into a newline, and then a
    position that a reader kept and the position the file itself agrees with
    are different numbers.

    Raise ReportableError when the read fails, for the reason read_text does.
    """
    try:
        with path.open("rb") if path.exists() else BytesIO() as opened:
            yield opened
    except OSError as error:
        raise ReportableError(f"cannot read {path}: {error}.") from error


def _find_line_ending(*, opened: IO[bytes], before: int) -> int | None:
    """Return where the last line ending before this position is, or nothing.

    The file is read backwards a window at a time, so no read of it takes the
    whole, and a line longer than one window is found all the same.
    """
    end = before
    while end > 0:
        start = max(0, end - BACKWARD_READ_SIZE)
        opened.seek(start)
        ending_position = opened.read(end - start).rfind(b"\n")
        if ending_position >= 0:
            return start + ending_position
        end = start
    return None


def _decode(*, contents: bytes, path: Path) -> str:
    """Decode file contents as UTF-8 or raise ReportableError.

    Raise ReportableError when the bytes are not UTF-8, for the reason
    read_text does.
    """
    try:
        return contents.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportableError(f"{path} is not UTF-8 text.") from error


def _write(*, text: str, path: Path, mode: str) -> None:
    """Write UTF-8 text with fixed line endings, creating parent directories.

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


def _describe_validation_error(*, path: Path, error: ValidationError) -> str:
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
