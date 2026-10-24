import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread

import pytest
from filelock import BaseFileLock, Timeout

from dreamcatcher.documents import (
    _BACKWARD_READ_SIZE,
    _STAGED_WRITE_SUFFIX,
    DreamcatcherDocument,
    WriteOnceDreamcatcherDocument,
    append_text,
    is_complete_line_position,
    read_json,
    read_json_if_exists,
    read_last_line,
    read_lines_from,
    read_toml,
    remove_file,
    write_json,
    write_json_if_absent,
    write_text,
)
from dreamcatcher.errors import ReportableError

READERS = [
    pytest.param(read_toml, id="toml"),
    pytest.param(read_json, id="json"),
]

_WAIT_SECONDS = 5
_READ_DOCUMENT_UNTIL_RELEASED = """
import sys, time
from pathlib import Path
from unittest.mock import patch
from dreamcatcher.documents import read_text

document = Path(sys.argv[1])
opened = Path(sys.argv[2])
release = Path(sys.argv[3])
open_file = Path.open

class HeldFile:
    def __init__(self, file):
        self.file = file

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.file.__exit__(*args)

    def read(self, *args, **kwargs):
        contents = self.file.read(*args, **kwargs)
        opened.touch()
        while not release.exists():
            time.sleep(0.01)
        return contents

def open_and_hold(path, /, *args, **kwargs):
    return HeldFile(open_file(path, *args, **kwargs))

with patch.object(Path, "open", open_and_hold):
    print(read_text(path=document), end="", flush=True)
"""


class Sample(DreamcatcherDocument):
    name: str
    count: int = 1


class WriteOnceSample(WriteOnceDreamcatcherDocument):
    name: str


def write(*, path: Path, text: str) -> Path:
    document = path / "sample.toml"
    document.write_text(text, encoding="utf-8")
    return document


def _wait_for_path(*, path: Path) -> None:
    deadline = time.monotonic() + _WAIT_SECONDS
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"{path} was not written")
        time.sleep(0.01)


def _wait_for_staged_write(*, document: Path) -> None:
    deadline = time.monotonic() + _WAIT_SECONDS
    pattern = f"{document.name}.*{_STAGED_WRITE_SUFFIX}"
    while next(document.parent.glob(pattern), None) is None:
        if time.monotonic() >= deadline:
            raise AssertionError(f"no staged write appeared beside {document}")
        time.sleep(0.01)


def test_a_valid_document_reads_back(tmp_path):
    document = write(path=tmp_path, text='name = "probe"\ncount = 3\n')

    assert read_toml(model=Sample, path=document) == Sample(name="probe", count=3)
    assert not document.with_name("sample.toml.lock").exists()


def test_a_valid_json_document_reads_back(tmp_path):
    document = write(path=tmp_path, text='{"name": "probe", "count": 3}')

    assert read_json(model=Sample, path=document) == Sample(name="probe", count=3)


def test_a_write_once_json_document_needs_no_lock(tmp_path):
    document = tmp_path / "work.json"

    write_json(document=WriteOnceSample(name="probe"), path=document)

    assert read_json(model=WriteOnceSample, path=document).name == "probe"
    assert not document.with_name("work.json.lock").exists()


def test_an_optional_json_document_reads_back(tmp_path):
    document = write(path=tmp_path, text='{"name": "probe", "count": 3}')

    assert read_json_if_exists(model=Sample, path=document) == Sample(
        name="probe", count=3
    )


def test_a_missing_optional_json_document_is_none(tmp_path):
    document = tmp_path / "sample.json"

    assert read_json_if_exists(model=Sample, path=document) is None
    assert document.with_name("sample.json.lock").is_file()


def test_an_unreadable_optional_json_document_says_so(tmp_path):
    with pytest.raises(ReportableError, match="cannot read"):
        read_json_if_exists(model=Sample, path=tmp_path)


@pytest.mark.parametrize("read", READERS)
def test_a_missing_document_names_the_path(tmp_path, read):
    with pytest.raises(ReportableError) as error:
        read(model=Sample, path=tmp_path / "sample.toml")

    assert str(error.value) == f"{tmp_path / 'sample.toml'} does not exist."


