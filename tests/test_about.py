"""Check the briefing for an agent that works with the user."""

from conftest import FIXTURES, assert_matches_view_golden
from records import hold_daemon_lock_for_test

from dreamcatcher.about import compose_agent_briefing
from dreamcatcher.cli import main
from dreamcatcher.config import DREAMCATCHER_CONFIG_NAME
from dreamcatcher.state import StateDirectory

CONFIG = """[[conversation]]
label = "ask-agent"
[conversation.claude]
prompt = "/dream:scout GH{issue}"
model = "opus"
effort = "high"

[[assignment]]
label = "build-carefully"
[assignment.codex]
prompt = "$dream:smith GH{issue}"
model = "gpt-5.6-sol"
effort = "high"

[[assignment]]
label = "build-quickly"
[assignment.claude]
prompt = "/dream:less GH{issue}"
model = "sonnet"
effort = "medium"
[assignment.codex]
prompt = "$dream:less GH{issue}"
model = "gpt-5.6-terra"
effort = "medium"

[[campaign]]
label = "lead-program"
[campaign.claude]
prompt = "/dream:big GH{issue}"
model = "opus[1m]"
effort = "high"
"""


def test_an_initialised_checkout_briefs_from_its_routes_and_running_daemon(
    tmp_path, pytestconfig
):
    (tmp_path / DREAMCATCHER_CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    state = StateDirectory(root=tmp_path)
    hold_daemon_lock_for_test(path=state.lock)

    assert_matches_view_golden(
        rendered=compose_agent_briefing(root=tmp_path),
        path=FIXTURES / "about-initialised.md",
        config=pytestconfig,
    )


def test_about_elsewhere_briefs_from_the_defaults_and_says_no_daemon_runs(
    monkeypatch, tmp_path, capsys, pytestconfig
):
    monkeypatch.chdir(tmp_path)

    assert main(argv=["about"]) == 0
    assert_matches_view_golden(
        rendered=capsys.readouterr().out,
        path=FIXTURES / "about-defaults.md",
        config=pytestconfig,
    )


def test_a_checkout_with_no_routes_says_that_none_are_configured(tmp_path):
    (tmp_path / DREAMCATCHER_CONFIG_NAME).write_bytes(b"")

    assert "No dispatch routes are configured." in compose_agent_briefing(root=tmp_path)
