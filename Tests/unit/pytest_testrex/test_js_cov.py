"""The JavaScript coverage plugin in process: statements, branches, V8 coverage, the report and the hooks."""

import json
import os
import pathlib
from types import SimpleNamespace

import pytest

from fixture_helpers import unwrap
from pytest_testrex import js_cov, parsers, statement_coverage


def units(source, text, nth=0):
    """The UTF-16 offset of the nth occurrence of text in source, as V8 counts."""
    index = -1
    for _ in range(nth + 1):
        index = source.index(text, index + 1)
    return len(source[:index].encode("utf-16-le")) // 2


def whole(source):
    return len(source.encode("utf-16-le")) // 2


def write_coverage(directory, path, functions, name="coverage-1.json"):
    """A coverage file as node writes it, for one script given as [[(start, end, count), ...], ...]."""
    result = [{"url": pathlib.Path(path).as_uri(), "functions": [
        {"functionName": "", "ranges": [{"startOffset": s, "endOffset": e, "count": c} for s, e, c in ranges]}
        for ranges in functions]}]
    (directory / name).write_text(json.dumps({"result": result}), encoding="utf-8")


def ranges_of(functions):
    return [found for ranges in functions for found in ranges]


# --- offsets ----------------------------------------------------------------

@pytest.mark.parametrize("source", ["let a = 1;\nlet b;", "const s = 'é';\nlet b;", "const s = '😀é😀';\nlet b;"])
def test_byte_offsets_become_utf16_offsets(source):
    convert = js_cov.utf16_offsets(source)
    byte = source.encode().index(b"let b")
    assert convert(byte) == units(source, "let b")
    assert convert(0) == 0


# --- statements and branches ----------------------------------------------------

@pytest.mark.parametrize("source, expected", [
    ("a();\nb();\n", [(1, 1), (2, 2)]),
    ("const x = [\n  1,\n  2,\n];\n", [(1, 4)]),
    ("if (a) {\n  b();\n} else {\n  c();\n}\n", [(1, 1), (2, 2), (4, 4)]),
    ("for (const k in o) {\n}\nwhile (x) {\n  y();\n}\n", [(1, 1), (3, 3), (4, 4)]),
    ("function f() {\n  return 1;\n}\nclass A {\n  m() {}\n}\n", [(1, 1), (2, 2), (4, 4)]),
    ("run(() => {\n  inner();\n});\n", [(1, 1), (2, 2)]),
    ("{\n  a();\n}\n;\n", [(2, 2)]),
    ("import x from 'y';\nexport const z = 1;\n", [(1, 1), (2, 2)]),
])
def test_statements(source, expected):
    found = js_cov.find_statements(js_cov.read_tree(source))
    assert [lines for _, _, lines in found] == expected


def test_function_declarations_carry_their_end():
    found = js_cov.find_statements(js_cov.read_tree("function f() {}\nfunction* g() {}\nf();\n"))
    assert [end for _, end, _ in found] == [15, 32, None]


def test_a_label_or_an_exported_declaration_is_one_statement():
    source = "outer: for (;;) {\n  break outer;\n}\nexport function f() {}\n"
    found = js_cov.find_statements(js_cov.read_tree(source))
    assert [(start, lines) for start, _, lines in found] == [
        (source.index("for"), (1, 1)), (source.index("break"), (2, 2)), (source.index("function"), (4, 4))]


def test_branches_are_logical_right_sides_and_conditional_arms():
    source = "x = a && b;\ny = a || b;\nz = a ?? b;\nw = a ? b : c;\nv = a + b;\n"
    found = js_cov.find_branches(js_cov.read_tree(source), source.encode())
    assert [(line, text) for _, line, text in found] == [
        (1, "&& b"), (2, "|| b"), (3, "?? b"), (4, "? b"), (4, ": c")]
    assert found[0][0] == source.index("b;")


def test_branch_text_skips_comments_and_is_kept_short():
    source = "x = a ||\n  /* c */ " + "y" * 100 + ";\n"
    (_, line, text), = js_cov.find_branches(js_cov.read_tree(source), source.encode())
    assert line == 2
    assert text.startswith("|| /* c */ yyy") and text.endswith("...") and len(text) == js_cov.BRANCH_TEXT_WIDTH


