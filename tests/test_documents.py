from pathlib import Path

import pytest

from dreamcatcher.documents import Document, DocumentError, read_toml


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
    with pytest.raises(DocumentError) as error:
        read_toml(Sample, tmp_path / "sample.toml")

    assert str(error.value) == f"{tmp_path / 'sample.toml'} does not exist."


def test_an_unreadable_document_says_so(tmp_path):
    with pytest.raises(DocumentError, match="cannot be read"):
        read_toml(Sample, tmp_path)


def test_a_document_that_is_not_toml_says_so(tmp_path):
    document = write(tmp_path, "name = \n")

    with pytest.raises(DocumentError, match="is not valid TOML"):
        read_toml(Sample, document)


def test_a_document_that_breaks_its_model_lists_every_fault(tmp_path):
    document = write(tmp_path, 'count = "many"\nextra = true\n')

    with pytest.raises(DocumentError) as error:
        read_toml(Sample, document)

    assert str(error.value) == (
        f"{document} is not valid:\n"
        "  name is required\n"
        "  count: input should be a valid integer, "
        "unable to parse string as an integer\n"
        "  there is no setting called extra"
    )
