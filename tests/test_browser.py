"""Exercise web interactions that depend on a real browser layout."""

import re
from collections.abc import Iterator
from datetime import datetime

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
    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
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

    page.get_by_role("link", name="02 1 post").click()
    assert tail.is_visible()
    expect(second_round).to_be_in_viewport()

    page.get_by_role("link", name="01 start").click()
    expect(locate_first_line_of_round(page=page, number=1)).to_be_in_viewport()
    assert first_round.evaluate(
        """element => ({
          value: element.style.getPropertyValue("position"),
          priority: element.style.getPropertyPriority("position"),
        })"""
    ) == {"value": "sticky", "priority": "important"}


def test_a_refresh_leaves_an_opened_section_open(page: Page, live_web: str) -> None:
    page.goto(live_web)
    ended = page.locator("details.ended-work")
    ended.locator("summary").click()
    expect(ended).to_have_attribute("open", "")

    wait_for_refresh(page=page)

    expect(ended).to_have_attribute("open", "")


def test_home_tabs_switch_by_pointer_and_keyboard_and_survive_refresh(
    page: Page, live_web: str
) -> None:
    page.goto(live_web)
    assignments = page.get_by_role("tab", name="Assignments")
    conversations = page.get_by_role("tab", name="Conversations")
    assignment_panel = page.get_by_role("tabpanel", name="Assignments")
    conversation_panel = page.get_by_role("tabpanel", name="Conversations")

    expect(assignments).to_have_attribute("aria-selected", "true")
    expect(assignment_panel).to_be_visible()
    expect(conversation_panel).to_be_hidden()

    assignments.press("ArrowLeft")
    expect(conversations).to_have_attribute("aria-selected", "true")
    expect(assignment_panel).to_be_hidden()
    expect(conversation_panel).to_be_visible()

    conversations.press("ArrowRight")
    expect(assignments).to_have_attribute("aria-selected", "true")

    assignments.press("ArrowRight")
    expect(conversations).to_have_attribute("aria-selected", "true")

    conversations.press("Home")
    expect(assignments).to_have_attribute("aria-selected", "true")

    assignments.press("End")
    expect(conversations).to_have_attribute("aria-selected", "true")

    assignments.click()
    expect(assignments).to_have_attribute("aria-selected", "true")
    conversations.click()
    wait_for_refresh(page=page)
    expect(conversations).to_have_attribute("aria-selected", "true")
    expect(assignments).to_have_attribute("aria-selected", "false")
    expect(assignment_panel).to_be_hidden()
    expect(conversation_panel).to_be_visible()

    conversations.press("ArrowLeft")
    expect(assignments).to_have_attribute("aria-selected", "true")
    expect(conversations).to_have_attribute("aria-selected", "false")
    expect(assignments).to_be_focused()
    expect(assignment_panel).to_be_visible()
    expect(conversation_panel).to_be_hidden()


def test_refresh_focuses_the_first_tab_when_the_selected_section_disappears(
    page: Page, live_web: str
) -> None:
    page.goto(live_web)
    conversations = page.get_by_role("tab", name="Conversations")
    conversations.click()
    expect(conversations).to_be_focused()

    page.evaluate(
        """
        () => {
          const home = document.querySelector("#home");
          document.body.dispatchEvent(new CustomEvent("htmx:beforeSwap", {
            detail: {target: home, serverResponse: home.outerHTML},
          }));
          document.querySelector("#conversation-tab").remove();
          document.querySelector("#conversation-panel").remove();
          document.body.dispatchEvent(new CustomEvent("htmx:afterSwap", {
            detail: {target: home},
          }));
        }
        """
    )

    assignments = page.get_by_role("tab", name="Assignments")
    expect(assignments).to_have_attribute("aria-selected", "true")
    expect(assignments).to_be_focused()
    expect(page.get_by_role("tabpanel", name="Assignments")).to_be_visible()


def test_a_failed_home_refresh_keeps_the_dashboard_and_reports_why(
    page: Page, live_web: str
) -> None:
    page.goto(live_web)
    assignments = page.get_by_role("tab", name="Assignments")
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
    page.goto(f"{live_web}/work/GH8-20260819-184158-conversation")
    hand_resume = page.locator("#agent-work-foot details")
    hand_resume.locator("summary").click()
    expect(hand_resume).to_have_attribute("open", "")

    wait_for_refresh(page=page)

    expect(hand_resume).to_have_attribute("open", "")


def test_stopping_a_round_asks_first(page: Page, live_web: str) -> None:
    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    stop = page.get_by_role("button", name="stop round")

    page.once("dialog", lambda dialog: dialog.dismiss())
    stop.click()
    expect(stop).to_be_visible()

    page.once("dialog", lambda dialog: dialog.accept())
    stop.click()
    expect(stop).to_have_count(0)


