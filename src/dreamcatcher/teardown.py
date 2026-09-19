"""Hold a child process, so the daemon can end it and everything it started.

How a child process is ended differs by platform, and that difference lives here
alone. On POSIX a child leads a process group of its own, and the daemon signals
that group, so one signal reaches whatever the round left in that group, and
nothing else. What a round started can still get away: a process that starts a
session of its own has left the group, and no signal to the group reaches it.
On Windows a child goes into a Job Object of its own, which Windows empties
when the daemon terminates the job, and again when the daemon exits and its last
handle on the job closes. So a round on Windows dies with the daemon that started
it.

A child and everything it starts make a tree, and teardown holds the tree
rather than the one child. That is what makes this right however the harness was
installed. A .cmd runs through cmd.exe, and even a real executable can be a
launcher that starts the program that the daemon meant to run, so the child that
the daemon knows about is often not the one doing the work.

The tree is ended when the child ends by itself, as well as when the daemon
kills it, so one call serves both. Without that, a POSIX round that finished
normally would leave whatever it started running until the machine restarts,
because nothing else ever ends it. Windows has no such leak.
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
        """Put the child at pid, and whatever it starts, in a job of its own."""
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
        """End the child at pid and everything it started."""
        job = _jobs.pop(pid, None)
        if job is not None:
            win32job.TerminateJobObject(job, WINDOWS_TERMINATED_PROCESS_STATUS)
            job.Close()

else:  # pragma: no cover
    import os
    import signal
    from contextlib import suppress

    def contain_process_tree(*, pid: int) -> None:
        """Nothing to do: the child already leads a process group of its own."""

    def end_process_tree(*, pid: int) -> None:
        """End the child at pid and everything it started.

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
