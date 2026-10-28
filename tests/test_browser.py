"""Exercise web interactions that depend on a real browser layout."""

import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from playwright.sync_api import Locator, Page, expect
from records import write_ending, write_round, write_tick
from status_fabrications import CAMPAIGN_CHILDREN, LOOKED_AT, compose_ended_round
from web_browser import (
    BROWSER_ASSIGNMENT_IDENTIFIER,
    serve_empty_web,
    serve_fabricated_web,
)

from dreamcatcher.agent_work import AgentWorkEndReason, find_agent_work
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildChange,
    CampaignChildNotification,
    CampaignRoundInput,
)
from dreamcatcher.documents import append_text, read_json
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler.models import SchedulerRecord
from dreamcatcher.state import StateDirectory

pytestmark = pytest.mark.browser

# Keyboard scrolling animates, so wait for two frames to agree on the position.
SETTLED_SCROLL_TOP = """async feed => {
  let top = feed.scrollTop;
  for (;;) {
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
    if (feed.scrollTop === top) {
      return top;
    }
    top = feed.scrollTop;
  }
}"""

# Record whether the tail button is hidden on every animation frame.
RECORD_TAIL_HIDDEN_PER_FRAME = """() => {
  window.tailHiddenPerFrame = [];
  const tail = document.querySelector(".feed-tail");
  const record = () => {
    window.tailHiddenPerFrame.push(tail.hidden);
    requestAnimationFrame(record);
  };
  requestAnimationFrame(record);
}"""

# The narrowest window whose side margins hold the working-agent motifs.
MOTIF_WINDOW_WIDTH = 1680

# Step every animation of each shown working-agent motif through its cycle,
# in every combination, and give the widest reach of each motif with the
# header's bottom, the motif layer's top and the content column's sides.
MEASURE_WORKING_MOTIFS = """() => {
  const layer = document.querySelector(".working-motifs");
  const content = document.querySelector(".home-content").getBoundingClientRect();
  const motifs = [...layer.children].filter(motif => motif.checkVisibility());
  const reaches = motifs.map(motif => {
    const animations = motif.getAnimations({ subtree: true });
    animations.forEach(animation => animation.pause());
    const steps = [0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1];
    let [left, right] = [Infinity, -Infinity];
    const measure = depth => {
      if (depth === animations.length) {
        const bounds = motif.getBoundingClientRect();
        left = Math.min(left, bounds.left);
        right = Math.max(right, bounds.right);
        return;
      }
      const duration = animations[depth].effect.getComputedTiming().duration;
      for (const step of steps) {
        animations[depth].currentTime = step * duration;
        measure(depth + 1);
      }
    };
    measure(0);
    return [left, right];
  });
  return {
    header: document.querySelector(".site-header").getBoundingClientRect().bottom,
    layer: layer.getBoundingClientRect().top,
    content: [content.left, content.right],
    reaches,
  };
}"""

FEED_IS_AT_END = """() => {
  const feed = document.querySelector(".feed-records");
  return feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 1;
}"""


@pytest.fixture
def live_web(tmp_path) -> Iterator[str]:
    """Serve the fabricated web app for one browser test."""
    with serve_fabricated_web(root=tmp_path) as address:
        yield address


@pytest.fixture
def empty_web(tmp_path) -> Iterator[str]:
    """Serve a daemon run with no work, so every home tab is empty."""
    with serve_empty_web(root=tmp_path) as address:
        yield address


def read_working_agents(*, page: Page) -> int:
    """Read how many agents the home page's agent capacity fact counts working."""
    capacity = page.locator(".fact", has_text="agent capacity").locator("dd")
    match = re.fullmatch(r"(\d+) of \d+ working", capacity.inner_text())
    assert match is not None
    return int(match[1])


def wait_for_refresh(*, page: Page) -> None:
    """Wait until the page's next refresh has been swapped in and settled."""
    page.evaluate(
        """() => new Promise((resolve) => {
          document.body.addEventListener("htmx:afterSettle", resolve, { once: true });
        })"""
    )


def locate_first_line_of_round(*, page: Page, number: int) -> Locator:
    """Locate the first feed line beneath one round boundary."""
    return page.locator(f"#feed-round-{number} > .round-boundary + .feed-line")


