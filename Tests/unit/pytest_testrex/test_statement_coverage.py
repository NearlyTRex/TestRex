"""What the coverage plugins share: sources, the report, options and the session hooks."""

import os
from types import SimpleNamespace

import pytest

from pytest_testrex import statement_coverage


def result(statements, missed, source=None):
    return {"statements": statements, "covered": statements - len(missed), "missed": missed,
            "missed_source": source or [f"line {first}" for first, _ in missed]}


def make_config(tmp_path, **options):
    values = {"--x-cov-source": [], "--x-cov-report": False, "--x-cov-fail-under": None,
              "--x-cov-exclude": [], **options}
    return SimpleNamespace(rootpath=tmp_path, getoption=lambda name, default=None: values.get(name, default))


def make_reporter():
    lines = []
    return lines, SimpleNamespace(write_sep=lambda sep, text: lines.append(f"[{text}]"), write_line=lines.append)


# --- sources ------------------------------------------------------------------

def test_find_sources_searches_directories_and_takes_files_as_given(tmp_path):
    for name in ("a.js", "b.txt", "deep/c.mjs", "node_modules/d.js", ".git/e.js"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", encoding="utf-8")
    found = statement_coverage.find_sources([str(tmp_path), str(tmp_path / "b.txt")], (".js", ".mjs"))
    assert found == [str(tmp_path / name) for name in ("a.js", "b.txt", "deep/c.mjs")]


def test_read_source_refuses_one_too_big(tmp_path, monkeypatch):
    path = tmp_path / "a.js"
    path.write_text("abcd", encoding="utf-8")
    monkeypatch.setattr(statement_coverage, "MAX_SOURCE_BYTES", 4)
    assert statement_coverage.read_source(path) == "abcd"
    monkeypatch.setattr(statement_coverage, "MAX_SOURCE_BYTES", 3)
    with pytest.raises(statement_coverage.SourceError, match="larger than 3 bytes"):
        statement_coverage.read_source(path)
    with pytest.raises(KeyError):
        statement_coverage.read_source(path, KeyError)


def test_describe_statement():
    lines = ["  a(   b);", "x" * 80, "end"]
    assert statement_coverage.describe_statement(lines, (1, 1)) == "a( b);"
    assert statement_coverage.describe_statement(lines, (1, 3)) == "a( b); ..."
    assert statement_coverage.describe_statement(lines, (2, 3)) == "x" * 69 + "..."


# --- report -------------------------------------------------------------------

def test_render_report_orders_by_coverage_and_lists_what_was_missed():
    results = {"good.js": result(2, []), "bad.js": result(4, [(1, 1), (3, 5)]), "empty.js": result(0, [])}
    report = statement_coverage.render_report(results, floor=50.0, title="T", label="File")
    lines = report.split("\n")
    assert lines[:2] == ["T", ""]
    assert lines[2].startswith("File    ")
    assert lines[3].startswith("bad.js ") and "50.0%  1, 3-5" in lines[3]
    assert "  bad.js:3  line 3" in lines
    assert lines[-2:] == ["Total: 66.7%", "Floor: 50.0% (met)"]
    assert statement_coverage.render_report(results, floor=90.0).endswith("Floor: 90.0% (NOT MET)")


def test_render_report_without_misses_or_floor():
    report = statement_coverage.render_report({"a.sh": result(1, [])})
    assert report.startswith("Shell coverage\n")
    assert "Missed statements" not in report and "Floor" not in report
    assert report.endswith("Total: 100.0%")


def test_meets_floor():
    results = {"a": result(4, [(1, 1)])}
    assert statement_coverage.meets_floor(results, None)
    assert statement_coverage.meets_floor(results, 75.0)
    assert not statement_coverage.meets_floor(results, 75.1)


# --- options ------------------------------------------------------------------

@pytest.mark.parametrize("branch_help, expected", [
    (None, ["--x-cov-source", "--x-cov-exclude", "--x-cov-report", "--x-cov-fail-under"]),
    ("count arms", ["--x-cov-source", "--x-cov-exclude", "--x-cov-report", "--x-cov-branch", "--x-cov-fail-under"]),
])
def test_add_options(branch_help, expected):
    added = {}
    groups = []
    group = SimpleNamespace(addoption=lambda name, **kwargs: added.setdefault(name, kwargs))
    parser = SimpleNamespace(getgroup=lambda name: groups.append(name) or group)
    statement_coverage.add_options(parser, "x-cov", "Lisp coverage", "a source", branch_help)
    assert list(added) == expected
    assert groups == ["Lisp coverage"]
    assert added["--x-cov-source"]["help"] == "a source"
    assert added["--x-cov-report"]["help"] == "report how much of the Lisp the tests ran"
    assert "Lisp coverage is below" in added["--x-cov-fail-under"]["help"]


@pytest.mark.parametrize("options, enabled", [
    ({}, False),
    ({"--x-cov-source": ["a"]}, True),
    ({"--x-cov-report": True}, True),
    ({"--x-cov-fail-under": 0.0}, True),
])
def test_is_enabled(tmp_path, options, enabled):
    assert statement_coverage.is_enabled(make_config(tmp_path, **options), "x-cov") is enabled


def test_is_worker_and_is_branch(tmp_path):
    config = make_config(tmp_path)
    assert not statement_coverage.is_worker(config)
    assert not statement_coverage.is_branch(config, "x-cov")
    config.workerinput = {}
    assert statement_coverage.is_worker(config)
    assert statement_coverage.is_branch(make_config(tmp_path, **{"--x-cov-branch": True}), "x-cov")


def test_get_sources(tmp_path):
    (tmp_path / "src").mkdir()
    assert statement_coverage.get_sources(make_config(tmp_path), "x-cov") == [str(tmp_path)]
    config = make_config(tmp_path, **{"--x-cov-source": ["src"]})
    assert statement_coverage.get_sources(config, "x-cov") == [os.path.join(str(tmp_path), "src")]
    with pytest.raises(pytest.UsageError, match="--x-cov-source .*nope does not exist"):
        statement_coverage.get_sources(make_config(tmp_path, **{"--x-cov-source": ["nope"]}), "x-cov")


# --- session ------------------------------------------------------------------

def test_finish_keeps_the_results_and_passes_what_measure_needs(tmp_path):
    calls = []

    def measure(*args):
        calls.append(args)
        return {"a": result(1, [])}

    config = make_config(tmp_path, **{"--x-cov-exclude": ["v/*"], "--x-cov-fail-under": 100.0})
    session = SimpleNamespace(config=config, exitstatus=0)
    statement_coverage.finish(session, "x-cov", measure)
    assert calls == [(str(tmp_path), [str(tmp_path)], False, ["v/*"])]
    assert config.x_cov_results == {"a": result(1, [])}
    assert session.exitstatus == 0


@pytest.mark.parametrize("before, after", [
    (0, pytest.ExitCode.TESTS_FAILED),
    (pytest.ExitCode.INTERRUPTED, pytest.ExitCode.INTERRUPTED),
])
def test_finish_fails_a_run_below_the_floor(tmp_path, before, after):
    config = make_config(tmp_path, **{"--x-cov-fail-under": 100.0})
    session = SimpleNamespace(config=config, exitstatus=before)
    statement_coverage.finish(session, "x-cov", lambda *args: {"a": result(2, [(1, 1)])})
    assert session.exitstatus == after


@pytest.mark.parametrize("before, after", [
    (0, pytest.ExitCode.TESTS_FAILED),
    (pytest.ExitCode.INTERRUPTED, pytest.ExitCode.INTERRUPTED),
])
def test_finish_keeps_why_a_source_could_not_be_measured(tmp_path, before, after):
    def measure(*args):
        raise statement_coverage.SourceError("bad.x: unreadable")

    config = make_config(tmp_path)
    session = SimpleNamespace(config=config, exitstatus=before)
    statement_coverage.finish(session, "x-cov", measure)
    assert config.x_cov_error == "bad.x: unreadable"
    assert not hasattr(config, "x_cov_results")
    assert session.exitstatus == after


def test_summarize_writes_nothing_without_a_measurement(tmp_path):
    lines, reporter = make_reporter()
    statement_coverage.summarize(reporter, make_config(tmp_path), "x-cov", "Lisp coverage", "File")
    assert not lines


def test_summarize_names_a_source_it_could_not_measure(tmp_path):
    config = make_config(tmp_path)
    config.x_cov_error = "bad.x: unreadable"
    lines, reporter = make_reporter()
    statement_coverage.summarize(reporter, config, "x-cov", "Lisp coverage", "File")
    assert lines[:2] == ["[lisp coverage]", "Could not measure: bad.x: unreadable"]
    assert "--x-cov-exclude" in lines[2]


@pytest.mark.parametrize("branch, title", [(False, "Lisp coverage"),
                                           (True, "Lisp coverage (branches count as statements)")])
def test_summarize_writes_the_report(tmp_path, branch, title):
    config = make_config(tmp_path, **{"--x-cov-branch": branch, "--x-cov-fail-under": 50.0})
    config.x_cov_results = {"a.x": result(2, [(2, 2)])}
    lines, reporter = make_reporter()
    statement_coverage.summarize(reporter, config, "x-cov", "Lisp coverage", "File")
    assert lines[0] == "[lisp coverage]"
    assert lines[1].startswith(title + "\n\nFile ")
    assert lines[1].endswith("Floor: 50.0% (met)")


def test_percentages_with_no_statements_are_full():
    assert statement_coverage.get_percent(result(0, [])) == 100.0
    assert statement_coverage.get_total_percent({}) == 100.0
    assert statement_coverage.get_total_percent({"a": result(3, [(1, 1)]), "b": result(1, [])}) == 75.0


def test_format_missed_is_cut_to_a_limit():
    assert statement_coverage.format_missed([(1, 1), (3, 5)]) == "1, 3-5"
    assert statement_coverage.format_missed([(n, n) for n in range(1, 5)], limit=2) == "1, 2, ..."


def test_render_report_caps_the_missed_statements_listed_per_source():
    count = statement_coverage.MISSED_LISTED + 2
    report = statement_coverage.render_report({"a.x": result(count, [(n, n) for n in range(1, count + 1)])})
    assert f"  a.x:{statement_coverage.MISSED_LISTED}  line {statement_coverage.MISSED_LISTED}" in report
    assert f"a.x:{count}  " not in report
    assert "  a.x: ... and 2 more" in report
