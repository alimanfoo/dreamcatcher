"""Contain and terminate each harness process tree.

On POSIX, each child leads a process group that termination signals as a unit.
A descendant that starts another session can escape that group. On Windows,
each child belongs to a Job Object that terminates its members when the daemon
closes the last job handle.

Cleanup runs after normal exit as well as forced termination so that descendants
do not outlive a completed round.
"""

import sys

# Whether to ask for the child to lead a session, and so a process group, of its
# own. That is what POSIX teardown signals. Windows holds a child in a Job
# Object instead, where asking for a session of its own would say nothing.
SHOULD_START_NEW_PROCESS_SESSION = sys.platform != "win32"

if sys.platform == "win32":  # pragma: no cover
    import win32api
    import win32con
    import win32job

    # What everything left in a terminated job reports as the status it ended
    # with.
    WINDOWS_TERMINATED_PROCESS_STATUS = 1

    # Nothing puts a child in a group that Windows can signal, so a job stands
    # for each running child. The job is held here until the child's tree is
    # ended, because closing the last handle on it is what kills what is left
    # inside.
    _jobs: dict[int, object] = {}

    def contain_process_tree(*, pid: int) -> None:
        """Place the child and its descendants in a dedicated Job Object."""
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation
        )
        limits["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32job.SetInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation, limits
        )
        child = win32api.OpenProcess(
            win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid
        )
        win32job.AssignProcessToJobObject(job, child)
        child.Close()
        _jobs[pid] = job

    def end_process_tree(*, pid: int) -> None:
        """Terminate the child's Job Object and release its handle."""
        job = _jobs.pop(pid, None)
        if job is not None:
            win32job.TerminateJobObject(job, WINDOWS_TERMINATED_PROCESS_STATUS)
            job.Close()

else:  # pragma: no cover
    import os
    import signal
    from contextlib import suppress

    def contain_process_tree(*, pid: int) -> None:
        """Leave the child in the process group that spawn created for it."""

    def end_process_tree(*, pid: int) -> None:
        """Terminate the process group that the child leads.

        A group with nothing left in it is a round that has already ended,
        which is what the caller wanted, so that reads as done rather than as
        a failure.
        """
        # The child leads the group, so its pid is the group's id. A caller
        # that has collected the child's status has let go of that pid, so
        # between that statement and this one the number could come to belong
        # to a stranger. That window is two adjacent statements wide, and it
        # is accepted. Closing it would mean waiting for the child without
        # collecting its status, which is os.waitid with WNOWAIT, and macOS
        # has that only from Python 3.13 while this project pins 3.12. The
        # line would be a branch on the Python version inside this platform
        # branch, and no one runner can cover both of its arms.
        with suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)
