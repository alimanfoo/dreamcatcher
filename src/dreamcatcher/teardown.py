"""Hold a child process, so the daemon can end it and everything it started.

Every platform difference in how dreamcatcher runs a child process lives here.
On POSIX a child leads a process group of its own, and the daemon signals that
group, so one signal reaches everything that the round started, and nothing
else. On
Windows a child goes into a Job Object of its own, which Windows empties when
the daemon terminates the job, and again when the daemon exits and its last
handle on the job closes. So a round on Windows dies with the daemon that
started it.

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
    import ctypes
    from ctypes import wintypes

    # Kill everything left in the job when its last handle closes. That is what
    # ends a round when the daemon exits, however the daemon exits.
    KILL_ON_CLOSE = 0x2000

    # The class of limits that KILL_ON_CLOSE belongs to, which
    # SetInformationJobObject asks for by number.
    EXTENDED_LIMIT_INFORMATION = 9

    # What a job needs of a process to hold it: enough to put it in the job,
    # and enough to end it there.
    SET_QUOTA = 0x0100
    TERMINATE = 0x0001

    # What a terminated job reports as the exit status of everything in it.
    KILLED = 1

    class BasicLimitInformation(ctypes.Structure):
        """What Windows calls JOBOBJECT_BASIC_LIMIT_INFORMATION."""

        _fields_ = (
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        )

    class IoCounters(ctypes.Structure):
        """What Windows calls IO_COUNTERS."""

        _fields_ = tuple(
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        )

    class ExtendedLimitInformation(ctypes.Structure):
        """What Windows calls JOBOBJECT_EXTENDED_LIMIT_INFORMATION."""

        _fields_ = (
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        )

    # A handle is a pointer, so every call that hands one back or takes one is
    # declared. Left to itself ctypes reads a returned handle as a 32-bit int,
    # which loses the top half of one.
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _kernel.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _kernel.OpenProcess.restype = wintypes.HANDLE
    _kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _kernel.CloseHandle.argtypes = (wintypes.HANDLE,)

    # Nothing puts a child in a group that Windows can signal, so the job standing
    # for each running child is held here until the child has been let go of.
    _jobs: dict[int, int] = {}

    def contain(pid: int) -> None:
        """Put the child at pid, and whatever it starts, in a job of its own."""
        job = _kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = KILL_ON_CLOSE
        _kernel.SetInformationJobObject(
            job,
            EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        process = _kernel.OpenProcess(SET_QUOTA | TERMINATE, False, pid)
        _kernel.AssignProcessToJobObject(job, process)
        _kernel.CloseHandle(process)
        _jobs[pid] = job

    def kill(pid: int) -> None:
        """End the child at pid and everything it started."""
        job = _jobs.pop(pid, None)
        if job is not None:
            _kernel.TerminateJobObject(job, KILLED)
            _kernel.CloseHandle(job)

    def release(pid: int) -> None:
        """Let go of the child at pid, now that it has ended."""
        job = _jobs.pop(pid, None)
        if job is not None:
            _kernel.CloseHandle(job)

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
