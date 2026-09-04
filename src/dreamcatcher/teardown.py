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

The tree is ended when the child ends by itself, as well as when the daemon
kills it, so one call serves both.
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
    # for each running child. The job is held here until the child's tree is
    # ended, because closing the last handle on it is what kills what is left
    # inside.
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

    def end(pid: int) -> None:
        """End the child at pid and everything it started."""
        job = _jobs.pop(pid, None)
        if job is not None:
            win32job.TerminateJobObject(job, KILLED)
            job.Close()

else:  # pragma: no cover
    import os
    import signal
    from contextlib import suppress

    def contain(pid: int) -> None:
        """Nothing to do: the child already leads a process group of its own."""

    def end(pid: int) -> None:
        """End the child at pid and everything it started.

        A group with nothing left in it is a round that has already ended,
        which is what the caller wanted, so that reads as done rather than as
        a failure.
        """
        # The child leads the group, so its pid is the group's id. A caller
        # that has reaped the child has let go of that pid, and in principle
        # the operating system could have given it to somebody else by now.
        # Only in principle: a pid stays taken while any process still has it
        # as a group id, so the group has to be empty first, and then the new
        # owner has to lead a group of its own, all before the next
        # instruction. Closing the window would mean waiting for a child
        # without reaping it, and there is no call for that on every platform,
        # since os.waitid is not on macOS.
        with suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)
