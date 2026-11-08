# Imports
import os
import types

# Third-party imports
import pytest

# Local imports
from fixture_helpers import unwrap
from pytest_testrex import process_guard as guard


@pytest.fixture
def processes(monkeypatch):
    # A scripted process table: each scan pops the next {pid: state}, the last repeating
    state = {"scans": [{}], "killed": [], "reaped": [], "kill_fails": False, "wait_fails": False}

    def get_descendants():
        return dict(state["scans"].pop(0) if len(state["scans"]) > 1 else state["scans"][0])

    def kill(pid, signal_number):
        if state["kill_fails"]:
            raise ProcessLookupError(pid)
        state["killed"].append(pid)

    def waitpid(pid, options):
        if state["wait_fails"]:
            raise ChildProcessError(pid)
        state["reaped"].append(pid)
        return pid, 0

    monkeypatch.setattr(guard, "get_descendants", get_descendants)
    monkeypatch.setattr(guard.os, "kill", kill)
    monkeypatch.setattr(guard.os, "waitpid", waitpid)
    monkeypatch.setattr(guard.time, "sleep", lambda seconds: None)
    return state


def test_a_process_reads_its_state_and_parent():
    assert guard.read_process(os.getpid()) == ("R", os.getppid())


def test_a_gone_process_reads_as_none():
    assert guard.read_process(2 ** 22 + 1) is None


def test_this_process_is_named_by_its_command_line():
    assert guard.describe(os.getpid()).startswith(f"pid {os.getpid()}: ")


def test_a_gone_process_is_named_by_its_pid_alone():
    assert guard.describe(2 ** 22 + 1) == f"pid {2 ** 22 + 1}: ?"


def test_the_first_launch_in_a_test_takes_the_baseline(monkeypatch):
    scans = iter([{7: "S"}, {7: "S", 8: "S"}])
    monkeypatch.setattr(guard, "get_descendants", lambda: next(scans))
    outer, inner = guard.Watch(), guard.Watch()
    monkeypatch.setattr(guard, "_watches", [outer])

    guard.note_launch()
    guard._watches.append(inner)
    guard.note_launch()
    guard.note_launch()

    assert (outer.launched, outer.baseline) == (True, {7})
    assert (inner.launched, inner.baseline) == (True, {7, 8})


def test_launch_functions_are_wrapped_once_and_put_back(monkeypatch):
    fake_os = types.SimpleNamespace(fork = lambda: 0, system = lambda command: 0)
    fake_popen = type("Popen", (), {"_execute_child": lambda self: "ran"})
    monkeypatch.setattr(guard, "os", fake_os)
    monkeypatch.setattr(guard.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(guard, "_unwatched", {})
    monkeypatch.setattr(guard, "_watches", [])
    originals = (fake_os.fork, fake_os.system, fake_popen._execute_child)

    assert guard.watch_launches() is True
    assert guard.watch_launches() is False
    assert fake_os.fork.__wrapped__ is originals[0]
    assert fake_popen._execute_child(None) == "ran"

    guard.unwatch_launches()
    guard.unwatch_launches()
    assert (fake_os.fork, fake_os.system, fake_popen._execute_child) == originals
    assert not hasattr(fake_os, "posix_spawn")


def test_exited_processes_are_reaped_and_not_leaks(processes):
    processes["scans"] = [{5: "S", 6: "Z"}, {5: "S"}]

    assert guard.find_leaks({5}) == []
    assert processes["reaped"] == [6]


def test_a_process_that_exits_within_the_grace_period_is_not_a_leak(processes):
    processes["scans"] = [{9: "S"}, {9: "S"}, {}]

    assert guard.find_leaks(set(), settle_seconds = 60) == []


def test_reaping_someone_elses_child_is_skipped(processes):
    processes["wait_fails"] = True

    guard.reap([4])

    assert processes["reaped"] == []


def test_leaks_are_named_then_killed(processes):
    processes["scans"] = [{9: "S", 10: "R"}, {}]

    message = guard.stop_leaks(set(), settle_seconds = 0)

    assert message.startswith("the test left 2 process(es) running")
    assert "pid 9" in message and "pid 10" in message
    assert processes["killed"] == [9, 10]


def test_a_leak_that_dies_before_its_kill_is_skipped(processes):
    processes["kill_fails"] = True

    guard.kill([9])

    assert processes["killed"] == []


def test_without_leaks_there_is_no_message(processes):
    assert guard.stop_leaks(set(), settle_seconds = 0) is None


def run_fixture(monkeypatch, launch, settle = "0"):
    request = types.SimpleNamespace(config = types.SimpleNamespace(getini = lambda name: settle))
    monkeypatch.setattr(guard, "_watches", [])
    steps = unwrap(guard.testrex_no_leaked_processes)(request)
    next(steps)
    if launch:
        guard.note_launch()
    next(steps, None)
    return guard._watches


def test_a_test_that_leaks_fails(processes, monkeypatch):
    processes["scans"] = [{}, {9: "S"}, {}]

    with pytest.raises(pytest.fail.Exception, match = "left 1 process"):
        run_fixture(monkeypatch, launch = True)


def test_a_test_that_launched_nothing_is_not_checked(processes, monkeypatch):
    processes["scans"] = [{9: "S"}]

    assert run_fixture(monkeypatch, launch = False) == []


def test_a_test_that_cleaned_up_passes(processes, monkeypatch):
    assert run_fixture(monkeypatch, launch = True) == []


def test_off_linux_the_guard_does_nothing(monkeypatch):
    monkeypatch.setattr(guard, "is_supported", lambda: False)
    monkeypatch.setattr(guard, "watch_launches", lambda: pytest.fail("watched"))
    config = types.SimpleNamespace(stash = {})

    guard.pytest_configure(config)
    guard.pytest_unconfigure(config)

    assert run_fixture(monkeypatch, launch = False) == []
    assert config.stash == {}
