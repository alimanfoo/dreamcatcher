"""Serve representative fabricated pages for browser inspection."""

from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from web_browser import (
    BROWSER_ASSIGNMENT_IDENTIFIER,
    serve_fabricated_web,
)

PAGES = (
    ("Home", "/"),
    ("Working assignment", f"/work/{BROWSER_ASSIGNMENT_IDENTIFIER}"),
    ("Complete assignment", "/work/GH12-20260819-184158-assignment"),
    ("Cancelled assignment", "/work/GH70-20260819-184158-assignment"),
    ("Faulted assignment", "/work/GH9-20260819-184158-assignment"),
    ("Waiting assignment", "/work/GH44-20260819-184158-assignment"),
    ("Conversation", "/work/GH8-20260819-184158-conversation"),
    ("Campaign", "/work/GH60-20260819-184158-campaign"),
)


def main() -> None:
    """Serve fabricated pages and print their addresses until interrupted."""
    with (
        TemporaryDirectory(prefix="dreamcatcher-web-") as directory,
        serve_fabricated_web(root=Path(directory)) as address,
    ):
        for label, path in PAGES:
            print(f"{label}: {address}{path}", flush=True)
        with suppress(KeyboardInterrupt):
            Event().wait()


if __name__ == "__main__":
    main()