@pytest.mark.parametrize("read", READERS)
def test_an_unreadable_document_says_so(tmp_path, read):
    with pytest.raises(ReportableError, match="cannot read"):
        read(model=Sample, path=tmp_path)


@pytest.mark.parametrize("read", READERS)
def test_a_document_that_is_not_utf_8_says_so(tmp_path, read):
    document = tmp_path / "sample.toml"
    document.write_bytes('name = "Ren\u00e9"\n'.encode("utf-16"))

    with pytest.raises(ReportableError, match="not UTF-8"):
        read(model=Sample, path=document)


def write_growing_file(*, path: Path, written: str) -> Path:
    """Write a file that something adds a line at a time to, and return it.

    The bytes go down as they are written. A text-mode write turns each line
    ending into the one the platform prefers, and then the positions these
    tests assert would be Windows's own numbers rather than these.
    """
    file = path / "feed.txt"
    file.write_bytes(written.encode("utf-8"))
    return file


def test_a_file_reads_as_the_lines_it_holds_and_where_they_end(tmp_path):
    assert read_lines_from(
        path=write_growing_file(path=tmp_path, written="first\nsecond\n"), position=0
    ) == (
        ["first", "second"],
        13,
    )


def test_a_read_from_where_the_last_one_stopped_finds_what_arrived_since(tmp_path):
    file = write_growing_file(path=tmp_path, written="first\n")
    _, position = read_lines_from(path=file, position=0)

    append_text(text="second\n", path=file)

    assert read_lines_from(path=file, position=position) == (["second"], 13)


def test_a_line_still_being_written_is_not_one_a_file_holds(tmp_path):
    assert read_lines_from(
        path=write_growing_file(path=tmp_path, written="first\nseco"), position=0
    ) == (
        ["first"],
        6,
    )


def test_a_line_still_being_written_reads_whole_once_the_rest_lands(tmp_path):
    file = write_growing_file(path=tmp_path, written="first\nseco")
    _, position = read_lines_from(path=file, position=0)

    append_text(text="nd\n", path=file)

    assert read_lines_from(path=file, position=position) == (["second"], 13)


def test_a_file_with_nothing_in_it_holds_no_lines(tmp_path):
    assert read_lines_from(
        path=write_growing_file(path=tmp_path, written=""), position=0
    ) == (
        [],
        0,
    )


def test_a_file_that_is_not_there_holds_no_lines(tmp_path):
    assert read_lines_from(path=tmp_path / "feed.txt", position=0) == ([], 0)


@pytest.mark.parametrize(
    ("written", "position", "expected"),
    [
        ("first\nsecond\n", 0, True),
        ("first\nsecond\n", 6, True),
        ("first\nsecond\n", 1, False),
        ("first\nsecond\n", -1, False),
        ("first\nsecond\n", 99, False),
    ],
)
def test_a_complete_line_position_is_recognised(tmp_path, written, position, expected):
    assert (
        is_complete_line_position(
            path=write_growing_file(path=tmp_path, written=written),
            position=position,
        )
        is expected
    )


def test_position_zero_is_valid_for_a_file_that_is_not_there(tmp_path):
    assert is_complete_line_position(path=tmp_path / "feed.txt", position=0)


def test_a_file_of_lines_that_is_not_utf_8_says_so(tmp_path):
    file = tmp_path / "feed.txt"
    file.write_bytes(b"first\n\xff\n")

    with pytest.raises(ReportableError, match="not UTF-8"):
        read_lines_from(path=file, position=0)


def test_lines_that_cannot_be_read_say_so(tmp_path):
    with pytest.raises(ReportableError, match="cannot read"):
        read_lines_from(path=tmp_path, position=0)


def test_the_last_line_a_file_holds_is_the_last_one_written_whole(tmp_path):
    assert (
        read_last_line(
            path=write_growing_file(path=tmp_path, written="first\nsecond\n")
        )
        == "second"
    )


