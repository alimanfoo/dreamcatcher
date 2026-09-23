"""Test the supported rendered-view golden workflow."""

from unittest.mock import MagicMock

import pytest
from conftest import assert_matches_view_golden


def test_a_normal_run_does_not_rewrite_a_stale_golden(tmp_path):
    path = tmp_path / "view.txt"
    original = b"old\r\n"
    path.write_bytes(original)
    config = MagicMock(spec=pytest.Config)
    config.getoption.return_value = False

    with pytest.raises(AssertionError):
        assert_matches_view_golden(rendered="new\n", path=path, config=config)

    assert path.read_bytes() == original


def test_a_regeneration_run_writes_exact_utf_8_bytes(tmp_path):
    path = tmp_path / "view.txt"
    path.write_bytes(b"old\r\n")
    rendered = "new caf\N{LATIN SMALL LETTER E WITH ACUTE}\nline\n"
    config = MagicMock(spec=pytest.Config)
    config.getoption.return_value = True

    assert_matches_view_golden(rendered=rendered, path=path, config=config)

    assert path.read_bytes() == b"new caf\xc3\xa9\nline\n"
