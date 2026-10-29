"""Check the text that explains dreamcatcher."""

from conftest import FIXTURES, assert_matches_view_golden

import dreamcatcher.about as about
from dreamcatcher.about import read_about_dreamcatcher
from dreamcatcher.cli import main


def test_about_prints_the_explanation(capsys, pytestconfig):
    assert main(argv=["about"]) == 0
    assert_matches_view_golden(
        rendered=capsys.readouterr().out,
        path=FIXTURES / "about.md",
        config=pytestconfig,
    )


def test_the_explanation_uses_lf_when_windows_checked_out_its_file_with_crlf(
    monkeypatch,
):
    text = about.read_text(path=about._ABOUT_TEXT, is_replaceable=False)
    monkeypatch.setattr(
        about,
        "read_text",
        lambda **_arguments: text.replace("\r\n", "\n").replace("\n", "\r\n"),
    )

    assert "\r" not in read_about_dreamcatcher()