def test_a_script_the_parser_cannot_read_is_refused_with_where():
    with pytest.raises(js_cov.JsParseError, match="near line 2"):
        js_cov.read_tree("a();\nif (\n")


# --- V8 coverage ------------------------------------------------------------------

def test_count_at_takes_the_smallest_range_holding_the_offset():
    ranges = ranges_of([[(0, 100, 1), (10, 20, 0)], [(10, 20, 3)]])
    assert js_cov.count_at(ranges, 15) == 3          # equal sizes: the later range
    assert js_cov.count_at(ranges, 5) == 1
    assert js_cov.count_at(ranges_of([[(10, 20, 0)], [(0, 100, 1)]]), 15) == 0   # in any order
    assert js_cov.count_at(ranges, 100) == 0         # end is exclusive
    assert js_cov.count_at([], 0) == 0


def test_a_definition_is_counted_by_the_code_around_it():
    ranges = ranges_of([[(0, 50, 1)], [(10, 30, 0)]])
    assert js_cov.count_at(ranges, 10) == 0
    assert js_cov.count_at(ranges, 10, skip=(10, 30)) == 1
    assert js_cov.count_at(ranges, 10, skip=(10, 29)) == 0


def test_any_process_that_ran_it_counts():
    assert js_cov.is_run([ranges_of([[(0, 9, 0)]]), ranges_of([[(0, 9, 2)]])], 3)
    assert not js_cov.is_run([ranges_of([[(0, 9, 0)]])], 3)
    assert not js_cov.is_run([], 3)


def test_path_of_takes_file_urls_only(tmp_path):
    spaced = tmp_path / "a dir" / "x.js"
    assert js_cov.path_of(spaced.as_uri()) == os.path.realpath(spaced)
    assert js_cov.path_of("node:internal/main") is None
    assert js_cov.path_of("https://example.com/x.js") is None


