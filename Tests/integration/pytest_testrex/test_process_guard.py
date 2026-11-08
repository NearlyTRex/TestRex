"""The process guard against real processes: leaks fail the test that made them and are killed."""

import os
import sys
import time

import pytest

pytestmark = [
    pytest.mark.requires_binary("sh", "sleep"),
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason = "the guard reads /proc"),
]

# Inner tests write the pids they start here, so the outer test can check them
PIDS_HELPER = """
import os
import subprocess

def record(pid):
    with open(os.environ["GUARD_PIDS"], "a") as pids:
        pids.write("%d\\n" % pid)
"""


def run_inner(pytester, monkeypatch, tmp_path, source, *args):
    pids = tmp_path / "pids"
    pytester.makepyfile(pids_helper = PIDS_HELPER, test_inner = source)
    pytester.makeini("[pytest]\nprocess_guard_settle_seconds = 1\n")
    monkeypatch.setenv("GUARD_PIDS", str(pids))
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", *args)
    recorded = [int(line) for line in pids.read_text().split()] if pids.exists() else []
    return result, recorded


def is_running(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding = "utf-8") as stat:
            return stat.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def kill_strays(pids):
    for pid in pids:
        if is_running(pid):
            os.kill(pid, 9)


def test_a_child_left_running_fails_the_test_and_is_killed(pytester, monkeypatch, tmp_path):
    result, pids = run_inner(pytester, monkeypatch, tmp_path, """
        from pids_helper import record, subprocess
        def test_leaks():
            record(subprocess.Popen(["sleep", "60"]).pid)
    """)
    kill_strays(pids)

    result.assert_outcomes(passed = 1, errors = 1)
    result.stdout.fnmatch_lines(["*left 1 process(es) running*", "*sleep 60*"])
    assert [pid for pid in pids if is_running(pid)] == []


def test_an_orphaned_grandchild_is_caught(pytester, monkeypatch, tmp_path):
    # The parent exits at once and the sleep is reparented, as a browser is
    # behind a launcher script that quit stopped
    result, pids = run_inner(pytester, monkeypatch, tmp_path, """
        import os
        from pids_helper import subprocess
        def test_orphans():
            subprocess.run(["sh", "-c", "sleep 60 & echo $! >> \\"$GUARD_PIDS\\""], check = True)
    """)
    kill_strays(pids)

    result.assert_outcomes(passed = 1, errors = 1)
    result.stdout.fnmatch_lines(["*left 1 process(es) running*", "*sleep 60*"])
    assert len(pids) == 1
    assert not is_running(pids[0])


def test_processes_that_are_stopped_or_exit_on_their_own_pass(pytester, monkeypatch, tmp_path):
    result, pids = run_inner(pytester, monkeypatch, tmp_path, """
        from pids_helper import subprocess
        def test_waits():
            subprocess.run(["sh", "-c", "exit 0"], check = True)
        def test_kills():
            process = subprocess.Popen(["sleep", "60"])
            process.kill()
            process.wait()
        def test_never_waited():
            subprocess.Popen(["sh", "-c", "exit 0"])
        def test_finishes_soon_after():
            subprocess.Popen(["sleep", "0.3"])
    """)

    result.assert_outcomes(passed = 4)
    assert pids == []


def test_a_process_from_a_session_fixture_is_not_blamed_on_later_tests(pytester, monkeypatch, tmp_path):
    result, pids = run_inner(pytester, monkeypatch, tmp_path, """
        import pytest
        from pids_helper import record, subprocess
        @pytest.fixture(scope = "session")
        def server():
            process = subprocess.Popen(["sleep", "60"])
            record(process.pid)
            yield
            process.kill()
            process.wait()
        def test_first(server):
            pass
        def test_launches_too(server):
            subprocess.run(["sh", "-c", "exit 0"], check = True)
    """)
    kill_strays(pids)

    result.assert_outcomes(passed = 2)


def test_the_guard_can_be_turned_off(pytester, monkeypatch, tmp_path):
    result, pids = run_inner(pytester, monkeypatch, tmp_path, """
        from pids_helper import record, subprocess
        def test_leaks():
            record(subprocess.Popen(["sleep", "60"]).pid)
    """, "-p", "no:testrex_process_guard")
    time.sleep(0.2)
    running = [pid for pid in pids if is_running(pid)]
    kill_strays(pids)

    result.assert_outcomes(passed = 1)
    assert running == pids