def test_a_file_holding_one_line_holds_it_as_its_last(tmp_path):
    assert (
        read_last_line(path=write_growing_file(path=tmp_path, written="only\n"))
        == "only"
    )


def test_a_line_still_being_written_is_not_the_last_a_file_holds(tmp_path):
    assert (
        read_last_line(path=write_growing_file(path=tmp_path, written="first\nseco"))
        == "first"
    )


def test_a_file_with_no_whole_line_in_it_yet_holds_no_last_line(tmp_path):
    assert read_last_line(path=write_growing_file(path=tmp_path, written="fir")) is None


def test_a_file_with_nothing_in_it_holds_no_last_line(tmp_path):
    assert read_last_line(path=write_growing_file(path=tmp_path, written="")) is None


def test_a_file_that_is_not_there_holds_no_last_line(tmp_path):
    assert read_last_line(path=tmp_path / "feed.txt") is None


def test_a_last_line_longer_than_one_read_of_the_end_reads_whole(tmp_path):
    long_line = "x" * (_BACKWARD_READ_SIZE * 2 + 1)

    assert (
        read_last_line(
            path=write_growing_file(path=tmp_path, written=f"first\n{long_line}\n")
        )
        == long_line
    )


def test_a_file_whose_last_line_is_not_utf_8_says_so(tmp_path):
    file = tmp_path / "feed.txt"
    file.write_bytes(b"first\n\xff\n")

    with pytest.raises(ReportableError, match="not UTF-8"):
        read_last_line(path=file)


def test_a_last_line_that_cannot_be_read_says_so(tmp_path):
    with pytest.raises(ReportableError, match="cannot read"):
        read_last_line(path=tmp_path)


def test_a_document_that_is_not_toml_says_so(tmp_path):
    document = write(path=tmp_path, text="name = \n")

    with pytest.raises(ReportableError, match="is not valid TOML"):
        read_toml(model=Sample, path=document)


def test_a_document_that_is_not_json_says_so(tmp_path):
    document = write(path=tmp_path, text="not json at all\n")

    with pytest.raises(ReportableError, match="Invalid JSON"):
        read_json(model=Sample, path=document)


def test_a_document_that_breaks_its_model_lists_every_fault(tmp_path):
    document = write(path=tmp_path, text='count = "many"\nextra = true\n')

    with pytest.raises(ReportableError) as error:
        read_toml(model=Sample, path=document)

    assert str(error.value) == (
        f"{document} is not valid:\n"
        "  name: Field required\n"
        "  count: Input should be a valid integer, "
        "unable to parse string as an integer\n"
        "  extra: Extra inputs are not permitted"
    )


def test_a_json_document_that_breaks_its_model_lists_every_fault(tmp_path):
    document = write(path=tmp_path, text='{"count": "many", "extra": true}')

    with pytest.raises(ReportableError) as error:
        read_json(model=Sample, path=document)

    assert str(error.value) == (
        f"{document} is not valid:\n"
        "  extra: Extra inputs are not permitted\n"
        "  name: Field required\n"
        "  count: Input should be a valid integer, "
        "unable to parse string as an integer"
    )


def test_a_write_lands_where_it_is_asked_for(tmp_path):
    written = tmp_path / "records" / "sample.txt"

    write_text(text="what it holds\n", path=written)

    assert written.read_text(encoding="utf-8") == "what it holds\n"