def test_read_coverage_merges_processes_and_passes_over_other_files(tmp_path):
    script = tmp_path / "s.js"
    write_coverage(tmp_path, script, [[(0, 5, 1), (2, 3, 0)], [(1, 2, 4)]], name="coverage-1.json")
    write_coverage(tmp_path, script, [[(0, 5, 0)]], name="coverage-2.json")
    (tmp_path / "coverage-3.json").write_text('{"result": [', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not coverage", encoding="utf-8")
    (tmp_path / "coverage-4.json").write_text(json.dumps({"result": [
        {"url": "node:fs", "functions": []}]}), encoding="utf-8")
    (tmp_path / "coverage-5.json").write_text("{}", encoding="utf-8")
    assert js_cov.read_coverage(tmp_path) == {os.path.realpath(script): [
        [(0, 5, 1), (2, 3, 0), (1, 2, 4)], [(0, 5, 0)]]}


# --- measuring ----------------------------------------------------------------------

UNCALLED = "function never() {\n  return 1;\n}\nconst y = 2;\n"


def test_a_function_never_called_misses_its_body_only():
    ranges = ranges_of([[(0, whole(UNCALLED), 1)], [(0, units(UNCALLED, "\nconst"), 0)]])   # starts with the file
    result = js_cov.measure_script(UNCALLED, [ranges])
    assert result == {"statements": 3, "covered": 2, "missed": [(2, 2)], "missed_source": ["return 1;"]}


def test_a_script_no_process_loaded_is_wholly_missed():
    result = js_cov.measure_script(UNCALLED, [])
    assert result["covered"] == 0 and result["missed"] == [(1, 1), (2, 2), (4, 4)]


@pytest.mark.parametrize("prefix", ["", "const s = 'é';\n", "const s = '😀😀';\n", "// ü 😀 ü\n"])
def test_offsets_after_text_that_is_not_ascii_land_on_their_statement(prefix):
    source = prefix + "if (x) {\n  a();\n} else {\n  b();\n}\n"
    block = units(source, "{", 1)
    ranges = ranges_of([[(0, whole(source), 1), (block, block + 12, 0)]])
    result = js_cov.measure_script(source, [ranges])
    assert result["missed_source"] == ["b();"]


def test_branch_mode_counts_each_arm():
    source = "const v = a && b;\nconst w = a ? b : c;\n"
    ranges = ranges_of([[(0, whole(source), 1), (units(source, "&&"), units(source, ";"), 0),
                         (units(source, ":"), units(source, ";", 1), 0)]])
    assert js_cov.measure_script(source, [ranges])["statements"] == 2
    result = js_cov.measure_script(source, [ranges], branch=True)
    assert result == {"statements": 5, "covered": 3, "missed": [(1, 1), (2, 2)],
                      "missed_source": ["&& b", ": c"]}


def test_measure_names_scripts_and_leaves_out_excluded_ones(tmp_path):
    (tmp_path / "src").mkdir()
    for name in ("a.js", "b.mjs", "c.cjs", "vendor.js", "notes.txt"):
        (tmp_path / "src" / name).write_text("x();\n", encoding="utf-8")
    coverage_dir = tmp_path / "coverage"
    coverage_dir.mkdir()
    write_coverage(coverage_dir, tmp_path / "src" / "a.js", [[(0, 5, 1)]])
    results = js_cov.measure(str(tmp_path), [str(tmp_path / "src")], exclude=["src/vendor*"],
                             coverage_dir=coverage_dir)
    assert sorted(results) == [os.path.join("src", name) for name in ("a.js", "b.mjs", "c.cjs")]
    assert results[os.path.join("src", "a.js")]["covered"] == 1
    assert results[os.path.join("src", "b.mjs")]["covered"] == 0


def test_measure_names_a_script_it_cannot_read(tmp_path, monkeypatch):
    (tmp_path / "bad.js").write_text("if (\n", encoding="utf-8")
    with pytest.raises(js_cov.JsParseError, match="^bad.js: tree-sitter-javascript cannot parse it"):
        js_cov.measure(str(tmp_path), [str(tmp_path)], coverage_dir=tmp_path)
    monkeypatch.setattr(statement_coverage, "MAX_SOURCE_BYTES", 2)
    (tmp_path / "bad.js").write_text("a();\n", encoding="utf-8")
    with pytest.raises(js_cov.JsParseError, match="^bad.js: larger than 2 bytes"):
        js_cov.measure(str(tmp_path), [str(tmp_path)], coverage_dir=tmp_path)


# --- plugin hooks -------------------------------------------------------

def make_config(tmp_path, source=(), report=False, floor=None, worker=False, branch=False, exclude=()):
    options = {"--js-cov-source": list(source), "--js-cov-report": report, "--js-cov-fail-under": floor,
               "--js-cov-branch": branch, "--js-cov-exclude": list(exclude)}
    config = SimpleNamespace(rootpath=tmp_path, getoption=lambda name, default=None: options[name])
    if worker:
        config.workerinput = {}
    return config


def test_addoption_registers_all_options():
    added = []
    group = SimpleNamespace(addoption=lambda *a, **k: added.append(a[0]))
    js_cov.pytest_addoption(SimpleNamespace(getgroup=lambda name: group))
    assert added == ["--js-cov-source", "--js-cov-exclude", "--js-cov-report", "--js-cov-branch",
                     "--js-cov-fail-under"]


def test_configure_is_inert_when_disabled_or_on_a_worker(tmp_path, monkeypatch):
    monkeypatch.delenv("NODE_V8_COVERAGE", raising=False)
    for config in (make_config(tmp_path), make_config(tmp_path, report=True, worker=True)):
        js_cov.pytest_configure(config)
        assert config.js_cov_dir is None
        js_cov.pytest_unconfigure(config)
        session = SimpleNamespace(config=config, exitstatus=0)
        js_cov.pytest_sessionfinish(session, 0)
        assert session.exitstatus == 0
        js_cov.pytest_terminal_summary(None, 0, config)
    assert "NODE_V8_COVERAGE" not in os.environ


@pytest.mark.parametrize("before", [None, "/elsewhere"])
def test_configure_sets_and_restores_the_coverage_directory(tmp_path, monkeypatch, before):
    if before is None:
        monkeypatch.delenv("NODE_V8_COVERAGE", raising=False)
    else:
        monkeypatch.setenv("NODE_V8_COVERAGE", before)
    config = make_config(tmp_path, report=True)
    js_cov.pytest_configure(config)
    coverage_dir = config.js_cov_dir
    assert os.environ["NODE_V8_COVERAGE"] == coverage_dir and os.path.isdir(coverage_dir)
    js_cov.pytest_unconfigure(config)
    assert os.environ.get("NODE_V8_COVERAGE") == before
    assert not os.path.exists(coverage_dir)


def test_missing_source_is_a_usage_error(tmp_path):
    with pytest.raises(pytest.UsageError, match="does not exist"):
        js_cov.pytest_configure(make_config(tmp_path, source=["nope"]))


def test_configure_fails_clearly_when_the_grammar_is_missing(tmp_path, monkeypatch):
    def missing(language):
        raise parsers.ParserMissing(f"reading {language} needs tree-sitter-javascript")

    monkeypatch.setattr(parsers, "get_parser", missing)
    with pytest.raises(pytest.UsageError, match="needs tree-sitter-javascript"):
        js_cov.pytest_configure(make_config(tmp_path, report=True))


def test_traced_env_adds_the_coverage_directory_only_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_V8_COVERAGE", "/ours")
    fixture = unwrap(js_cov.js_traced_env)
    disabled = fixture(SimpleNamespace(config=make_config(tmp_path)))
    assert disabled({"A": "1"}) == {"A": "1"}
    worker = fixture(SimpleNamespace(config=make_config(tmp_path, report=True, worker=True)))
    assert worker({"A": "1"}) == {"A": "1", "NODE_V8_COVERAGE": "/ours"}
    assert worker()["PATH"] == os.environ["PATH"]
    monkeypatch.delenv("NODE_V8_COVERAGE")
    assert fixture(SimpleNamespace(config=make_config(tmp_path, report=True)))({"A": "1"}) == {"A": "1"}


def test_session_finish_measures_gates_and_reports(tmp_path):
    (tmp_path / "s.js").write_text("a() || b();\n", encoding="utf-8")
    config = make_config(tmp_path, source=["s.js"], floor=100.0, branch=True)
    js_cov.pytest_configure(config)
    try:
        write_coverage(pathlib.Path(config.js_cov_dir), tmp_path / "s.js", [[(0, 12, 1), (4, 10, 0)]])
        session = SimpleNamespace(config=config, exitstatus=0)
        js_cov.pytest_sessionfinish(session, 0)
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        assert config.js_cov_results["s.js"]["missed_source"] == ["|| b()"]
        lines = []
        reporter = SimpleNamespace(write_sep=lambda *a, **k: lines.append(a[1]), write_line=lines.append)
        js_cov.pytest_terminal_summary(reporter, 0, config)
        assert lines[0] == "javascript coverage"
        assert lines[1].startswith("JavaScript coverage (branches count as statements)")
        assert "s.js:1  || b()" in lines[1]
    finally:
        js_cov.pytest_unconfigure(config)


def test_a_script_that_cannot_be_parsed_fails_the_run_and_says_which(tmp_path):
    (tmp_path / "bad.js").write_text("if (\n", encoding="utf-8")
    config = make_config(tmp_path, report=True)
    js_cov.pytest_configure(config)
    try:
        session = SimpleNamespace(config=config, exitstatus=0)
        js_cov.pytest_sessionfinish(session, 0)
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        lines = []
        reporter = SimpleNamespace(write_sep=lambda *a, **k: lines.append(a[1]), write_line=lines.append)
        js_cov.pytest_terminal_summary(reporter, 0, config)
        assert lines[1].startswith("Could not measure: bad.js: tree-sitter-javascript")
        assert "--js-cov-exclude" in lines[2]
    finally:
        js_cov.pytest_unconfigure(config)