def test_cancelling_an_assignment_asks_first(page: Page, live_web: str) -> None:
    page.goto(f"{live_web}/work/GH44-20260819-184158-assignment")
    cancel = page.get_by_role("button", name="cancel assignment")

    page.once("dialog", lambda dialog: dialog.dismiss())
    cancel.click()
    expect(page.locator("#agent-work-status")).to_have_text("waiting")

    page.once("dialog", lambda dialog: dialog.accept())
    cancel.click()
    expect(page.locator("#agent-work-status")).to_have_text("ended")
    expect(cancel).to_have_count(0)


def test_dark_nature_uses_the_dusk_palette_and_follows_the_night(
    page: Page,
    live_web: str,
) -> None:
    page.emulate_media(color_scheme="dark")
    page.clock.install(time=datetime(2026, 10, 11, 20, 0))
    page.goto(live_web)

    expect(page.locator("html")).to_have_css("background-color", "rgb(26, 24, 48)")
    expect(page.locator("body")).to_have_css("color", "rgb(236, 230, 220)")
    expect(page.locator(".status-working")).to_have_css(
        "color",
        "rgb(179, 203, 166)",
    )
    expect(page.locator(".status-routing-conflict").first).to_have_css(
        "color",
        "rgb(22, 21, 42)",
    )
    expect(page.locator(".agent-work-card").first).to_have_css(
        "border-bottom-color",
        "rgba(236, 230, 220, 0.1)",
    )

    body = page.locator("body")
    times = (
        (None, 20.6667, "1"),
        ("04:00:00", 50, "1"),
        ("04:00:00", 79.3333, "1"),
        ("08:00:00", None, "0"),
    )
    for advance, expected_position, expected_opacity in times:
        if advance is not None:
            page.clock.fast_forward(advance)
        celestial_style = body.evaluate(
            """element => {
              const style = getComputedStyle(element, "::before");
              return { backgroundImage: style.backgroundImage, opacity: style.opacity };
            }"""
        )
        assert celestial_style["opacity"] == expected_opacity
        if expected_position is not None:
            position_match = re.search(
                r"circle at ([\d.]+)% 6%",
                celestial_style["backgroundImage"],
            )
            assert position_match is not None
            assert float(position_match.group(1)) == pytest.approx(
                expected_position,
                abs=0.0001,
            )

    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    expect(page.locator(".feed-line time").first).to_have_css(
        "color",
        "rgba(236, 230, 220, 0.56)",
    )

    page.emulate_media(color_scheme="light")
    expect(page.locator("html")).to_have_css("background-color", "rgb(239, 230, 214)")


def test_nature_shows_exactly_one_of_sun_and_moon_at_each_boundary(
    page: Page,
    live_web: str,
) -> None:
    page.clock.install(time=datetime(2026, 10, 11, 5, 59))
    page.goto(live_web)

    root = page.locator("html")
    steps = (
        (None, "0", "1"),
        ("00:01:00", "1", "0"),
        ("11:59:00", "1", "0"),
        ("00:01:00", "0", "1"),
    )
    for advance, sun_opacity, moon_opacity in steps:
        if advance is not None:
            page.clock.fast_forward(advance)
        opacities = root.evaluate(
            """element => [
              element.style.getPropertyValue("--sun-opacity"),
              element.style.getPropertyValue("--moon-opacity"),
            ]"""
        )
        assert opacities == [sun_opacity, moon_opacity]


@pytest.mark.parametrize("theme", ["matrix", "nature"])
@pytest.mark.parametrize("width", [390, 1280])
def test_a_card_heading_keeps_its_title_and_status_within_the_row(
    page: Page,
    live_web: str,
    theme: str,
    width: int,
) -> None:
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"{live_web}/?theme={theme}")
    expect(page.get_by_label("Issue #53 dream:less")).to_be_visible()

    headings = page.locator(".card-heading").filter(visible=True)
    for heading in headings.evaluate_all(
        """headings => headings.map(heading => {
          const row = heading.getBoundingClientRect();
          const title = heading.firstElementChild.getBoundingClientRect();
          const status = heading.lastElementChild.getBoundingClientRect();
          return {
            text: heading.textContent,
            row: [row.left, row.right],
            title_width: title.width,
            status: [status.left, status.right],
          };
        })"""
    ):
        row_left, row_right = heading["row"]
        status_left, status_right = heading["status"]
        assert heading["title_width"] >= (row_right - row_left) / 2, heading["text"]
        assert row_left <= status_left, heading["text"]
        assert status_right <= row_right, heading["text"]