def append_feed_lines(*, root: Path, count: int) -> None:
    """Append lines to the browser assignment's last round feed in one write."""
    assignment = find_agent_work(
        state=StateDirectory(root=root), identifier=BROWSER_ASSIGNMENT_IDENTIFIER
    )
    assert assignment is not None
    last_round = assignment.rounds[-1]
    append_text(
        text="".join(
            FeedLine(
                at=last_round.started + timedelta(minutes=10, seconds=line_number),
                text=f"[Agent] appended line {line_number:02d}",
            ).render()
            for line_number in range(1, count + 1)
        ),
        path=assignment.compose_round_paths(number=last_round.number).feed,
    )


def test_a_round_link_brings_its_round_into_view_from_the_tail(
    page: Page,
    live_web: str,
) -> None:
    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    expect(page.locator("#agent-work-status")).to_have_text("working")
    expect(page.get_by_text("daemon not running", exact=True)).to_have_count(0)
    expect(page.get_by_text("resume by hand", exact=True)).to_have_count(0)
    page.wait_for_function(FEED_IS_AT_END)
    tail = page.get_by_role("button", name="TAIL ↓")
    expect(tail).to_be_hidden()
    second_round = locate_first_line_of_round(page=page, number=2)
    expect(second_round).not_to_be_in_viewport()

    page.get_by_role("link", name="02 1 post").click()
    assert tail.is_visible()
    expect(second_round).to_be_in_viewport()

    page.get_by_role("link", name="01 start").click()
    expect(locate_first_line_of_round(page=page, number=1)).to_be_in_viewport()


def test_a_round_boundary_leaves_the_top_when_its_round_does(
    page: Page,
    live_web: str,
) -> None:
    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    page.wait_for_function(FEED_IS_AT_END)

    page.get_by_role("link", name="02 1 post").click()

    page.wait_for_function(
        """() => {
          const feedTop = document.querySelector(".feed-records")
            .getBoundingClientRect().top;
          const secondRoundTop = document.querySelector("#feed-round-2")
            .getBoundingClientRect().top;
          const [first, second] = document.querySelectorAll(".round-boundary");
          return secondRoundTop <= feedTop + 1
            && first.getBoundingClientRect().bottom
              <= second.getBoundingClientRect().top;
        }"""
    )


def test_a_burst_of_feed_lines_shows_at_once_and_the_feed_follows_it(
    page: Page, live_web: str, tmp_path: Path
) -> None:
    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    page.wait_for_function(FEED_IS_AT_END)
    lines = page.locator(".feed-line")
    line_count = lines.count()

    append_feed_lines(root=tmp_path, count=30)

    expect(lines).to_have_count(line_count + 30)
    assert page.evaluate(
        """() => [...document.querySelectorAll(".feed-line")]
          .every((line) => line.getAnimations().length === 0)"""
    )
    page.wait_for_function(FEED_IS_AT_END, timeout=2_000)


def test_a_feed_scrolled_away_from_its_end_stays_put_until_the_tail_button(
    page: Page, live_web: str, tmp_path: Path
) -> None:
    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    page.wait_for_function(FEED_IS_AT_END)
    feed = page.locator(".feed-records")
    feed.hover()
    page.mouse.wheel(0, -100_000)
    page.wait_for_function('document.querySelector(".feed-records").scrollTop === 0')
    feed.evaluate('feed => feed.scrollTo({ top: 200, behavior: "instant" })')
    tail = page.get_by_role("button", name="TAIL ↓")
    expect(tail).to_be_visible()
    lines = page.locator(".feed-line")
    line_count = lines.count()

    append_feed_lines(root=tmp_path, count=5)

    expect(lines).to_have_count(line_count + 5)
    assert feed.evaluate("feed => feed.scrollTop") == 200
    expect(tail).to_be_visible()

    tail.click()

    page.wait_for_function(FEED_IS_AT_END)
    expect(tail).to_be_hidden()


def test_a_feed_scrolled_by_keyboard_stops_following_until_it_is_back_at_its_end(
    page: Page, live_web: str, tmp_path: Path
) -> None:
    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    page.wait_for_function(FEED_IS_AT_END)
    feed = page.locator(".feed-records")
    feed.evaluate("feed => feed.focus()")
    tail = page.get_by_role("button", name="TAIL ↓")
    lines = page.locator(".feed-line")

    page.keyboard.press("PageUp")

    expect(tail).to_be_visible()
    scroll_top = feed.evaluate(SETTLED_SCROLL_TOP)
    line_count = lines.count()
    append_feed_lines(root=tmp_path, count=5)
    expect(lines).to_have_count(line_count + 5)
    assert feed.evaluate("feed => feed.scrollTop") == scroll_top

    page.keyboard.press("End")

    page.wait_for_function(FEED_IS_AT_END)
    expect(tail).to_be_hidden()
    line_count = lines.count()
    append_feed_lines(root=tmp_path, count=5)
    expect(lines).to_have_count(line_count + 5)
    page.wait_for_function(FEED_IS_AT_END)


