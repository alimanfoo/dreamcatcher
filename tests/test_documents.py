from pathlib import Path

import pytest

from dreamcatcher.documents import (
    BACKWARD_WINDOW,
    Document,
    append_text,
    read_json,
    read_last_line,
    read_lines_from,
    read_toml,
    write_text,
)
from dreamcatcher.errors import ReportableError

READERS = [
    pytest.param(read_toml, id="toml"),
    pytest.param(read_json, id="json"),
]


class Sample(Document):
    name: str
    count: int = 1


def write(*, path: Path, text: str) -> Path:
    document = path / "sample.toml"
    document.write_text(text, encoding="utf-8")
    return document


def test_a_valid_document_reads_back(tmp_path):
    document = write(path=tmp_path, text='name = "probe"\ncount = 3\n')

    assert read_toml(model=Sample, path=document) == Sample(name="probe", count=3)


def test_a_valid_json_document_reads_back(tmp_path):
    document = write(path=tmp_path, text='{"name": "probe", "count": 3}')

    assert read_json(model=Sample, path=document) == Sample(name="probe", count=3)


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


def growing(*, path: Path, written: str) -> Path:
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
        path=growing(path=tmp_path, written="first\nsecond\n"), position=0
    ) == (
        ["first", "second"],
        13,
    )


def test_a_read_from_where_the_last_one_stopped_finds_what_arrived_since(tmp_path):
    file = growing(path=tmp_path, written="first\n")
    _, position = read_lines_from(path=file, position=0)

    append_text(text="second\n", path=file)

    assert read_lines_from(path=file, position=position) == (["second"], 13)


def test_a_line_still_being_written_is_not_one_a_file_holds(tmp_path):
    assert read_lines_from(
        path=growing(path=tmp_path, written="first\nseco"), position=0
    ) == (
        ["first"],
        6,
    )


def test_a_line_still_being_written_reads_whole_once_the_rest_lands(tmp_path):
    file = growing(path=tmp_path, written="first\nseco")
    _, position = read_lines_from(path=file, position=0)

    append_text(text="nd\n", path=file)

    assert read_lines_from(path=file, position=position) == (["second"], 13)


def test_a_file_with_nothing_in_it_holds_no_lines(tmp_path):
    assert read_lines_from(path=growing(path=tmp_path, written=""), position=0) == (
        [],
        0,
    )


def test_a_file_that_is_not_there_holds_no_lines(tmp_path):
    assert read_lines_from(path=tmp_path / "feed.txt", position=0) == ([], 0)


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
        read_last_line(path=growing(path=tmp_path, written="first\nsecond\n"))
        == "second"
    )


def test_a_file_holding_one_line_holds_it_as_its_last(tmp_path):
    assert read_last_line(path=growing(path=tmp_path, written="only\n")) == "only"


def test_a_line_still_being_written_is_not_the_last_a_file_holds(tmp_path):
    assert read_last_line(path=growing(path=tmp_path, written="first\nseco")) == "first"


def test_a_file_with_no_whole_line_in_it_yet_holds_no_last_line(tmp_path):
    assert read_last_line(path=growing(path=tmp_path, written="fir")) is None


def test_a_file_with_nothing_in_it_holds_no_last_line(tmp_path):
    assert read_last_line(path=growing(path=tmp_path, written="")) is None


def test_a_file_that_is_not_there_holds_no_last_line(tmp_path):
    assert read_last_line(path=tmp_path / "feed.txt") is None


def test_a_last_line_longer_than_one_read_of_the_end_reads_whole(tmp_path):
    long_line = "x" * (BACKWARD_WINDOW * 2 + 1)

    assert (
        read_last_line(path=growing(path=tmp_path, written=f"first\n{long_line}\n"))
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


def test_a_write_leaves_nothing_of_itself_beside_what_it_wrote(tmp_path):
    # A whole write lands through a file beside the target, and a reader of the
    # session's rounds globs the directory, so nothing may be left there.
    written = tmp_path / "round.json"

    write_text(text="what it holds\n", path=written)

    assert [found.name for found in tmp_path.iterdir()] == ["round.json"]


def test_a_write_that_fails_says_so(tmp_path):
    with pytest.raises(ReportableError, match="cannot write"):
        write_text(text="what it holds\n", path=tmp_path)


def test_an_append_adds_to_the_end_of_what_is_there(tmp_path):
    written = tmp_path / "records" / "feed.txt"

    append_text(text="one line\n", path=written)
    append_text(text="another\n", path=written)

    assert written.read_text(encoding="utf-8") == "one line\nanother\n"


def test_an_append_that_fails_says_so(tmp_path):
    with pytest.raises(ReportableError, match="cannot write"):
        append_text(text="one line\n", path=tmp_path)


def test_a_write_keeps_the_line_endings_it_was_given(tmp_path):
    written = tmp_path / "raw.jsonl"

    write_text(text="one line\nanother\n", path=written)

    assert written.read_bytes() == b"one line\nanother\n"
