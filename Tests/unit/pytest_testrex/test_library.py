# Imports
import os

# Third-party imports
import pytest

# Local imports
from pytest_testrex import library, settings


def configured(tmp_path, **table):
    return settings.from_table(dict({"library_targets": ["pkg"]}, **table), str(tmp_path))


def test_library_files_come_from_files_and_directories(write_file, tmp_path):
    for path in ("pkg/a.py", "pkg/sub/b.py", "pkg/__pycache__/c.py", "pkg/.hidden/d.py", "pkg/notes.txt", "tool.py"):
        write_file(path)

    found = library.discover_library_files([str(tmp_path / "pkg"), str(tmp_path / "tool.py"), str(tmp_path / "tool.py")])

    assert [os.path.relpath(path, tmp_path) for path in found] == [
        os.path.join("pkg", "a.py"), os.path.join("pkg", "sub", "b.py"), "tool.py"]


def test_a_path_is_under_a_root_it_is_or_sits_in(tmp_path):
    root = str(tmp_path / "cli")

    assert library.is_under(root, [root])
    assert library.is_under(os.path.join(root, "run.py"), [root])
    assert not library.is_under(str(tmp_path / "client.py"), [root])


@pytest.mark.parametrize("table, rule, reason", [
    ({"library_targets": []}, "no-print", "no library_targets"),
    ({}, "documented", "no doc_style"),
    ({}, "doc-paraphrase", "no doc_style"),
    ({"doc_style": "comment"}, "doc-length", "no doc_max_lines"),
    ({}, "wrappers", "no wrappers"),
    ({}, "no-exit", "no-exit is not in [tool.testrex] standards"),
])
def test_a_rule_says_why_it_is_off(tmp_path, table, rule, reason):
    assert reason in library.why_off(configured(tmp_path, **table), rule)


@pytest.mark.parametrize("table, rule", [
    ({"doc_style": "comment"}, "documented"),
    ({"doc_style": "comment", "doc_max_lines": 2}, "doc-length"),
    ({"wrappers": {"open": "fileops"}}, "wrappers"),
    ({"standards": ["no-print"]}, "no-print"),
])
def test_a_configured_rule_runs(tmp_path, table, rule):
    assert library.why_off(configured(tmp_path, **table), rule) is None


LIBRARY_SOURCE = '''
def run(items=[]):
    print(open("x").read())
'''


@pytest.mark.parametrize("table, rule, expected", [
    ({"doc_style": "comment"}, "documented", ["run (line 2)"]),
    ({"doc_style": "docstring"}, "documented", ["no module docstring", "run (line 2)"]),
    ({"doc_style": "comment"}, "doc-sections", []),
    ({"doc_style": "comment", "doc_max_lines": 1}, "doc-length", []),
    ({"doc_style": "comment"}, "doc-paraphrase", []),
    ({"wrappers": {"open": "fileops"}}, "wrappers", ["line 3: open, use fileops"]),
    ({"standards": ["no-print"]}, "no-print", ["line 3: print"]),
    ({"standards": ["mutable-defaults"]}, "mutable-defaults", ["run line 2"]),
    ({"standards": ["no-narration"]}, "no-narration", []),
    ({"standards": ["long-functions"], "max_function_lines": 1}, "long-functions", ["run line 2: 2 lines, at most 1"]),
    ({"standards": ["long-modules"]}, "long-modules", []),
])
def test_each_rule_finds_its_own_problems_in_a_file(write_file, tmp_path, table, rule, expected):
    path = write_file("pkg/mod.py", LIBRARY_SOURCE)

    assert library.file_findings(configured(tmp_path, **table), rule, str(path)) == expected


def test_a_module_longer_than_max_module_lines_is_found(write_file, tmp_path):
    path = write_file("pkg/mod.py", LIBRARY_SOURCE)

    found = library.file_findings(configured(tmp_path, standards = ["long-modules"], max_module_lines = 2), "long-modules", str(path))

    assert [finding.split(";")[0] for finding in found] == ["3 lines, at most 2"]


def test_the_wrappers_themselves_may_make_the_raw_calls(write_file, tmp_path):
    path = write_file("pkg/fileops.py", "def read(path):\n    return open(path).read()\n")
    loaded = configured(tmp_path, wrappers = {"open": "fileops"}, wrapper_modules = ["pkg/fileops.py"])

    assert library.file_findings(loaded, "wrappers", str(path)) == []


def test_commands_may_print_and_exit_but_keep_the_other_standards(write_file, tmp_path):
    path = write_file("pkg/cli/main.py", "import sys\ndef main(args=[]):\n    print(args)\n    sys.exit(0)\n")
    loaded = configured(tmp_path, standards = ["no-print", "no-exit", "mutable-defaults"], command_paths = ["pkg/cli"])

    assert library.file_findings(loaded, "no-print", str(path)) == []
    assert library.file_findings(loaded, "no-exit", str(path)) == []
    assert library.file_findings(loaded, "mutable-defaults", str(path)) == ["main line 2"]


def test_findings_name_the_file_they_are_in(write_file, tmp_path):
    first = write_file("pkg/a.py", "print(1)\n")
    second = write_file("pkg/b.py", "x = 1\nprint(2)\n")

    found = library.findings(configured(tmp_path, standards = ["no-print"]), "no-print", [str(first), str(second)])

    assert found == [os.path.join("pkg", "a.py") + ": line 1: print", os.path.join("pkg", "b.py") + ": line 2: print"]


def test_the_ratchet_holds_the_count_to_its_baseline():
    assert library.ratchet("no-print", ["a", "b"], 2) is None
    assert library.ratchet("no-print", ["a", "b"], 1) == "no-print: 2 finding(s), 1 allowed by the baseline\na\nb"
    assert library.ratchet("no-print", ["a"], 3) == (
        "no-print: 1 finding(s), fewer than the baseline of 3; lower [tool.testrex.baseline] no-print to 1 so they stay fixed")


def test_a_long_list_of_findings_is_cut_with_a_count(monkeypatch):
    monkeypatch.setattr(library, "MAX_LISTED", 2)

    assert library.ratchet("no-print", ["a", "b", "c", "d"], 0).splitlines()[1:] == ["a", "b", "... and 2 more"]