def test_a_following_feed_keeps_the_tail_button_hidden_while_it_scrolls_to_new_lines(
    page: Page, live_web: str, tmp_path: Path
) -> None:
    page.goto(f"{live_web}/work/{BROWSER_ASSIGNMENT_IDENTIFIER}")
    page.wait_for_function(FEED_IS_AT_END)
    lines = page.locator(".feed-line")
    line_count = lines.count()
    page.evaluate(RECORD_TAIL_HIDDEN_PER_FRAME)

    append_feed_lines(root=tmp_path, count=20)

    expect(lines).to_have_count(line_count + 20)
    page.wait_for_function(FEED_IS_AT_END)
    page.wait_for_function("window.tailHiddenPerFrame.length > 0")
    assert all(page.evaluate("window.tailHiddenPerFrame"))


def test_a_refresh_leaves_an_opened_section_open(page: Page, live_web: str) -> None:
    page.goto(live_web)
    ended = page.locator("#assignment-panel details.ended-work")
    ended.locator("summary").click()
    expect(ended).to_have_attribute("open", "")

    wait_for_refresh(page=page)

    expect(ended).to_have_attribute("open", "")


def read_colour(*, locator: Locator) -> str:
    """Read the computed text colour of the one element the locator finds."""
    return locator.evaluate("element => getComputedStyle(element).color")


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
@pytest.mark.parametrize("theme", ["matrix", "nature"])
def test_an_ended_card_has_a_quieter_title_and_the_same_links(
    page: Page,
    live_web: str,
    theme: str,
    color_scheme: Literal["light", "dark"],
) -> None:
    page.emulate_media(color_scheme=color_scheme)
    page.goto(f"{live_web}/?theme={theme}")
    page.locator("#assignment-panel details.ended-work summary").click()
    ended = page.locator("#GH12-20260819-184158-assignment")
    live = page.locator(f"#{BROWSER_ASSIGNMENT_IDENTIFIER}")
    expect(ended).to_be_visible()

    ended_title = read_colour(locator=ended.locator(".title"))

    assert ended_title != read_colour(locator=live.locator(".title"))
    assert ended_title == read_colour(locator=ended.locator(".card-route"))
    for link in (".issue-number", ".pr-chip", ".agent-work-open"):
        assert read_colour(locator=ended.locator(link)) == read_colour(
            locator=live.locator(link)
        ), link


CAMPAIGN_IDENTIFIER = "GH60-20260819-184158-campaign"
CHILD_ASSIGNMENT_IDENTIFIER = "GH64-20260819-184158-assignment"


def expand_campaign(*, page: Page) -> Locator:
    """Show the Campaigns tab, expand the idle campaign's children and return them."""
    page.get_by_role("tab", name="Campaigns").click()
    children = page.locator(f"#{CAMPAIGN_IDENTIFIER}-children")
    children.locator("summary").click()
    expect(children).to_have_attribute("open", "")
    return children


@pytest.mark.parametrize("theme", ["matrix", "nature"])
def test_a_closed_sub_issue_has_the_quieter_title_of_an_ended_card(
    page: Page, live_web: str, theme: str
) -> None:
    page.goto(f"{live_web}/?theme={theme}")
    children = expand_campaign(page=page)
    prefix = f"#{CAMPAIGN_IDENTIFIER}-sub-issue-"

    closed_title = read_colour(locator=children.locator(f"{prefix}69 .title"))

    assert closed_title != read_colour(locator=children.locator(f"{prefix}66 .title"))
    assert closed_title == read_colour(
        locator=children.locator(
            f"#{CAMPAIGN_IDENTIFIER}-GH63-20260819-184158-assignment .title"
        )
    )


