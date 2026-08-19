from importlib.metadata import version

import pytest

from dreamcatcher.cli import main


def test_version_prints_the_installed_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == version("dreamcatcher")


@pytest.mark.parametrize("verb", ["run", "scry"])
def test_a_verb_is_not_implemented_yet(verb, capsys):
    assert main([verb]) == 1
    assert verb in capsys.readouterr().err


def test_a_bare_invocation_asks_for_a_verb(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([])

    assert exit_info.value.code == 2
    assert "verb" in capsys.readouterr().err
