"""Hold a child process, so the daemon can end it and everything it started.

How a child process is ended differs by platform, and that difference lives here
alone. On POSIX a child leads a process group of its own, and the daemon signals
that group, so one signal reaches everything that the round started, and nothing
else. On Windows a child goes into a Job Object of its own, which Windows empties
when the daemon terminates the job, and again when the daemon exits and its last
handle on the job closes. So a round on Windows dies with the daemon that started
it.

A child and everything it starts make a tree, and teardown holds the tree
rather than the one child. That is what makes this right however the harness was
installed. A .cmd runs through cmd.exe, and even a real executable can be a
launcher that starts the program that the daemon meant to run, so the child that
the daemon knows about is often not the one doing the work.
"""

import sys

# Whether to ask for the child to lead a session, and so a process group, of its
# own. That is what POSIX teardown signals. Windows holds a child in a Job
# Object instead, where asking for a session of its own would say nothing.
OWN_SESSION = sys.platform != "win32"

if sys.platform == "win32":  # pragma: no cover
    import win32api
    import win32con
    import win32job

    # What everything left in a terminated job reports as the status it ended
    # with.
    KILLED = 1

    # Nothing puts a child in a group that Windows can signal, so a job stands
    # for each running child. The job is held here until the child is let go of,
    # because closing the last handle on it is what kills what is left inside.
    _jobs: dict[int, object] = {}

    def contain(pid: int) -> None:
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

    def kill(pid: int) -> None:
        """End the child at pid and everything it started."""
        job = _jobs.pop(pid, None)
        if job is not None:
            win32job.TerminateJobObject(job, KILLED)
            job.Close()

    def release(pid: int) -> None:
        """Let go of the child at pid, now that it has ended."""
        job = _jobs.pop(pid, None)
        if job is not None:
            job.Close()

else:  # pragma: no cover
    import os
    import signal
    from contextlib import suppress

    def contain(pid: int) -> None:
        """Nothing to do: the child already leads a process group of its own."""

    def kill(pid: int) -> None:
        """End the child at pid and everything it started."""
        # The child leads the group, so its pid is the group's id. A group that
        # has already gone is a round that has already ended, which is what the
        # caller wanted.
        with suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)

    def release(pid: int) -> None:
        """Nothing to do: a process group needs no handle to hold it."""
