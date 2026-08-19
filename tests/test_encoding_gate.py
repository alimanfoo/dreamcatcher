"""Prove the EncodingWarning gate is armed.

Run pytest with PYTHONWARNDEFAULTENCODING=1. Without it the interpreter never
emits EncodingWarning, and this test fails.
"""

import pytest


def test_the_encoding_gate_is_armed(tmp_path):
    probe = tmp_path / "probe.txt"
    probe.write_text("probe", encoding="utf-8")

    with pytest.raises(EncodingWarning):
        probe.open().close()
