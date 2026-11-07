# Imports
import os
import subprocess

# Third-party imports
import pytest

# Local imports
from pytest_testrex import plugin, script_tests, settings

###########################################################
# Standalone test files, with the runners faked
#
# A sample repository is run in this process with pytester, its runner
# replaced by a stand-in that answers with canned TAP output, so collection,
# results and reports are checked without node or busted.
###########################################################

CONFIGURED = "[tool.testrex]\nsuites = ['unit', 'integration']\ndata_dirs = ['integration/data']\n"

PASSING_TAP = "TAP version 13\nok 1 - greets\n1..1\n"

FAILING_TAP = """TAP version 13
# Subtest: greets
not ok 1 - greets
  ---
  ...
not ok 2 - waits # TODO
not ok 3 - later # SKIP no network
    not ok 4 - inner case # time=1ms
not ok 5
ok 6 - passes
1..6
"""


# Writes a sample repository and replaces the runner with one that answers with output
@pytest.fixture
def sample(pytester, monkeypatch):
    ran = []

    def write(files, returncode = 0, output = PASSING_TAP, settings_text = CONFIGURED):
        pytester.makepyprojecttoml(settings_text)
        for relative_path, text in files.items():
            path = pytester.path / relative_path
            path.parent.mkdir(parents = True, exist_ok = True)
            path.write_text(text, encoding = "utf-8")

        def run(runner, path, cwd):
            ran.append((list(runner), os.path.relpath(path, cwd), cwd))
            return subprocess.CompletedProcess([*runner, path], returncode, output, "warning on stderr\n")
        monkeypatch.setattr(script_tests, "run_script", run)
        monkeypatch.setattr(plugin, "missing_binaries", lambda names: [])
        return ran
    return write


def test_tap_failures_are_named_and_todo_and_skip_left_out():
    assert script_tests.failing_tests(FAILING_TAP) == ["greets", "inner case", ""]
    assert script_tests.failing_tests(PASSING_TAP) == []


def test_a_file_is_a_script_test_only_under_a_suite_and_outside_data(tmp_path):
    loaded = settings.from_table({"data_dirs": ["unit/data"], "lua_test_patterns": []}, str(tmp_path))
    unit = tmp_path / "Tests" / "unit"

    assert script_tests.language_of(str(unit / "greet.test.js"), loaded) == "javascript"
    assert script_tests.language_of(str(unit / "greet_spec.lua"), loaded) is None
    assert script_tests.language_of(str(unit / "data" / "greet.test.js"), loaded) is None
    assert script_tests.language_of(str(tmp_path / "greet.test.js"), loaded) is None


def test_each_script_test_file_is_one_item_run_from_the_repository(pytester, sample):
    ran = sample({
        "Tests/integration/lib/greet.test.js": "", "Tests/integration/lib/greet_spec.lua": "",
        "Tests/integration/data/old.test.js": "", "lib/greet.test.js": ""})

    result = pytester.inline_run("-p", "no:cacheprovider")
    passed, skipped, failed = result.listoutcomes()

    assert sorted(report.nodeid for report in passed) == [
        "Tests/integration/lib/greet.test.js::node", "Tests/integration/lib/greet_spec.lua::busted"]
    assert (skipped, failed) == ([], [])
    assert sorted(ran) == [
        (["busted", "--output=TAP"], os.path.join("Tests", "integration", "lib", "greet_spec.lua"), str(pytester.path)),
        (["node", "--test", "--test-reporter=tap"], os.path.join("Tests", "integration", "lib", "greet.test.js"), str(pytester.path))]


def test_a_failing_file_reports_the_tests_that_failed_and_the_output(pytester, sample):
    sample({"Tests/integration/greet.test.js": ""}, returncode = 1, output = FAILING_TAP)

    result = pytester.runpytest("-p", "no:cacheprovider")

    result.assert_outcomes(failed = 1)
    result.stdout.fnmatch_lines(["failed: greets, inner case, ", "*not ok 4 - inner case*", "warning on stderr"])
    assert "Traceback" not in result.stdout.str()


def test_a_failure_without_tap_names_the_exit_status(pytester, sample):
    sample({"Tests/integration/greet_spec.lua": ""}, returncode = 2, output = "lua: cannot open file\n")

    result = pytester.runpytest("-p", "no:cacheprovider")

    result.assert_outcomes(failed = 1)
    result.stdout.fnmatch_lines(["busted exited with 2", "lua: cannot open file"])


def test_an_error_in_running_it_is_reported_as_an_error(pytester, sample, monkeypatch):
    sample({"Tests/integration/greet.test.js": ""})

    def missing(runner, path, cwd):
        raise FileNotFoundError(runner[0])
    monkeypatch.setattr(script_tests, "run_script", missing)

    result = pytester.runpytest("-p", "no:cacheprovider")

    result.assert_outcomes(failed = 1)
    result.stdout.fnmatch_lines(["*FileNotFoundError: node*"])


def test_a_missing_runner_skips_the_file(pytester, sample, monkeypatch):
    sample({"Tests/integration/greet.test.js": ""})
    monkeypatch.setattr(plugin, "missing_binaries", list)

    result = pytester.runpytest("-p", "no:cacheprovider", "-rs")

    result.assert_outcomes(skipped = 1)
    result.stdout.fnmatch_lines(["*node not installed*"])


def test_the_report_names_the_command(pytester, sample):
    sample({"Tests/integration/greet.test.js": ""})

    items, _ = pytester.inline_genitems("-p", "no:cacheprovider")

    assert items[0].reportinfo() == (
        items[0].path, 0, "node --test --test-reporter=tap " + os.path.join("Tests", "integration", "greet.test.js"))


def test_without_a_table_nothing_is_collected(pytester, sample):
    sample({"Tests/integration/greet.test.js": ""}, settings_text = "[project]\nname = 'x'\n")

    items, _ = pytester.inline_genitems("-p", "no:cacheprovider")

    assert items == []


def test_the_runner_is_started_with_the_file_from_the_directory(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: seen.append((command, kwargs["cwd"])) or "done")

    assert script_tests.run_script(("node", "--test"), "a.test.js", str(tmp_path)) == "done"
    assert seen == [(["node", "--test", "a.test.js"], str(tmp_path))]