def test_a_document_reader_and_replacement_coordinate_between_processes(tmp_path):
    document = tmp_path / "scheduler.json"
    document.write_bytes(b'{"name": "old contents"}\n')
    opened = tmp_path / "opened"
    release = tmp_path / "release"
    write_finished = Event()
    write_errors = []

    def replace_document():
        try:
            write_text(text='{"name": "new contents"}\n', path=document)
        except BaseException as error:
            write_errors.append(error)
        finally:
            write_finished.set()

    with subprocess.Popen(
        [
            sys.executable,
            "-c",
            _READ_DOCUMENT_UNTIL_RELEASED,
            str(document),
            str(opened),
            str(release),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    ) as reader:
        writer = Thread(target=replace_document)
        try:
            _wait_for_path(path=opened)
            writer.start()
            _wait_for_staged_write(document=document)
            assert not write_finished.is_set()
            assert document.read_bytes() == b'{"name": "old contents"}\n'
        finally:
            release.write_bytes(b"")
            writer.join(_WAIT_SECONDS)
        read_contents, read_error = reader.communicate(timeout=_WAIT_SECONDS)

    assert reader.returncode == 0, read_error
    assert not writer.is_alive()
    assert write_errors == []
    assert read_contents == '{"name": "old contents"}\n'
    assert read_json(model=Sample, path=document).name == "new contents"
    assert document.with_name("scheduler.json.lock").is_file()


def test_a_write_keeps_its_persistent_lock_beside_what_it_wrote(tmp_path):
    written = tmp_path / "round.json"

    write_text(text="what it holds\n", path=written)

    assert sorted(found.name for found in tmp_path.iterdir()) == [
        "round.json",
        "round.json.lock",
    ]


def test_a_write_that_lands_while_another_is_staged_leaves_both_whole(
    tmp_path, monkeypatch
):
    # The second write lands between the first write's staging and its move into
    # place, as a write from another process or thread can.
    written = tmp_path / "assignment.json"
    acquire = BaseFileLock.acquire
    landed_while_staged = []

    def land_another_write_first(lock, /):
        """Let another write land after staging and before acquiring the lock."""
        monkeypatch.setattr(BaseFileLock, "acquire", acquire)
        write_text(text="the second write\n", path=written)
        landed_while_staged.append(written.read_bytes())
        return acquire(lock)

    monkeypatch.setattr(BaseFileLock, "acquire", land_another_write_first)

    write_text(text="the first write\n", path=written)

    assert landed_while_staged == [b"the second write\n"]
    assert written.read_bytes() == b"the first write\n"
    assert sorted(found.name for found in tmp_path.iterdir()) == [
        "assignment.json",
        "assignment.json.lock",
    ]


def test_a_write_gives_its_file_the_mode_any_new_file_gets(tmp_path):
    plain = tmp_path / "plain.txt"
    plain.write_bytes(b"")
    written = tmp_path / "written.txt"

    write_text(text="what it holds\n", path=written)

    assert written.stat().st_mode == plain.stat().st_mode


def test_a_write_if_absent_lands_where_no_document_is(tmp_path):
    written = tmp_path / "ended.json"

    assert write_json_if_absent(document=WriteOnceSample(name="first"), path=written)

    assert read_json(model=WriteOnceSample, path=written).name == "first"
    assert sorted(found.name for found in tmp_path.iterdir()) == [
        "ended.json",
        "ended.json.lock",
    ]


def test_a_write_if_absent_leaves_the_document_that_is_there(tmp_path):
    written = tmp_path / "ended.json"
    write_json_if_absent(document=WriteOnceSample(name="first"), path=written)
    first = written.read_bytes()

    assert not write_json_if_absent(
        document=WriteOnceSample(name="second"), path=written
    )

    assert written.read_bytes() == first
    assert sorted(found.name for found in tmp_path.iterdir()) == [
        "ended.json",
        "ended.json.lock",
    ]


def test_a_write_if_absent_reads_what_landed_while_it_was_staged(tmp_path, monkeypatch):
    # The other write lands between this write's staging and its lock, as a
    # write from another process or thread can.
    written = tmp_path / "ended.json"
    acquire = BaseFileLock.acquire

    def land_another_write_first(lock, /):
        """Let another write land after staging and before acquiring the lock."""
        monkeypatch.setattr(BaseFileLock, "acquire", acquire)
        write_json_if_absent(document=WriteOnceSample(name="other"), path=written)
        return acquire(lock)

    monkeypatch.setattr(BaseFileLock, "acquire", land_another_write_first)

    assert not write_json_if_absent(document=WriteOnceSample(name="this"), path=written)

    assert read_json(model=WriteOnceSample, path=written).name == "other"
    assert next(tmp_path.glob(f"*{_STAGED_WRITE_SUFFIX}"), None) is None


def test_a_write_if_absent_over_an_invalid_document_says_so_and_keeps_it(tmp_path):
    written = tmp_path / "ended.json"
    written.write_bytes(b'{"name": 3}\n')

    with pytest.raises(ReportableError, match=f"{written} is not valid"):
        write_json_if_absent(document=WriteOnceSample(name="first"), path=written)

    assert written.read_bytes() == b'{"name": 3}\n'
    assert next(tmp_path.glob(f"*{_STAGED_WRITE_SUFFIX}"), None) is None


def test_a_write_if_absent_that_cannot_read_what_is_there_says_so(tmp_path):
    written = tmp_path / "ended.json"
    written.mkdir()

    with pytest.raises(ReportableError, match="cannot read"):
        write_json_if_absent(document=WriteOnceSample(name="first"), path=written)

    assert written.is_dir()
    assert next(tmp_path.glob(f"*{_STAGED_WRITE_SUFFIX}"), None) is None


def test_a_write_if_absent_that_cannot_take_its_lock_writes_nothing(
    tmp_path, monkeypatch
):
    written = tmp_path / "ended.json"

    def refuse_lock(self, /):
        raise Timeout(self.lock_file)

    monkeypatch.setattr(BaseFileLock, "acquire", refuse_lock)

    with pytest.raises(ReportableError, match="cannot write"):
        write_json_if_absent(document=WriteOnceSample(name="first"), path=written)

    assert not written.exists()
    assert next(tmp_path.glob(f"*{_STAGED_WRITE_SUFFIX}"), None) is None


def test_a_failed_write_cleans_its_staged_file_and_keeps_its_lock(tmp_path):
    taken = tmp_path / "taken"
    taken.mkdir()

    with pytest.raises(ReportableError, match="cannot write"):
        write_text(text="what it holds\n", path=taken)

    assert sorted(found.name for found in tmp_path.iterdir()) == ["taken", "taken.lock"]


def test_a_document_read_that_cannot_take_its_lock_is_reportable(tmp_path, monkeypatch):
    document = write(path=tmp_path, text='{"name": "old contents"}')

    def refuse_lock(self, /):
        raise Timeout(self.lock_file)

    monkeypatch.setattr(BaseFileLock, "acquire", refuse_lock)

    with pytest.raises(ReportableError, match="cannot read"):
        read_json(model=Sample, path=document)


def test_a_document_write_that_cannot_take_its_lock_preserves_the_document(
    tmp_path, monkeypatch
):
    document = tmp_path / "sample.toml"
    document.write_bytes(b"old contents\n")

    def refuse_lock(self, /):
        raise Timeout(self.lock_file)

    monkeypatch.setattr(BaseFileLock, "acquire", refuse_lock)

    with pytest.raises(ReportableError, match="cannot write"):
        write_text(text="new contents\n", path=document)

    assert document.read_bytes() == b"old contents\n"
    assert next(tmp_path.glob(f"*{_STAGED_WRITE_SUFFIX}"), None) is None


def test_an_append_adds_to_the_end_of_what_is_there(tmp_path):
    written = tmp_path / "records" / "feed.txt"

    append_text(text="one line\n", path=written)
    append_text(text="another\n", path=written)

    assert written.read_text(encoding="utf-8") == "one line\nanother\n"


def test_an_append_that_fails_says_so(tmp_path):
    with pytest.raises(ReportableError, match="cannot write"):
        append_text(text="one line\n", path=tmp_path)


def test_a_file_is_removed_when_it_exists(tmp_path):
    document = write(path=tmp_path, text="anything\n")

    remove_file(path=document)

    assert not document.exists()


def test_removing_a_missing_file_is_already_done(tmp_path):
    remove_file(path=tmp_path / "missing.txt")


def test_a_file_that_cannot_be_removed_says_so(tmp_path):
    with pytest.raises(ReportableError, match="cannot remove"):
        remove_file(path=tmp_path)


def test_a_write_keeps_the_line_endings_it_was_given(tmp_path):
    written = tmp_path / "raw.jsonl"

    write_text(text="one line\nanother\n", path=written)

    assert written.read_bytes() == b"one line\nanother\n"
