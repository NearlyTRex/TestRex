# Imports
import json
import os
import subprocess

# Third-party imports
import pytest

# Local imports
from pytest_testrex import lint, settings


def shipped_rcfile(tmp_path):
    return settings.from_table({}, str(tmp_path)).rcfile


def test_every_conftest_directory_is_an_import_root(tmp_path):
    files = [str(tmp_path / "unit" / "conftest.py"), str(tmp_path / "unit" / "test_a.py"), str(tmp_path / "unit" / "sub" / "conftest.py")]

    assert lint.import_roots(str(tmp_path), files) == sorted(
        [str(tmp_path), str(tmp_path / "unit"), str(tmp_path / "unit" / "sub")])


def test_the_targets_are_the_suites_and_the_shared_files_at_the_top(write_file, tmp_path):
    write_file("conftest.py")
    write_file("fakes.py")
    write_file("README.md")

    assert lint.pylint_targets(str(tmp_path), ["unit/test_a.py"]) == [
        "unit/test_a.py", os.path.join(str(tmp_path), "conftest.py"), os.path.join(str(tmp_path), "fakes.py")]


def test_pylint_reports_a_finding_it_is_given(write_file, tmp_path):
    sample = write_file("sample.py", "import os\n")

    result = lint.run_pylint(shipped_rcfile(tmp_path), str(tmp_path), [str(tmp_path)], str(sample))

    assert result.returncode != 0
    assert "unused-import" in result.stdout


def test_the_shipped_rcfile_allows_pytest_idioms(write_file, tmp_path):
    sample = write_file("test_sample.py", """
        import pytest


        @pytest.fixture
        def server(tmp_path):
            return tmp_path


        def test_x(server, monkeypatch):
            assert server
        """)

    result = lint.run_pylint(shipped_rcfile(tmp_path), str(tmp_path), [str(tmp_path)], str(sample))

    assert result.returncode == 0, result.stdout


def test_only_the_named_rules_run(write_file, tmp_path):
    sample = write_file("sample.py", "import os\nwith open('x') as handle:\n    handle.read()\n")

    result = lint.run_pylint(shipped_rcfile(tmp_path), str(tmp_path), [], *lint.only_rules(["unspecified-encoding"]), str(sample))

    assert result.returncode != 0
    assert "unspecified-encoding" in result.stdout
    assert "unused-import" not in result.stdout


###########################################################
# eslint and luacheck, with the programs faked
###########################################################

# Stands in for subprocess.run: records each command and answers with a version or a clean run
@pytest.fixture
def commands(monkeypatch):
    ran = []

    def run(command, **kwargs):
        ran.append((command, kwargs["cwd"]))
        return subprocess.CompletedProcess(command, 0, "v8.57.0\n" if command[1:] == ["--version"] else "", "")
    monkeypatch.setattr(subprocess, "run", run)
    return ran


def test_a_program_is_installed_when_it_is_on_path(write_file, tmp_path, monkeypatch):
    tool = write_file("bin/tool")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    assert lint.installed("tool")
    assert not lint.installed("absent")


@pytest.mark.parametrize("printed, major", [("v6.4.0\n", 6), ("9.12.1", 9), ("unknown", 0)])
def test_the_eslint_major_version_is_read_from_its_version(monkeypatch, tmp_path, printed, major):
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, printed, ""))

    assert lint.eslint_major(str(tmp_path)) == major


@pytest.mark.parametrize("name, text, found", [
    ("eslint.config.mjs", "export default [];", True),
    (".eslintrc.json", "{}", True),
    ("package.json", '{"eslintConfig": {}}', True),
    ("package.json", '{"name": "x"}', False),
    ("README.md", "", False),
])
def test_the_repository_eslint_config_is_found(write_file, tmp_path, name, text, found):
    write_file(name, text)

    assert lint.has_eslint_config(str(tmp_path)) is found


