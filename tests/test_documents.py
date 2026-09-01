from pathlib import Path

import pytest

from dreamcatcher.documents import Document, read_toml, write_text
from dreamcatcher.errors import ReportableError


class Sample(Document):
    name: str
    count: int = 1


def write(path: Path, text: str) -> Path:
    document = path / "sample.toml"
    document.write_text(text, encoding="utf-8")
    return document


def test_a_valid_document_reads_back(tmp_path):
    document = write(tmp_path, 'name = "probe"\ncount = 3\n')

    assert read_toml(Sample, document) == Sample(name="probe", count=3)


def test_a_missing_document_names_the_path(tmp_path):
    with pytest.raises(ReportableError) as error:
        read_toml(Sample, tmp_path / "sample.toml")

    assert str(error.value) == f"{tmp_path / 'sample.toml'} does not exist."


def test_an_unreadable_document_says_so(tmp_path):
    with pytest.raises(ReportableError, match="cannot read"):
        read_toml(Sample, tmp_path)


def test_a_document_that_is_not_toml_says_so(tmp_path):
    document = write(tmp_path, "name = \n")

    with pytest.raises(ReportableError, match="is not valid TOML"):
        read_toml(Sample, document)


def test_a_document_that_is_not_utf_8_says_so(tmp_path):
    document = tmp_path / "sample.toml"
    document.write_bytes('name = "Ren\u00e9"\n'.encode("utf-16"))

    with pytest.raises(ReportableError, match="not UTF-8"):
        read_toml(Sample, document)


def test_a_document_that_breaks_its_model_lists_every_fault(tmp_path):
    document = write(tmp_path, 'count = "many"\nextra = true\n')

    with pytest.raises(ReportableError) as error:
        read_toml(Sample, document)

    assert str(error.value) == (
        f"{document} is not valid:\n"
        "  name: Field required\n"
        "  count: Input should be a valid integer, "
        "unable to parse string as an integer\n"
        "  extra: Extra inputs are not permitted"
    )


def test_a_write_lands_where_it_is_asked_for(tmp_path):
    written = tmp_path / "records" / "sample.txt"

    write_text("what it holds\n", written)

    assert written.read_text(encoding="utf-8") == "what it holds\n"


def test_a_write_that_fails_names_the_path(tmp_path):
    with pytest.raises(ReportableError, match="cannot write"):
        write_text("what it holds\n", tmp_path)
