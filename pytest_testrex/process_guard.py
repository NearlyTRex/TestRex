# Imports
import ctypes
import os
import signal
import subprocess
import sys
import time

# Third-party imports
import pytest

###########################################################
# The process guard
#
# A test that starts a process has to stop it, and everything that process
# started, before the test ends. On Linux each pytest process becomes a child
# subreaper, so a process its parent orphaned (a browser behind a launcher
# script, a daemon that double-forked) is adopted by pytest instead of
# escaping to init. After a test that launched anything, whatever it left
# running fails the test and is killed. Off with -p no:testrex_process_guard.
###########################################################

PR_SET_CHILD_SUBREAPER = 36

# Seconds a test's processes get to finish exiting once the test is over
SETTLE_SECONDS = 5
SETTLE_INI = "process_guard_settle_seconds"

# Every way Python starts a process; os.spawn*, pty and multiprocessing go through os.fork
LAUNCH_FUNCTIONS = ["fork", "forkpty", "posix_spawn", "posix_spawnp", "system"]

# The Popen method every subprocess launch goes through
POPEN_LAUNCH = "_execute_child"

# The tests running now, innermost last (pytester nests a session inside a test)
_watches = []

_unwatched = {}

# Whether this session wrapped the launch functions, and so unwraps them
WATCHING_KEY = pytest.StashKey[bool]()


# One running test: whether it launched anything, and what ran before it did
class Watch:
    def __init__(self):
        self.launched = False
        self.baseline = set()


# Whether the guard can see processes here
def is_supported():
    return sys.platform.startswith("linux") and os.path.isdir("/proc/self")


# Adopt orphaned descendants, so a leak cannot hide under init
def become_subreaper():
    libc = ctypes.CDLL(None, use_errno = True)
    return libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0


# A process's state letter and parent pid from /proc, or None once it is gone
def read_process(pid):
    try:
        with open("/proc/%d/stat" % pid, "rb") as stat_file:
            stat = stat_file.read().decode(errors = "replace")
    except OSError:
        return None
    fields = stat[stat.rindex(")") + 2:].split()
    return fields[0], int(fields[1])


# {pid: state} of every process below this one
def get_descendants():
    children = {}
    for entry in os.listdir("/proc"):
        info = read_process(int(entry)) if entry.isdigit() else None
        if info:
            children.setdefault(info[1], []).append((int(entry), info[0]))
    found = {}
    pending = [os.getpid()]
    while pending:
        for pid, state in children.get(pending.pop(), []):
            found[pid] = state
            pending.append(pid)
    return found


# A process's command line, for naming it
def describe(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as cmdline_file:
            command = cmdline_file.read().replace(b"\0", b" ").decode(errors = "replace").strip()
    except OSError:
        command = ""
    return "pid %d: %s" % (pid, command or "?")


# Note a launch in every running test that has not launched anything yet
def note_launch():
    waiting = [watch for watch in _watches if not watch.launched]
    if waiting:
        baseline = set(get_descendants())
        for watch in waiting:
            watch.launched = True
            watch.baseline = baseline


# A launch function that notes each launch before making it
def watching(launch):
    def watched(*args, **kwargs):
        note_launch()
        return launch(*args, **kwargs)
    watched.__wrapped__ = launch
    return watched


# Wrap the launch functions; False if they already are
def watch_launches():
    if _unwatched:
        return False
    _unwatched[POPEN_LAUNCH] = getattr(subprocess.Popen, POPEN_LAUNCH)
    setattr(subprocess.Popen, POPEN_LAUNCH, watching(_unwatched[POPEN_LAUNCH]))
    for name in LAUNCH_FUNCTIONS:
        if hasattr(os, name):
            _unwatched[name] = getattr(os, name)
            setattr(os, name, watching(_unwatched[name]))
    return True


# Put the launch functions back as they were
def unwatch_launches():
    if POPEN_LAUNCH in _unwatched:
        setattr(subprocess.Popen, POPEN_LAUNCH, _unwatched.pop(POPEN_LAUNCH))
    for name, original in _unwatched.items():
        setattr(os, name, original)
    _unwatched.clear()


# Collect exited processes this one is the parent of
def reap(pids):
    for pid in pids:
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            continue


# Descendants started since the baseline still running once the grace period is over
def find_leaks(baseline, settle_seconds = SETTLE_SECONDS):
    deadline = time.monotonic() + settle_seconds
    while True:
        new = {pid: state for pid, state in get_descendants().items() if pid not in baseline}
        reap(pid for pid, state in new.items() if state == "Z")
        running = sorted(pid for pid, state in new.items() if state != "Z")
        if not running or time.monotonic() >= deadline:
            return running
        time.sleep(0.05)


# Kill processes, then collect them
def kill(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            continue
    find_leaks(set(get_descendants()) - set(pids))


# The failure message for leaked processes, after killing them
def stop_leaks(baseline, settle_seconds = SETTLE_SECONDS):
    leaks = find_leaks(baseline, settle_seconds)
    if not leaks:
        return None
    lines = [describe(pid) for pid in leaks]
    kill(leaks)
    return "the test left %d process(es) running; stop what it starts:\n  %s" % (
        len(lines), "\n  ".join(lines))


# The grace period setting
def pytest_addoption(parser):
    parser.addini(SETTLE_INI, "seconds a test's processes get to exit before they count as leaked",
        default = str(SETTLE_SECONDS))


# Adopt orphans and watch launches from the session's start, collection included
def pytest_configure(config):
    if is_supported():
        become_subreaper()
        config.stash[WATCHING_KEY] = watch_launches()


# Unwrap the launch functions this session wrapped
def pytest_unconfigure(config):
    if config.stash.get(WATCHING_KEY, False):
        unwatch_launches()


# Wraps each test, its function fixtures included, failing it on what it left running
@pytest.fixture(autouse = True)
def testrex_no_leaked_processes(request):
    if not is_supported():
        yield
        return
    watch, watches = Watch(), _watches
    watches.append(watch)
    try:
        yield
    finally:
        watches.remove(watch)
    if watch.launched:
        message = stop_leaks(watch.baseline, float(request.config.getini(SETTLE_INI)))
        if message:
            pytest.fail(message, pytrace = False)
