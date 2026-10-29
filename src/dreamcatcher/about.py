"""Read the text that explains dreamcatcher to the user and their agent."""

from pathlib import Path

from dreamcatcher.documents import read_text

_ABOUT_TEXT = Path(__file__).with_name("about.md")


def read_about_dreamcatcher() -> str:
    """Return the text that explains what dreamcatcher can do and how it works.

    The text has LF line endings, however Git checked out its file.
    """
    return read_text(path=_ABOUT_TEXT, is_replaceable=False).replace("\r\n", "\n")
