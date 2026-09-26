"""Exercise web interactions that depend on a real browser layout."""

from collections.abc import Iterator

import pytest
from playwright.sync_api import Locator, Page, expect
from web_browser import (
    BROWSER_ASSIGNMENT_IDENTIFIER,
    create_fabricated_web_app,
    serve_web_app,
)

pytestmark = pytest.mark.browser

FEED_IS_AT_END = """() => {
  const feed = document.querySelector(".feed-records");
  return feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 1;
}"""


@pytest.fixture
def live_web(tmp_path, daemon) -> Iterator[str]:
    """Serve the fabricated web app for one browser test."""
    application = create_fabricated_web_app(root=tmp_path)
    with serve_web_app(application=application) as address:
        yield address


def locate_first_line_of_round(*, page: Page, number: int) -> Locator:
    """Locate the first feed line beneath one round boundary."""
    return page.locator(f"#feed-round-{number} + .feed-line")


def test_a_round_link_brings_its_round_into_view_from_the_tail(
    page: Page,
    live_web: str,
) -> None:
    page.goto(f"{live_web}/assignments/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    page.wait_for_function(FEED_IS_AT_END)
    second_round = locate_first_line_of_round(page=page, number=2)
    expect(second_round).not_to_be_in_viewport()

    page.get_by_role("link", name="02 address feedback").click()
    expect(second_round).to_be_in_viewport()

    page.get_by_role("link", name="01 implement").click()
    expect(locate_first_line_of_round(page=page, number=1)).to_be_in_viewport()
