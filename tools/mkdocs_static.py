"""Publish the web interface's mark and sun in the documentation site.

MkDocs loads this module as a hook, because `mkdocs.yml` names it. The site
shows the same mark as the web interface and moves the same sun as its nature
theme, so it takes both files from the package rather than keeping copies.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mkdocs.structure.files import File

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files

STATIC_ROOT = Path(__file__).parents[1] / "src" / "dreamcatcher" / "static"
PUBLISHED_FILES = ("dreamcatcher-mark-ink.png", "nature.js")


def on_files(files: Files, /, *, config: MkDocsConfig) -> Files:
    """Add each published file to the site under `static/`.

    MkDocs passes the files by position.
    """
    for name in PUBLISHED_FILES:
        files.append(
            File.generated(
                config, f"static/{name}", abs_src_path=str(STATIC_ROOT / name)
            )
        )
    return files
