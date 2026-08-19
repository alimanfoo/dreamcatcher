from importlib.metadata import version

import pytest

from dreamcatcher.cli import main


def test_version_prints_the_installed_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == version("dreamcatcher")


@pytest.mark.parametrize(
    ("argv", "verb"),
    [([], "run"), (["run"], "run"), (["scry"], "scry")],
)
def test_a_verb_is_not_implemented_yet(argv, verb, capsys):
    assert main(argv) == 1
    assert verb in capsys.readouterr().err
