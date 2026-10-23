import sys
from unittest.mock import Mock

import pytest
from conftest import wait_for_exit

from dreamcatcher import teardown
from dreamcatcher.commands import CommandError, spawn_command

# Only Windows holds a child in a Job Object, so only Windows can refuse to.
pywintypes = pytest.importorskip("pywintypes")
win32api = pytest.importorskip("win32api")
win32job = pytest.importorskip("win32job")
win32process = pytest.importorskip("win32process")


@pytest.fixture
def handles(monkeypatch):
    """Record every handle that containment opens, and every one it closes.

    A handle reads as zero once it is closed, so each is recorded as it opens
    and as it is about to close.
    """
    opened: list[int] = []
    closed: list[int] = []
    create_job_object = win32job.CreateJobObject

    def create_and_record_job(attributes, name, /):
        """Stand in for CreateJobObject, which teardown calls by position."""
        job = create_job_object(attributes, name)
        opened.append(int(job))
        return job

    monkeypatch.setattr(win32job, "CreateJobObject", create_and_record_job)
    for name in ("OpenProcess", "OpenThread"):
        record_opening(monkeypatch=monkeypatch, name=name, opened=opened)
    close_handle = win32api.CloseHandle

    def close_and_record_handle(handle, /):
        """Stand in for CloseHandle, which teardown calls by position."""
        closed.append(int(handle))
        close_handle(handle)

    monkeypatch.setattr(win32api, "CloseHandle", close_and_record_handle)
    return opened, closed


def record_opening(*, monkeypatch, name, opened):
    """Record each handle that the win32api function name opens."""
    open_handle = getattr(win32api, name)

    def open_and_record_handle(access, is_inheritable, identifier, /):
        """Stand in for the function, which teardown calls by position."""
        handle = open_handle(access, is_inheritable, identifier)
        opened.append(int(handle))
        return handle

    monkeypatch.setattr(win32api, name, open_and_record_handle)


@pytest.mark.parametrize(
    ("module", "step"),
    [
        (win32job, "CreateJobObject"),
        (win32job, "SetInformationJobObject"),
        (win32api, "OpenProcess"),
        (win32job, "AssignProcessToJobObject"),
        (win32process, "ResumeThread"),
    ],
)
def test_a_child_whose_containment_fails_never_runs(
    tmp_path, monkeypatch, handles, module, step
):
    refusal = pywintypes.error(5, step, "Access is denied.")
    monkeypatch.setattr(module, step, Mock(side_effect=refusal))
    contained = []
    contain_process_tree = teardown.contain_process_tree

    def record_child(*, pid: int) -> None:
        contained.append(pid)
        contain_process_tree(pid=pid)

    monkeypatch.setattr(teardown, "contain_process_tree", record_child)
    mark = tmp_path / "ran"

    with pytest.raises(
        CommandError, match=rf"\[WinError 5\] {step}: Access is denied\.$"
    ):
        spawn_command(
            program=sys.executable,
            arguments=["-c", f"open({str(mark)!r}, 'w').close()"],
            cwd=tmp_path,
        )

    assert wait_for_exit(pid=contained[0])
    assert not mark.exists()
    opened, closed = handles
    assert sorted(closed) == sorted(opened)
