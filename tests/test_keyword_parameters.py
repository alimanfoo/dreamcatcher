from pathlib import Path
from runpy import run_path

find_positional_parameters = run_path(
    str(Path(__file__).parents[1] / "tools" / "require_keyword_parameters.py")
)["find_positional_parameters"]


def test_a_subprocess_run_adapter_preserves_its_external_signature():
    source = """
import functools
import subprocess

@functools.wraps(subprocess.run)
def timed_run(*popenargs, **kwargs):
    pass
"""

    assert list(find_positional_parameters(text=source)) == []


def test_a_wrapper_around_an_owned_function_keeps_the_keyword_only_rule():
    source = """
import functools

def owned(*values):
    pass

@functools.wraps(owned)
def proxy(*values):
    pass
"""

    assert list(find_positional_parameters(text=source)) == [
        "4 owned takes *values by position",
        "8 proxy takes *values by position",
    ]
