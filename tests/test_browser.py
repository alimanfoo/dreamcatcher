"""Exercise web interactions that depend on a real browser layout."""

import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect
from records import write_ending, write_tick
from status_fabrications import CAMPAIGN_CHILDREN, LOOKED_AT
from web_browser import (
    BROWSER_ASSIGNMENT_IDENTIFIER,
    serve_fabricated_web,
)

from dreamcatcher.agent_work import AgentWorkEndReason, find_agent_work
from dreamcatcher.campaigns import CampaignChild
from dreamcatcher.documents import append_text, read_json
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler.models import SchedulerRecord
from dreamcatcher.state import StateDirectory

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
    ended = page.locator("#assignment-panel details.ended-work")
    ended.locator("summary").click()
    expect(ended).to_have_attribute("open", "")

    wait_for_refresh(page=page)

    expect(ended).to_have_attribute("open", "")


CAMPAIGN_IDENTIFIER = "GH60-20260819-184158-campaign"
CHILD_ASSIGNMENT_IDENTIFIER = "GH64-20260819-184158-assignment"


def expand_campaign(*, page: Page) -> Locator:
    """Show the Campaigns tab, expand the idle campaign's children and return them."""
    page.get_by_role("tab", name="Campaigns").click()
    children = page.locator(f"#{CAMPAIGN_IDENTIFIER}-children")
    children.locator("summary").click()
    expect(children).to_have_attribute("open", "")
    return children


def test_a_refresh_leaves_an_expanded_campaign_open(page: Page, live_web: str) -> None:
    page.goto(live_web)
    children = expand_campaign(page=page)
    expect(
        children.locator(".agent-work-card, .request-row, .campaign-child")
    ).to_have_count(4)

    wait_for_refresh(page=page)

    expect(children).to_have_attribute("open", "")
    expect(page.locator(f"#{CAMPAIGN_IDENTIFIER} .latest-output")).to_have_count(0)


def observe_campaign_children(
    *, state: StateDirectory, children: list[CampaignChild] | None
) -> None:
    """Rewrite the latest update so that it observed these children of the campaign."""
    tick = read_json(model=SchedulerRecord, path=state.scheduler_record)
    write_tick(
        state=state,
        tick=tick.model_copy(
            update={
                "rows": [
                    row.model_copy(update={"children": children})
                    if row.agent_work_identifier == CAMPAIGN_IDENTIFIER
                    else row
                    for row in tick.rows
                ]
            }
        ),
    )


def test_an_expanded_campaign_stays_open_while_its_children_are_unknown(
    page: Page, live_web: str, tmp_path: Path
) -> None:
    state = StateDirectory(root=tmp_path)
    page.goto(live_web)
    children = expand_campaign(page=page)
    entries = children.locator(".agent-work-card, .request-row, .campaign-child")
    expect(entries).to_have_count(4)

    observe_campaign_children(state=state, children=None)

    expect(children.locator("summary")).to_have_text("+ sub-issues unknown")
    expect(entries).to_have_count(0)
    expect(children).to_have_attribute("open", "")

    observe_campaign_children(state=state, children=CAMPAIGN_CHILDREN)

    expect(entries).to_have_count(4)
    expect(children).to_have_attribute("open", "")


def test_an_expanded_campaign_whose_parent_closes_keeps_only_its_card(
    page: Page, live_web: str, tmp_path: Path
) -> None:
    page.goto(live_web)
    expand_campaign(page=page)

    write_ending(
        directory=StateDirectory(root=tmp_path).work / CAMPAIGN_IDENTIFIER,
        reason=AgentWorkEndReason.ISSUE_CLOSED,
        at=LOOKED_AT,
    )

    ended = page.locator("#campaign-panel details.ended-work")
    expect(ended.locator(f"#{CAMPAIGN_IDENTIFIER}")).to_have_count(1)
    expect(page.locator(f"[id^='{CAMPAIGN_IDENTIFIER}-']")).to_have_count(0)


