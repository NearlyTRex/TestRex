# Imports
import os
import re

# Third-party imports
import pytest

# Local imports
from pytest_testrex import settings


def test_no_table_means_no_settings(write_file, tmp_path):
    write_file("pyproject.toml", "[project]\nname = 'x'\n")

    assert settings.load(str(tmp_path / "sub")) is None


def test_the_nearest_table_above_the_start_wins(write_file, tmp_path):
    write_file("pyproject.toml", "[tool.testrex]\nmax_lines = 10\n")
    write_file("inner/pyproject.toml", "[project]\nname = 'x'\n")
    (tmp_path / "inner" / "deep").mkdir()

    loaded = settings.load(str(tmp_path / "inner" / "deep"))

    assert loaded.repo_root == str(tmp_path)
    assert loaded.max_lines == 10


def test_defaults_fill_in_and_paths_are_absolute(tmp_path):
    loaded = settings.from_table({"library_targets": ["src"], "pylint_rcfile": "Tests/pylintrc"}, str(tmp_path))

    assert loaded.suite_dirs == (str(tmp_path / "Tests" / "unit"), str(tmp_path / "Tests" / "integration"))
    assert loaded.integration_dirs == (str(tmp_path / "Tests" / "integration"),)
    assert loaded.library_targets == (str(tmp_path / "src"),)
    assert loaded.rcfile == str(tmp_path / "Tests" / "pylintrc")
    assert loaded.fixture_programs["shell_sandbox"] == {"bash", "unshare"}


def test_the_shipped_rcfile_is_used_without_one(tmp_path):
    loaded = settings.from_table({}, str(tmp_path))

    assert os.path.basename(loaded.rcfile) == "pylintrc"
    assert os.path.isfile(loaded.rcfile)


def test_data_dirs_are_ignored_under_the_tests_dir(tmp_path):
    loaded = settings.from_table({"data_dirs": ["unit/fixtures"]}, str(tmp_path))

    assert loaded.ignored_dirs == (str(tmp_path / "Tests" / "unit" / "fixtures"),)


def test_requires_binary_always_leads_the_markers(tmp_path):
    loaded = settings.from_table({"requirement_markers": ["requires_tool", "requires_binary"]}, str(tmp_path))

    assert loaded.requirement_markers == ("requires_binary", "requires_tool")


def test_fixture_programs_add_to_the_shell_ones(tmp_path):
    loaded = settings.from_table({"fixture_programs": {"docker_compose": ["docker"]}}, str(tmp_path))

    assert loaded.fixture_programs == {"shell_sandbox": {"bash", "unshare"}, "shell_traced_env": {"bash"}, "docker_compose": {"docker"}}


@pytest.mark.parametrize("table, message", [
    ({"max_line": 3}, "has no setting 'max_line'"),
    ({"max_lines": "3"}, "max_lines must be a int"),
    ({"block_network": 1}, "block_network must be a bool"),
    ({"integration_suites": ["e2e"]}, "names suites not in suites: ['e2e']"),
    ({"doc_style": "javadoc"}, "doc_style must be one of ['comment', 'docstring', 'either'], not 'javadoc'"),
    ({"standards": ["no-prints"]}, "standards has no ['no-prints']"),
    ({"baseline": {"documentation": 3}}, "baseline has no rule ['documentation']"),
    ({"baseline": {"no-print": -1}}, "baseline counts must be whole numbers of findings: ['no-print']"),
    ({"baseline": {"no-print": 1.5}}, "baseline counts must be whole numbers of findings: ['no-print']"),
    ({"doc_max_lines": -1}, "doc_max_lines must be 0 (no limit) or more, not -1"),
    ({"max_nesting": 0}, "max_function_lines, max_nesting and max_module_lines must be at least 1"),
    ({"max_module_lines": 0}, "max_function_lines, max_nesting and max_module_lines must be at least 1"),
])
def test_a_wrong_setting_is_refused(tmp_path, table, message):
    with pytest.raises(settings.SettingsError, match = re.escape(message)):
        settings.from_table(table, str(tmp_path))


def test_library_paths_are_absolute_and_the_rest_is_kept(tmp_path):
    loaded = settings.from_table({
        "wrapper_modules": ["pkg/fileops.py"], "command_paths": ["pkg/cli"], "wrappers": {"open": "fileops"},
        "standards": ["no-print"], "baseline": {"no-print": 4}, "doc_style": "comment", "doc_max_lines": 2}, str(tmp_path))

    assert loaded.wrapper_modules == (str(tmp_path / "pkg" / "fileops.py"),)
    assert loaded.command_paths == (str(tmp_path / "pkg" / "cli"),)
    assert (loaded.wrappers, loaded.standards, loaded.baseline) == ({"open": "fileops"}, ("no-print",), {"no-print": 4})
    assert (loaded.doc_style, loaded.doc_max_lines, loaded.max_function_lines, loaded.max_nesting) == ("comment", 2, 40, 3)
    assert loaded.max_module_lines == 900
