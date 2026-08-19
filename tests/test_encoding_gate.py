import pytest


def test_a_read_with_no_encoding_fails_the_suite(tmp_path):
    probe = tmp_path / "probe.txt"
    probe.write_text("probe", encoding="utf-8")

    with pytest.raises(EncodingWarning):
        probe.open().close()