def test_a_refresh_leaves_an_expanded_campaign_open(page: Page, live_web: str) -> None:
    page.goto(live_web)
    children = expand_campaign(page=page)
    expect(
        children.locator(".agent-work-card, .request-row, .campaign-child")
    ).to_have_count(5)

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
    expect(entries).to_have_count(5)

    observe_campaign_children(state=state, children=None)

    expect(children.locator("summary")).to_have_text("sub-issues unknown")
    expect(entries).to_have_count(0)
    expect(children).to_have_attribute("open", "")

    observe_campaign_children(state=state, children=CAMPAIGN_CHILDREN)

    expect(entries).to_have_count(5)
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


@pytest.mark.parametrize("theme", ["matrix", "nature"])
def test_a_round_that_names_sub_issues_keeps_its_summary_beside_its_number(
    page: Page, live_web: str, tmp_path: Path, theme: str
) -> None:
    write_round(
        directory=StateDirectory(root=tmp_path).work / CAMPAIGN_IDENTIFIER,
        number=2,
        record=compose_ended_round(minute=10, number=2),
        round_input=CampaignRoundInput(
            issue=60,
            children=CAMPAIGN_CHILDREN,
            notifications=[
                CampaignChildNotification(
                    issue=63,
                    changes=[
                        CampaignChildChange.HANDBACK,
                        CampaignChildChange.PULL_REQUEST,
                    ],
                ),
                CampaignChildNotification(
                    issue=64, changes=[CampaignChildChange.ADDED]
                ),
            ],
            comments=[],
            cursor=None,
            revision="abc123",
            assignment_routes=[],
        ),
    )
    page.goto(f"{live_web}/work/{CAMPAIGN_IDENTIFIER}?theme={theme}")
    expect(page.get_by_role("link", name=re.compile(r"^02 #63: "))).to_be_visible()

    layout = page.locator(".round").last.evaluate(
        """round => {
          const box = (element) => element.getBoundingClientRect();
          const centre = (element) => {
            const { x, y, width, height } = box(element);
            return document.elementFromPoint(x + width / 2, y + height / 2);
          };
          const number = box(round.querySelector(".round-number"));
          const trigger = box(round.querySelector(".round-trigger"));
          const timing = round.querySelector(".round-timing");
          const subIssue = round.querySelector(".round-trigger a");
          return {
            number: [number.right, number.bottom],
            trigger: [trigger.left, trigger.top, trigger.bottom],
            timing_top: box(timing).top,
            timing_target: centre(timing).className,
            sub_issue_target: centre(subIssue) === subIssue,
          };
        }"""
    )

    number_right, number_bottom = layout["number"]
    trigger_left, trigger_top, trigger_bottom = layout["trigger"]
    assert number_right <= trigger_left
    assert trigger_top < number_bottom
    assert layout["timing_top"] >= trigger_bottom
    assert layout["timing_target"] == "round-link"
    assert layout["sub_issue_target"]


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

    assignments.press("Alt+ArrowLeft")
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


def test_the_address_names_the_home_tab_so_back_and_forward_move_between_tabs(
    page: Page, live_web: str
) -> None:
    page.goto(f"{live_web}/#conversation")
    assignments = page.get_by_role("tab", name="Assignments")
    conversations = page.get_by_role("tab", name="Conversations")
    campaigns = page.get_by_role("tab", name="Campaigns")
    expect(conversations).to_have_attribute("aria-selected", "true")

    campaigns.click()
    expect(page).to_have_url(f"{live_web}/#campaign")
    campaigns.press("ArrowRight")
    expect(page).to_have_url(f"{live_web}/#assignment")
    expect(assignments).to_have_attribute("aria-selected", "true")

    page.go_back()
    expect(campaigns).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel", name="Campaigns")).to_be_visible()
    page.go_back()
    expect(conversations).to_have_attribute("aria-selected", "true")
    page.go_forward()
    expect(campaigns).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel", name="Conversations")).to_be_hidden()


def test_a_work_page_opened_from_a_tab_leads_home_to_that_tab(
    page: Page, live_web: str
) -> None:
    page.goto(live_web)
    page.get_by_role("tab", name="Campaigns").click()
    page.get_by_role("link", name=f"Open campaign {CAMPAIGN_IDENTIFIER}").click()
    expect(page).to_have_url(f"{live_web}/work/{CAMPAIGN_IDENTIFIER}")

    page.get_by_role("link", name="< home").click()

    expect(page).to_have_url(f"{live_web}/#campaign")
    expect(page.get_by_role("tab", name="Campaigns")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.get_by_role("tabpanel", name="Campaigns")).to_be_visible()


