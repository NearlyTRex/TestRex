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

    assert loaded.fixture_programs == {
        "shell_sandbox": {"bash", "unshare"}, "shell_traced_env": {"bash"}, "js_traced_env": {"node"},
        "lua_traced_env": {"lua5.4|lua|luajit"}, "docker_compose": {"docker"}}


def test_script_test_settings_default_to_node_and_busted_names_and_shipped_linter_configs(tmp_path):
    loaded = settings.from_table({}, str(tmp_path))

    assert loaded.script_test_patterns == {"javascript": ("*.test.js", "*.test.mjs", "*.test.cjs"), "lua": ("*_spec.lua",)}
    assert (loaded.js_sources, loaded.lua_sources, loaded.eslint_config, loaded.luacheck_config) == ((), (), "", "")
    assert {".js", ".mjs", ".cjs", ".lua"} <= set(loaded.source_extensions)


def test_script_test_settings_are_kept_with_paths_made_absolute(tmp_path):
    loaded = settings.from_table({
        "js_test_patterns": [], "lua_test_patterns": ["test_*.lua"], "js_sources": ["web"], "lua_sources": ["lua"],
        "eslint_config": "eslint.config.mjs", "luacheck_config": "lint/luacheckrc"}, str(tmp_path))

    assert loaded.script_test_patterns == {"javascript": (), "lua": ("test_*.lua",)}
    assert (loaded.js_sources, loaded.lua_sources) == ((str(tmp_path / "web"),), (str(tmp_path / "lua"),))
    assert loaded.eslint_config == str(tmp_path / "eslint.config.mjs")
    assert loaded.luacheck_config == str(tmp_path / "lint" / "luacheckrc")


@pytest.mark.parametrize("table, message", [
    ({"max_line": 3}, "has no setting 'max_line'"),
    ({"max_lines": "3"}, "max_lines must be a int"),
    ({"block_network": 1}, "block_network must be a bool"),
    ({"js_test_patterns": "*.test.js"}, "js_test_patterns must be a list"),
    ({"eslint_config": ["a"]}, "eslint_config must be a str"),
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


def test_the_new_rules_are_on_unless_turned_off(tmp_path):
    loaded = settings.from_table({}, str(tmp_path))

    assert loaded.integration_marker == "integration"
    assert (loaded.ruff, loaded.ruff_format) == (True, False)
    assert (loaded.pylint_source, loaded.require_tests, loaded.check_coverage_config) == (True, True, True)
    assert loaded.coverage_omit_allowed == ("Tests/*", ".venv/*", "venv/*")
    assert loaded.coverage_exclude_allowed == ("if __name__ == .__main__.:",)


def test_the_library_and_the_further_sources_need_tests_unless_require_tests_is_off(tmp_path):
    table = {"library_targets": ["pkg"], "require_tests_for": ["scripts", "run.py"], "tests_not_required": ["pkg/x.mjs"]}

    loaded = settings.from_table(table, str(tmp_path))
    off = settings.from_table(dict(table, require_tests = False), str(tmp_path))

    assert loaded.tested_sources == tuple(str(tmp_path / path) for path in ("pkg", "scripts", "run.py"))
    assert loaded.tests_not_required == (str(tmp_path / "pkg" / "x.mjs"),)
    assert off.tested_sources == ()


def test_the_library_rcfile_is_the_shipped_one_unless_the_repository_names_its_own(tmp_path):
    shipped = settings.from_table({}, str(tmp_path)).source_rcfile
    own = settings.from_table({"pylint_source_rcfile": "pyproject.toml"}, str(tmp_path)).source_rcfile

    assert shipped == os.path.join(os.path.dirname(settings.__file__), "library-pylintrc")
    assert os.path.isfile(shipped)
    assert own == str(tmp_path / "pyproject.toml")


def test_pylint_over_the_library_may_be_baselined(tmp_path):
    assert settings.from_table({"baseline": {"pylint-source": 12}}, str(tmp_path)).baseline == {"pylint-source": 12}


@pytest.mark.parametrize("value, expected, exact", [
    (True, bool, True), (1, int, True), (True, int, False), (1, bool, False), ("a", str, True), ([], list, True)])
def test_a_bool_is_only_a_bool_and_not_the_int_it_subclasses(value, expected, exact):
    assert settings.is_exactly(value, expected) is exact


@pytest.mark.parametrize("table, message", [
    ({"min_test_files": True}, "min_test_files must be a int"),
    ({"baseline": {"no-print": True}}, "baseline counts must be whole numbers of findings: ['no-print']"),
    ({"integration_marker": False}, "integration_marker must be a str"),
])
def test_a_bool_is_refused_where_a_number_or_name_is_wanted(tmp_path, table, message):
    with pytest.raises(settings.SettingsError, match = re.escape(message)):
        settings.from_table(table, str(tmp_path))
