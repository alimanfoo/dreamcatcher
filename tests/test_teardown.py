import sys
from contextlib import suppress

import psutil

from dreamcatcher.commands import spawn

# A child that starts a child of its own, says which process that is, and then
# waits. So a kill that reached the child alone would leave the other running.
STARTS_A_CHILD = (
    "import subprocess, sys, time\n"
    "waiting = [sys.executable, '-c', 'import time; time.sleep(60)']\n"
    "print(subprocess.Popen(waiting).pid, flush=True)\n"
    "time.sleep(60)\n"
)


def gone(pid: int) -> bool:
    """Wait a while for the process at pid to end, and say whether it did."""
    with suppress(psutil.NoSuchProcess):
        psutil.Process(pid).wait(timeout=30)
    return not psutil.pid_exists(pid)


def test_a_kill_reaches_what_the_child_started(tmp_path):
    child = spawn(sys.executable, "-c", STARTS_A_CHILD, cwd=tmp_path)
    grandchild = int(child.out.readline())

    child.kill()
    child.wait()

    assert gone(grandchild)
    assert gone(child.pid)


def test_a_kill_after_the_child_ended_leaves_its_pid_alone(tmp_path):
    child = spawn(sys.executable, "-c", "print('done')", cwd=tmp_path)

    assert child.wait() == 0

    # Nothing to end, and by now the pid could be somebody else's, so this
    # signals nothing at all.
    child.kill()
