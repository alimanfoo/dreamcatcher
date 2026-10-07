"""Exercise web interactions that depend on a real browser layout."""

from collections.abc import Iterator

import pytest
from playwright.sync_api import Locator, Page, expect
from web_browser import (
    BROWSER_ASSIGNMENT_IDENTIFIER,
    serve_fabricated_web,
)

pytestmark = pytest.mark.browser

FEED_IS_AT_END = """() => {
  const feed = document.querySelector(".feed-records");
  return feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 1;
}"""


@pytest.fixture
def live_web(tmp_path) -> Iterator[str]:
    """Serve the fabricated web app for one browser test."""
    with serve_fabricated_web(root=tmp_path) as address:
        yield address


def wait_for_refresh(*, page: Page) -> None:
    """Wait until the page's next refresh has been swapped in and settled."""
    page.evaluate(
        """() => new Promise((resolve) => {
          document.body.addEventListener("htmx:afterSettle", resolve, { once: true });
        })"""
    )


def locate_first_line_of_round(*, page: Page, number: int) -> Locator:
    """Locate the first feed line beneath one round boundary."""
    return page.locator(f"#feed-round-{number} + .feed-line")


def test_a_round_link_brings_its_round_into_view_from_the_tail(
    page: Page,
    live_web: str,
) -> None:
    page.goto(f"{live_web}/assignments/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    expect(page.locator("#agent-work-status")).to_have_text("working")
    expect(page.get_by_text("daemon not running", exact=True)).to_have_count(0)
    expect(page.get_by_text("resume by hand", exact=True)).to_have_count(0)
    page.wait_for_function(FEED_IS_AT_END)
    first_round = page.locator("#feed-round-1")
    first_round.evaluate(
        "element => element.style.setProperty('position', 'sticky', 'important')"
    )
    tail = page.get_by_role("button", name="TAIL ↓")
    expect(tail).to_be_hidden()
    second_round = locate_first_line_of_round(page=page, number=2)
    expect(second_round).not_to_be_in_viewport()

    page.get_by_role("link", name="02 address feedback").click()
    assert tail.is_visible()
    expect(second_round).to_be_in_viewport()

    page.get_by_role("link", name="01 implement").click()
    expect(locate_first_line_of_round(page=page, number=1)).to_be_in_viewport()
    assert first_round.evaluate(
        """element => ({
          value: element.style.getPropertyValue("position"),
          priority: element.style.getPropertyPriority("position"),
        })"""
    ) == {"value": "sticky", "priority": "important"}


def test_a_refresh_leaves_an_opened_section_open(page: Page, live_web: str) -> None:
    page.goto(live_web)
    ended = page.locator("details.ended-assignments")
    ended.locator("summary").click()
    expect(ended).to_have_attribute("open", "")

    wait_for_refresh(page=page)

    expect(ended).to_have_attribute("open", "")


def test_a_failed_home_refresh_keeps_the_dashboard_and_reports_why(
    page: Page, live_web: str
) -> None:
    page.goto(live_web)
    assignments = page.get_by_role("heading", name="Assignments")
    expect(assignments).to_be_visible()
    home_address = f"{live_web}/**"
    page.route(
        home_address,
        lambda route: route.fulfill(
            status=500,
            content_type="text/html",
            body='<p class="error-message">The status record is invalid.</p>',
        ),
    )

    alert = page.get_by_role("alert")
    expect(alert).to_contain_text(
        "Refresh failed. Showing the last successful status. "
        "The status record is invalid.",
        timeout=5_000,
    )
    expect(assignments).to_be_visible()

    page.unroute(home_address)
    wait_for_refresh(page=page)

    expect(alert).to_be_hidden()


def test_a_tail_refresh_leaves_an_opened_hand_resume_open(
    page: Page, live_web: str
) -> None:
    page.goto(f"{live_web}/conversations/8")
    hand_resume = page.locator("#agent-work-foot details")
    hand_resume.locator("summary").click()
    expect(hand_resume).to_have_attribute("open", "")

    wait_for_refresh(page=page)

    expect(hand_resume).to_have_attribute("open", "")


def test_stopping_a_round_asks_first(page: Page, live_web: str) -> None:
    page.goto(f"{live_web}/assignments/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    stop = page.get_by_role("button", name="stop round")

    page.once("dialog", lambda dialog: dialog.dismiss())
    stop.click()
    expect(stop).to_be_visible()

    page.once("dialog", lambda dialog: dialog.accept())
    stop.click()
    expect(stop).to_have_count(0)


def test_cancelling_an_assignment_asks_first(page: Page, live_web: str) -> None:
    page.goto(f"{live_web}/assignments/GH44-20260819-184158")
    cancel = page.get_by_role("button", name="cancel assignment")

    page.once("dialog", lambda dialog: dialog.dismiss())
    cancel.click()
    expect(page.locator("#agent-work-status")).to_have_text("waiting")

    page.once("dialog", lambda dialog: dialog.accept())
    cancel.click()
    expect(page.locator("#agent-work-status")).to_have_text("cancelled")
    expect(cancel).to_have_count(0)
