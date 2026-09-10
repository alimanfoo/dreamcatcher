"""Report the invisible characters in a file.

Unicode's format category holds the zero-width marks, the bidirectional
overrides, the word joiner and the byte-order mark. Agents emit them by
accident, and no reviewer spots them in a diff.
"""

import sys
import unicodedata
from collections.abc import Iterator, Sequence
from pathlib import Path

INVISIBLE_CATEGORY = "Cf"


def describe(*, character: str) -> str:
    """Return the character's code point and its Unicode name."""
    return f"U+{ord(character):04X} {unicodedata.name(character)}"


def find_invisible_characters(*, text: str) -> Iterator[tuple[int, int, str]]:
    """Yield the line, the column and the name of each invisible character."""
    for number, line in enumerate(text.split("\n"), start=1):
        for column, character in enumerate(line, start=1):
            if unicodedata.category(character) == INVISIBLE_CATEGORY:
                yield number, column, describe(character=character)


def main(*, paths: Sequence[str]) -> int:
    """Name every invisible character in the given files, and fail if any."""
    found = False
    for path in paths:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        for number, column, name in find_invisible_characters(text=text):
            print(f"{path}:{number}:{column} {name}")
            found = True
    return int(found)


if __name__ == "__main__":
    sys.exit(main(paths=sys.argv[1:]))
