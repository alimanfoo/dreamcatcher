import json
import os
import shutil
from pathlib import Path

import pytest
from conftest import POSTED_BY, REPOSITORY, SMITH_CLAUDE, SMITH_CODEX, commit, git

from dreamcatcher.cli import main
from dreamcatcher.config import (
    DREAMCATCHER_CONFIG_NAME,
    AgentHarness,
    read_dreamcatcher_config,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.repository_setup import set_up_repository

LABELS = f"api repos/{REPOSITORY}/labels?per_page=100"
PERMISSION = f"repo view {REPOSITORY} --json viewerPermission"


@pytest.fixture
def checkout(cloned):
    """A main checkout of upstream, where Git has an identity to commit as."""
    git(arguments=["config", "user.name", "A Test"], cwd=cloned)
    git(arguments=["config", "user.email", "test@example.com"], cwd=cloned)
    return cloned


@pytest.fixture
def gh(fake):
    """A gh signed in with push access to a repository holding one route label."""
    stand_in = fake(program="gh")
    stand_in.replies(stdout=json.dumps({"nameWithOwner": REPOSITORY}), to="repo view")
    stand_in.replies(stdout=json.dumps({"viewerPermission": "WRITE"}), to=PERMISSION)
    stand_in.replies(stdout=json.dumps({"login": POSTED_BY}), to="api user")
    stand_in.replies(stdout=json.dumps([[{"name": "DREAM:SMITH"}]]), to=LABELS)
    stand_in.replies(stdout="", to="label create")
    return stand_in


@pytest.fixture
def installed(fake, stand_ins, monkeypatch, tmp_path):
    """Return a factory putting these harnesses on the PATH, signed in.

    A harness the developer installed for their own use often sits beside git,
    and would answer for one that a test means to be missing. So the PATH holds
    the stand-ins and a directory with git alone. Git for Windows keeps git in a
    directory of its own, and a symbolic link is a privilege there.
    """
    real_git = Path(str(shutil.which("git")))
    git_alone = real_git.parent
    if os.name != "nt":
        git_alone = tmp_path / "git-alone"
        git_alone.mkdir()
        (git_alone / "git").symlink_to(real_git)

    def install(*, programs: list[str]):
        harnesses = {}
        for program in programs:
            harnesses[program] = fake(program=program)
            harnesses[program].replies(stdout="")
        monkeypatch.setenv("PATH", f"{stand_ins}{os.pathsep}{git_alone}")
        return harnesses

    return install


def test_a_fresh_checkout_is_set_up_for_both_harnesses(checkout, gh, installed, capsys):
    harnesses = installed(programs=["claude", "codex"])

    set_up_repository(root=checkout)

    config = read_dreamcatcher_config(root=checkout)
    assert config.routed_harnesses == set(AgentHarness)
    assert [call.arguments for call in harnesses["claude"].calls] == [
        ["auth", "status"],
        ["plugin", "marketplace", "add", "alimanfoo/dream"],
        ["plugin", "install", "dream@dream", "--scope", "user"],
    ]
    assert [call.arguments for call in harnesses["codex"].calls] == [
        ["login", "status"],
        ["plugin", "marketplace", "add", "alimanfoo/dream"],
        ["plugin", "add", "dream@dream"],
    ]
    output = capsys.readouterr().out
    assert f"gh is signed in as {POSTED_BY}, who can push to {REPOSITORY}." in output
    assert "Git commits here as A Test <test@example.com>." in output
    assert f"Wrote the default {DREAMCATCHER_CONFIG_NAME}." in output
    assert output.endswith(
        "dreamcatcher is ready. Next:\n"
        f"  git add {DREAMCATCHER_CONFIG_NAME}\n"
        '  git commit -m "Configure dreamcatcher"\n'
        "  git push origin main\n"
        f"  Assign an issue to {POSTED_BY}, and label it dream:smith.\n"
        "  dreamcatcher run --harness claude\n"
    )


def test_only_the_route_labels_the_repository_lacks_are_created(
    checkout, gh, installed, capsys
):
    installed(programs=["claude", "codex"])

    set_up_repository(root=checkout)

    created = [call.arguments for call in gh.calls if call.arguments[0] == "label"]
    assert created == [
        [
            "label",
            "create",
            "dream:less",
            "--repo",
            REPOSITORY,
            "--description",
            "Start a dreamcatcher assignment",
        ],
        [
            "label",
            "create",
            "dream:scout",
            "--repo",
            REPOSITORY,
            "--description",
            "Start a dreamcatcher issue conversation",
        ],
    ]
    assert "Created the labels dream:less, dream:scout." in capsys.readouterr().out


def test_a_second_setup_leaves_the_configuration_and_labels_alone(
    checkout, gh, installed, capsys
):
    harnesses = installed(programs=["claude"])
    (checkout / DREAMCATCHER_CONFIG_NAME).write_text(SMITH_CLAUDE, encoding="utf-8")
    commit(path=checkout, message="Configure dreamcatcher")
    git(arguments=["push", "origin", "main"], cwd=checkout)
    gh.replies(stdout=json.dumps([[{"name": "dream:smith"}]]), to=LABELS)

    set_up_repository(root=checkout)

    assert (checkout / DREAMCATCHER_CONFIG_NAME).read_text(
        encoding="utf-8"
    ) == SMITH_CLAUDE
    assert ["plugin", "install", "dream@dream", "--scope", "user"] in [
        call.arguments for call in harnesses["claude"].calls
    ]
    assert not [call for call in gh.calls if call.arguments[0] == "label"]
    output = capsys.readouterr().out
    assert f"Left the existing {DREAMCATCHER_CONFIG_NAME} as it is." in output
    assert "The repository has every label that the configuration routes." in output
    assert "git add" not in output


def test_a_configuration_not_yet_on_main_comes_with_the_commands_to_push_it(
    checkout, gh, installed, capsys
):
    installed(programs=["claude"])
    (checkout / DREAMCATCHER_CONFIG_NAME).write_text(SMITH_CLAUDE, encoding="utf-8")

    set_up_repository(root=checkout)

    assert f"  git add {DREAMCATCHER_CONFIG_NAME}\n" in capsys.readouterr().out


def test_only_the_harnesses_the_configuration_routes_are_set_up(
    checkout, gh, installed
):
    harnesses = installed(programs=["claude", "codex"])
    (checkout / DREAMCATCHER_CONFIG_NAME).write_text(SMITH_CLAUDE, encoding="utf-8")

    set_up_repository(root=checkout)

    assert harnesses["claude"].calls
    assert not harnesses["codex"].calls


def test_a_harness_that_is_not_installed_is_left_out_of_the_configuration(
    checkout, gh, installed, capsys
):
    installed(programs=["claude"])

    set_up_repository(root=checkout)

    assert read_dreamcatcher_config(root=checkout).routed_harnesses == {
        AgentHarness.CLAUDE
    }
    assert "codex is not on the PATH." in capsys.readouterr().out


def test_a_configuration_routing_codex_alone_runs_on_codex(
    checkout, gh, installed, capsys
):
    harnesses = installed(programs=["codex"])

    set_up_repository(root=checkout)

    assert harnesses["codex"].calls
    assert capsys.readouterr().out.endswith("dreamcatcher run --harness codex\n")


def test_a_machine_with_no_harness_is_refused(checkout, gh, installed):
    installed(programs=[])

    with pytest.raises(ReportableError, match="Install Claude Code or Codex"):
        set_up_repository(root=checkout)


def test_a_configuration_routing_a_missing_harness_is_refused(checkout, gh, installed):
    harnesses = installed(programs=["claude"])
    (checkout / DREAMCATCHER_CONFIG_NAME).write_text(
        SMITH_CLAUDE + SMITH_CODEX, encoding="utf-8"
    )

    with pytest.raises(ReportableError, match="codex is not on the PATH"):
        set_up_repository(root=checkout)
    assert not harnesses["claude"].calls


def test_a_harness_that_is_signed_out_is_refused(checkout, gh, installed):
    harnesses = installed(programs=["claude", "codex"])
    harnesses["codex"].fails(stderr="Not logged in", to="login status")

    with pytest.raises(ReportableError, match="codex login status failed"):
        set_up_repository(root=checkout)
    assert [call.arguments for call in harnesses["codex"].calls] == [
        ["login", "status"]
    ]


def test_an_account_that_cannot_push_is_refused(checkout, gh, installed):
    installed(programs=["claude"])
    gh.replies(stdout=json.dumps({"viewerPermission": "READ"}), to=PERMISSION)

    with pytest.raises(ReportableError, match=f"{POSTED_BY} cannot push"):
        set_up_repository(root=checkout)
    assert not (checkout / DREAMCATCHER_CONFIG_NAME).exists()


def test_a_checkout_whose_origin_cannot_be_fetched_is_refused(checkout, gh, installed):
    installed(programs=["claude"])
    git(
        arguments=["remote", "set-url", "origin", str(checkout.parent / "gone.git")],
        cwd=checkout,
    )

    with pytest.raises(ReportableError, match="git fetch origin main failed"):
        set_up_repository(root=checkout)


@pytest.mark.parametrize(
    ("read", "refusal"),
    [(PERMISSION, "cannot tell whether"), (LABELS, "cannot tell which labels")],
    ids=["the push permission", "the labels"],
)
def test_a_github_read_that_fails_is_refused_with_what_gh_said(
    checkout, gh, installed, read, refusal
):
    installed(programs=["claude"])
    gh.fails(stderr="gh: could not connect to github.com", to=read)

    with pytest.raises(ReportableError, match=f"{refusal}.*could not connect"):
        set_up_repository(root=checkout)


def test_a_checkout_where_git_has_no_identity_is_refused(
    cloned, gh, installed, monkeypatch
):
    installed(programs=["claude"])
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    git(arguments=["config", "user.useConfigOnly", "true"], cwd=cloned)

    with pytest.raises(ReportableError, match="Please tell me who you are"):
        set_up_repository(root=cloned)


def test_a_directory_that_is_not_a_main_checkout_is_refused(tmp_path):
    with pytest.raises(ReportableError, match="main checkout"):
        set_up_repository(root=tmp_path)


def test_init_sets_up_the_current_directory(checkout, gh, installed, monkeypatch):
    installed(programs=["claude"])
    monkeypatch.chdir(checkout)

    assert main(argv=["init"]) == 0
    assert (checkout / DREAMCATCHER_CONFIG_NAME).is_file()