def test_switching_theme_keeps_the_selected_home_tab(page: Page, live_web: str) -> None:
    page.goto(live_web)
    page.get_by_role("tab", name="Campaigns").click()

    page.get_by_role("link", name="Nature").click()

    expect(page).to_have_url(f"{live_web}/?theme=nature#campaign")
    expect(page.get_by_role("tab", name="Campaigns")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.get_by_role("tabpanel", name="Campaigns")).to_be_visible()


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


@pytest.mark.parametrize(
    ("path", "kept"),
    [
        ("", "#home [role=tab]"),
        (f"/work/{BROWSER_ASSIGNMENT_IDENTIFIER}", ".feed-line"),
    ],
    ids=["home", "work"],
)
def test_a_refresh_that_reaches_no_server_keeps_the_page_and_points_to_the_terminal(
    page: Page, live_web: str, path: str, kept: str
) -> None:
    page.goto(f"{live_web}{path}")
    kept_content = page.locator(kept)
    expect(kept_content.first).to_be_visible()
    kept_count = kept_content.count()
    every_address = f"{live_web}/**"
    page.route(every_address, lambda route: route.abort())

    alert = page.get_by_role("alert")
    expect(alert).to_have_text(
        "Refresh failed. Check the terminal running dreamcatcher.", timeout=5_000
    )
    expect(kept_content).to_have_count(kept_count)

    page.unroute(every_address)

    expect(alert).to_be_hidden(timeout=5_000)


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
    expect(
        page.locator(f"#feed-round-{last_round.number}").get_by_text("after repair")
    ).to_have_count(1)
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
    expect(page.locator("#agent-work-status")).to_have_text("cancelled")
    expect(cancel).to_have_count(0)