def test_the_shipped_eslint_config_matches_the_eslint(tmp_path):
    legacy = lint.eslint_config_arguments(str(tmp_path), "", 6)
    newer_legacy = lint.eslint_config_arguments(str(tmp_path), "", 8)
    flat = lint.eslint_config_arguments(str(tmp_path), "", 9)

    assert legacy == ["--no-eslintrc", "--config", lint.shipped("eslintrc.json")]
    assert newer_legacy == legacy + ["--env", "es2022", "--parser-options", "ecmaVersion:2022"]
    assert flat == ["--config", lint.shipped("eslint.config.mjs")]
    assert os.path.isfile(lint.shipped("eslintrc.json")) and os.path.isfile(lint.shipped("eslint.config.mjs"))


def test_a_configured_eslint_config_replaces_every_other(write_file, tmp_path):
    write_file(".eslintrc.json", "{}")

    assert lint.eslint_config_arguments(str(tmp_path), "lint/rc.json", 8) == ["--no-eslintrc", "--config", "lint/rc.json"]
    assert lint.eslint_config_arguments(str(tmp_path), "lint/eslint.config.js", 9) == ["--config", "lint/eslint.config.js"]


def test_the_repository_eslint_config_is_left_to_eslint_to_find(write_file, tmp_path):
    write_file("eslint.config.js", "export default [];")

    assert lint.eslint_config_arguments(str(tmp_path), "", 9) == []


def test_the_shipped_legacy_config_extends_the_recommended_rules():
    with open(lint.shipped("eslintrc.json"), encoding = "utf-8") as handle:
        config = json.load(handle)

    assert config["extends"] == "eslint:recommended"
    assert config["overrides"] == [{"files": ["*.cjs"], "parserOptions": {"sourceType": "script"}}]


def test_eslint_runs_over_the_files_from_the_repository(commands, tmp_path):
    result = lint.run_eslint(str(tmp_path), "", ["a.test.js"])

    assert result.returncode == 0
    assert commands == [
        (["eslint", "--version"], str(tmp_path)),
        (["eslint", "--no-color", "--max-warnings", "0", "--no-eslintrc", "--config", lint.shipped("eslintrc.json"),
          "--env", "es2022", "--parser-options", "ecmaVersion:2022", "a.test.js"], str(tmp_path))]


def test_luacheck_gives_test_files_the_busted_globals_without_a_config(tmp_path):
    assert lint.luacheck_runs(str(tmp_path), "", ["a_spec.lua"], ["a.lua"]) == [
        ["--no-config", "--std", "max+busted", "a_spec.lua"], ["--no-config", "--std", "max", "a.lua"]]
    assert lint.luacheck_runs(str(tmp_path), "", [], ["a.lua"]) == [["--no-config", "--std", "max", "a.lua"]]
    assert lint.luacheck_runs(str(tmp_path), "", ["a_spec.lua"], []) == [["--no-config", "--std", "max+busted", "a_spec.lua"]]


def test_luacheck_reads_everything_under_a_configured_or_repository_config(write_file, tmp_path):
    assert lint.luacheck_runs(str(tmp_path), "rc.lua", ["a_spec.lua"], ["a.lua"]) == [["--config", "rc.lua", "a_spec.lua", "a.lua"]]

    write_file(".luacheckrc", "std = 'max'\n")
    assert lint.luacheck_runs(str(tmp_path), "", ["a_spec.lua"], ["a.lua"]) == [["a_spec.lua", "a.lua"]]


def test_luacheck_runs_once_per_argument_list(commands, tmp_path):
    results = lint.run_luacheck(str(tmp_path), "", ["a_spec.lua"], ["a.lua"])

    assert [result.returncode for result in results] == [0, 0]
    assert [command for command, _ in commands] == [
        ["luacheck", "--no-color", "--codes", "--no-config", "--std", "max+busted", "a_spec.lua"],
        ["luacheck", "--no-color", "--codes", "--no-config", "--std", "max", "a.lua"]]