def test_a_child_assignment_shows_its_new_output_in_both_tabs(
    page: Page, live_web: str, tmp_path: Path
) -> None:
    page.goto(live_web)
    children = expand_campaign(page=page)
    child_output = children.locator(
        f"#{CAMPAIGN_IDENTIFIER}-{CHILD_ASSIGNMENT_IDENTIFIER} .latest-output"
    )
    expect(child_output).to_have_text("agent [Bash] pytest -q")
    assignment = find_agent_work(
        state=StateDirectory(root=tmp_path), identifier=CHILD_ASSIGNMENT_IDENTIFIER
    )
    assert assignment is not None
    latest = assignment.rounds[-1]
    append_text(
        text=FeedLine(
            at=latest.started + timedelta(minutes=5), text="[Bash] git push"
        ).render(),
        path=assignment.compose_round_paths(number=latest.number).feed,
    )

    expect(child_output).to_have_text("agent [Bash] git push")
    page.get_by_role("tab", name="Assignments").click()
    expect(page.locator(f"#{CHILD_ASSIGNMENT_IDENTIFIER} .latest-output")).to_have_text(
        "agent [Bash] git push"
    )


def test_home_tabs_switch_by_pointer_and_keyboard_and_survive_refresh(
    page: Page, live_web: str
) -> None:
    page.goto(live_web)
    assignments = page.get_by_role("tab", name="Assignments")
    conversations = page.get_by_role("tab", name="Conversations")
    campaigns = page.get_by_role("tab", name="Campaigns")
    assignment_panel = page.get_by_role("tabpanel", name="Assignments")
    conversation_panel = page.get_by_role("tabpanel", name="Conversations")
    campaign_panel = page.get_by_role("tabpanel", name="Campaigns")

    expect(assignments).to_have_attribute("aria-selected", "true")
    expect(assignment_panel).to_be_visible()
    expect(conversation_panel).to_be_hidden()
    expect(campaign_panel).to_be_hidden()

    assignments.press("ArrowLeft")
    expect(campaigns).to_have_attribute("aria-selected", "true")
    expect(assignment_panel).to_be_hidden()
    expect(campaign_panel).to_be_visible()

    campaigns.press("ArrowRight")
    expect(assignments).to_have_attribute("aria-selected", "true")

    assignments.press("ArrowRight")
    expect(conversations).to_have_attribute("aria-selected", "true")
    expect(conversation_panel).to_be_visible()

    conversations.press("Home")
    expect(assignments).to_have_attribute("aria-selected", "true")

    assignments.press("End")
    expect(campaigns).to_have_attribute("aria-selected", "true")

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
        "Refresh failed. Showing what the page last read. "
        "The status record is invalid.",
        timeout=5_000,
    )
    expect(assignments).to_be_visible()

    page.unroute(home_address)
    wait_for_refresh(page=page)

    expect(alert).to_be_hidden()


@pytest.mark.parametrize("theme", ["matrix", "nature"])
@pytest.mark.parametrize(
    "identifier",
    [BROWSER_ASSIGNMENT_IDENTIFIER, "GH8-20260819-184158-conversation"],
)
def test_a_failed_feed_refresh_keeps_the_feed_and_reports_why(
    page: Page, live_web: str, tmp_path: Path, identifier: str, theme: str
) -> None:
    work = find_agent_work(state=StateDirectory(root=tmp_path), identifier=identifier)
    assert work is not None
    last_round = work.rounds[-1]
    feed_path = work.compose_round_paths(number=last_round.number).feed
    page.goto(f"{live_web}/work/{identifier}?theme={theme}")
    lines = page.locator(".feed-line")
    expect(lines.first).to_be_visible()
    line_count = lines.count()
    readable_feed = feed_path.read_bytes()

    feed_path.write_bytes(readable_feed + b"\xff\n")

    alert = page.get_by_role("alert")
    expect(alert).to_be_visible(timeout=5_000)
    expect(alert).to_contain_text("Refresh failed. Showing what the page last read.")
    expect(alert).to_contain_text("is not UTF-8 text.")
    expect(lines).to_have_count(line_count)

    feed_path.write_bytes(readable_feed)
    append_text(
        text=FeedLine(at=last_round.started, text="[Agent] after repair").render(),
        path=feed_path,
    )

    expect(alert).to_be_hidden(timeout=5_000)
    expect(page.get_by_text("after repair")).to_have_count(1)
    wait_for_refresh(page=page)
    expect(lines).to_have_count(line_count + 1)


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
    expect(page.locator(".status-working").first).to_have_css(
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