def test_a_tail_refresh_hides_the_detail_once_the_work_ends(
    page: Page, live_web: str, tmp_path: Path
) -> None:
    identifier = "GH44-20260819-184158-assignment"
    page.goto(f"{live_web}/work/{identifier}")
    detail = page.locator("#agent-work-detail")
    expect(detail).to_be_visible()

    write_ending(
        directory=StateDirectory(root=tmp_path).work / identifier,
        reason=AgentWorkEndReason.CANCELLED,
        at=LOOKED_AT,
    )

    expect(page.locator("#agent-work-status")).to_have_text("cancelled")
    expect(detail).to_be_hidden()


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
    expect(page.locator(".status-fault").first).to_have_css(
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
    body = page.locator("body")
    steps = (
        (None, "night", "0"),
        ("00:01:00", "day", "1"),
        ("11:59:00", "day", "1"),
        ("00:01:00", "night", "0"),
    )
    for advance, sky, sun_opacity in steps:
        if advance is not None:
            page.clock.fast_forward(advance)
        expect(root).to_have_attribute("data-sky", sky)
        assert (
            body.evaluate('element => getComputedStyle(element, "::before").opacity')
            == sun_opacity
        )


@pytest.mark.parametrize(
    ("theme", "hour"), [("matrix", 12), ("nature", 12), ("nature", 21)]
)
def test_working_motifs_stay_in_the_margins_beneath_the_header(
    page: Page, live_web: str, theme: str, hour: int
) -> None:
    page.clock.install(time=datetime(2026, 10, 11, hour, 0))
    page.set_viewport_size({"width": MOTIF_WINDOW_WIDTH, "height": 900})
    page.goto(f"{live_web}/?theme={theme}")

    geometry = page.evaluate(MEASURE_WORKING_MOTIFS)

    assert len(geometry["reaches"]) == read_working_agents(page=page)
    assert geometry["layer"] >= geometry["header"]
    content_left, content_right = geometry["content"]
    for left, right in geometry["reaches"]:
        assert right <= content_left or left >= content_right


@pytest.mark.parametrize("theme", ["matrix", "nature"])
def test_working_motifs_hide_where_the_margins_cannot_hold_them(
    page: Page, live_web: str, theme: str
) -> None:
    page.set_viewport_size({"width": MOTIF_WINDOW_WIDTH - 1, "height": 900})
    page.goto(f"{live_web}/?theme={theme}")

    expect(page.locator(".working-motifs")).to_be_hidden()


@pytest.mark.parametrize("theme", ["matrix", "nature"])
def test_working_motifs_keep_still_and_out_of_sight_under_reduced_motion(
    page: Page, live_web: str, theme: str
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.set_viewport_size({"width": MOTIF_WINDOW_WIDTH, "height": 900})
    page.goto(f"{live_web}/?theme={theme}")

    motifs = page.locator(".working-motifs > *")
    expect(motifs).not_to_have_count(0)
    shown_or_moving = motifs.evaluate_all(
        """motifs => motifs.filter(motif =>
          motif.checkVisibility({ opacityProperty: true })
          || motif.getAnimations({ subtree: true }).length > 0
        ).length"""
    )
    assert shown_or_moving == 0


def test_nature_drops_a_seed_by_day_and_lights_a_firefly_by_night(
    page: Page, live_web: str
) -> None:
    page.clock.install(time=datetime(2026, 10, 11, 17, 59))
    page.set_viewport_size({"width": MOTIF_WINDOW_WIDTH, "height": 900})
    page.goto(live_web)
    working_agents = read_working_agents(page=page)
    seeds = page.locator(".falling-seed").filter(visible=True)
    fireflies = page.locator(".firefly").filter(visible=True)

    expect(seeds).to_have_count(working_agents)
    expect(fireflies).to_have_count(0)

    page.clock.fast_forward("00:01:00")

    expect(seeds).to_have_count(0)
    expect(fireflies).to_have_count(working_agents)


@pytest.mark.parametrize(
    ("theme", "hour", "motif"),
    [
        ("matrix", 12, "empty-rain-column"),
        ("nature", 12, "rising-seed"),
        ("nature", 21, "firefly"),
    ],
)
def test_an_empty_tab_holds_its_motif_field_beneath_its_hint(
    page: Page, empty_web: str, theme: str, hour: int, motif: str
) -> None:
    page.clock.install(time=datetime(2026, 10, 11, hour, 0))
    page.goto(f"{empty_web}/?theme={theme}")
    panel = page.locator("#assignment-panel")
    hint = panel.locator(".empty")
    field = panel.locator(".empty-field")

    expect(field).to_be_visible()
    shown_motifs = field.evaluate(
        """field => [...new Set([...field.children]
          .filter(motif => motif.checkVisibility())
          .map(motif => motif.className))]"""
    )
    assert shown_motifs == [motif]
    hint_bottom = hint.evaluate("hint => hint.getBoundingClientRect().bottom")
    field_top = field.evaluate("field => field.getBoundingClientRect().top")
    assert field_top >= hint_bottom


@pytest.mark.parametrize(
    ("theme", "hour"), [("matrix", 12), ("nature", 12), ("nature", 21)]
)
def test_an_empty_tab_motif_field_keeps_still_under_reduced_motion(
    page: Page, empty_web: str, theme: str, hour: int
) -> None:
    page.emulate_media(reduced_motion="reduce")
    page.clock.install(time=datetime(2026, 10, 11, hour, 0))
    page.goto(f"{empty_web}/?theme={theme}")

    field = page.locator("#assignment-panel .empty-field")
    expect(field).to_be_visible()
    assert field.evaluate("field => field.getAnimations({ subtree: true }).length") == 0


@pytest.mark.parametrize("theme", ["matrix", "nature"])
@pytest.mark.parametrize("width", [390, 1280])
def test_a_card_row_keeps_its_items_within_the_row(
    page: Page,
    live_web: str,
    theme: str,
    width: int,
) -> None:
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"{live_web}/?theme={theme}")
    expect(page.get_by_label("Issue #53 dream:less")).to_be_visible()

    rows = page.locator(".card-heading, .card-route").filter(visible=True)
    for row in rows.evaluate_all(
        """rows => rows.map(row => {
          const bounds = row.getBoundingClientRect();
          const left = row.firstElementChild.getBoundingClientRect();
          const right = row.childElementCount > 1
            ? row.lastElementChild.getBoundingClientRect()
            : null;
          return {
            text: row.textContent,
            row: [bounds.left, bounds.right],
            left_width: left.width,
            right: right && [right.left, right.right],
          };
        })"""
    ):
        row_left, row_right = row["row"]
        assert row["left_width"] >= (row_right - row_left) / 2, row["text"]
        if row["right"] is not None:
            right_left, right_right = row["right"]
            assert row_left <= right_left, row["text"]
            assert right_right <= row_right, row["text"]
