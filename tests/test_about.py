"""Check the briefing that explains dreamcatcher to the user's agent."""

from conftest import FIXTURES, assert_matches_view_golden
from records import hold_daemon_lock_for_test

import dreamcatcher.about as about
from dreamcatcher.about import compose_agent_briefing
from dreamcatcher.cli import main
from dreamcatcher.config import DREAMCATCHER_CONFIG_NAME
from dreamcatcher.state import StateDirectory


def test_a_configured_checkout_points_to_its_routes_and_running_daemon(
    tmp_path, pytestconfig
):
    (tmp_path / DREAMCATCHER_CONFIG_NAME).write_bytes(b"")
    state = StateDirectory(root=tmp_path)
    hold_daemon_lock_for_test(path=state.lock)

    assert_matches_view_golden(
        rendered=compose_agent_briefing(root=tmp_path),
        path=FIXTURES / "about-initialised.md",
        config=pytestconfig,
    )


def test_about_elsewhere_says_there_is_no_configuration_or_daemon(
    monkeypatch, tmp_path, capsys, pytestconfig
):
    monkeypatch.chdir(tmp_path)

    assert main(argv=["about"]) == 0
    assert_matches_view_golden(
        rendered=capsys.readouterr().out,
        path=FIXTURES / "about-defaults.md",
        config=pytestconfig,
    )


def test_a_briefing_uses_lf_when_windows_checked_out_its_template_with_crlf(
    monkeypatch, tmp_path
):
    template = about.read_text(path=about._BRIEFING_TEMPLATE, is_replaceable=False)
    monkeypatch.setattr(
        about,
        "read_text",
        lambda **_arguments: template.replace("\r\n", "\n").replace("\n", "\r\n"),
    )

    briefing = compose_agent_briefing(root=tmp_path)

    assert "\r" not in briefing
