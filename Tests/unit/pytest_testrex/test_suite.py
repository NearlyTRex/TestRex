# Imports
import glob
import inspect
import os
import subprocess
import textwrap

# Third-party imports
import pytest

# Local imports
from pytest_testrex import lint, suite
from pytest_testrex.parsers import ParserMissing
from pytest_testrex.settings import LIBRARY_RULES

###########################################################
# The suite end to end
#
# A sample repository is written with pytester and the suite run over it the
# way a repository runs it. A clean one passes every rule; a broken one fails
# every rule at least once, so no rule is wired up in a way that cannot fail.
# eslint, luacheck and ruff are faked here, failing a file that holds UNUSED;
# the integration suite runs eslint and luacheck for real.
###########################################################

META = "from pytest_testrex import suite\n\n\nclass TestRex(suite.TestRex):\n    pass\n"

CLEAN_SETTINGS = """
    [tool.testrex]
    suites = ["unit", "integration"]
    signature_packages = ["pkg"]
    library_targets = ["pkg"]
    sealed_programs = ["sudo"]
    doc_style = "comment"
    doc_max_lines = 2
    wrappers = { "json.dumps" = "pkg.serialization.dumps" }
    wrapper_modules = ["pkg/serialization.py"]
    command_paths = ["pkg/cli.py"]
    require_tests_for = ["lib"]
    js_sources = ["lib"]
    lua_sources = ["lib/greet.lua"]
    standards = [
        "no-print", "no-exit", "mutable-defaults", "bare-except", "silent-except", "import-time-io",
        "no-narration", "commented-out-code", "blanket-suppression", "long-functions", "long-modules",
    ]
    """

CLEAN_FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": """
        # The method every tool overrides
        class Base:
            # Hand a back unchanged
            def run(self, a):
                return a


        # A tool that pairs its input with an optional extra
        class Child(Base):
            # Pair a with b
            def run(self, a, b = None):
                return a, b


        # Everything in a UTF-8 text file
        def read(path):
            with open(path, encoding = "utf-8") as handle:
                return handle.read()
        """,
    "pkg/serialization.py": """
        import json


        # Data as JSON text with sorted keys
        def dumps(data):
            return json.dumps(data, sort_keys = True)
        """,
    "pkg/cli.py": """
        import sys


        # Print the arguments and exit with success
        def main(args):
            print(args)
            sys.exit(0)
        """,
    "pkg/big.py": "",
    "lib/greet.js": "exports.greet = (name) => `hello ${name}`;\n",
    "lib/greet.lua": "return { greet = function(name) return 'hello ' .. name end }\n",
    "Tests/integration/lib/greet.test.js": """
        const test = require("node:test");
        const assert = require("node:assert");
        const { greet } = require("../../../lib/greet.js");

        test("greets", () => {
            assert.strictEqual(greet("you"), "hello you");
        });
        """,
    "Tests/integration/lib/greet_spec.lua": """
        local greet = require("lib.greet").greet

        describe("greet", function()
            it("greets", function()
                assert.are.equal("hello you", greet("you"))
            end)
        end)
        """,
    "Tests/unit/meta/test_rex.py": META,
    "Tests/unit/pkg/test_mod.py": """
        import pytest


        def double(value):
            return value * 2


        def test_double():
            assert double(2) == 4


        class TestMore:
            def test_twice(self):
                with pytest.raises(TypeError):
                    double(None)
        """,
    "Tests/unit/pkg/test_serialization.py": """
        from pkg.serialization import dumps


        def test_keys_are_sorted():
            assert dumps({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'
        """,
    "Tests/unit/pkg/test_cli.py": """
        import pytest

        from pkg.cli import main


        def test_main_exits_with_success(capsys):
            with pytest.raises(SystemExit) as exited:
                main(["x"])

            assert exited.value.code == 0
            assert capsys.readouterr().out == "['x']\\n"
        """,
    "Tests/unit/pkg/test_big/conftest.py": "",
    "Tests/unit/pkg/test_big/test_area.py": "def test_area():\n    assert len('ab') == 2\n",
    "Tests/integration/pkg/test_mod.py": """
        import subprocess

        import pytest

        pytestmark = [pytest.mark.integration, pytest.mark.requires_binary("python3")]


        def test_runs():
            assert subprocess.run(["python3", "-c", "pass"], check = False).returncode == 0
        """,
}

BROKEN_SETTINGS = """
    [tool.testrex]
    suites = ["unit", "integration", "empty"]
    max_lines = 60
    min_test_files = 100
    signature_packages = ["pkg"]
    library_targets = ["pkg"]
    doc_style = "comment"
    doc_max_lines = 1
    max_module_lines = 20
    wrappers = { "json.dumps" = "pkg.serialization.dumps" }
    standards = [
        "no-print", "no-exit", "mutable-defaults", "bare-except", "silent-except", "import-time-io",
        "no-narration", "commented-out-code", "blanket-suppression", "long-functions", "long-modules",
    ]
    """

BROKEN_MOD_TESTS = """
    import os
    import subprocess
    import shutil

    import pytest

    LIMIT = 1
    LIMIT = 2


    def helper():
        return 1


    def helper():
        return 2


    def shared(value):
        return value + 1


    def test_twice():
        assert shared(1) == 2


    def test_twice():
        assert shared(2) == 3


    def test_unchecked():
        shared(1)


    def test_conditional(flag):
        if flag:
            assert shared(1)


    def test_tautology():
        assert True


    def test_weak():
        assert shared(1) is not None


    def test_swallowed():
        try:
            shared(None)
        except TypeError:
            pass
        assert shared(1) == 2


    def test_generator():
        boom = lambda: (_ for _ in ()).throw(ValueError("x"))
        with pytest.raises(ValueError):
            boom()


    def test_gate():
        if not shutil.which("git"):
            pytest.skip("no git")
        assert shared(1) == 2


    @pytest.mark.requires_binary(NAME)
    def test_computed():
        assert shared(1) == 2


    def test_undeclared():
        assert subprocess.run(["git", "status"], check = False).returncode == 0


    def test_shell(shell_sandbox):
        assert shell_sandbox


    def leak():
        os.environ["LEAK"] = "1"


    def test_broad():
        with pytest.raises(Exception):
            shared(None)


    def test_crowded():
        with pytest.raises(TypeError):
            value = None
            shared(value)


    @pytest.mark.skip
    def test_skipped():
        assert shared(1) == 2


    UNUSED = 1  # noqa


    class TestDuplicate:
        def test_x(self):
            assert shared(1) == 2

        def test_x(self):
            assert shared(1) == 2


    import json
    """

BROKEN_FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": """
        import json
        import os  # noqa
        import sys

        HOME = os.environ["HOME"]


        class Base:
            def run(self, a):
                return a


        class Child(Base):
            def run(self, b):
                return b


        def read(path):
            with open(path) as handle:
                return handle.read()


        # Read the file
        def read_file(path):
            \"\"\"Read it.

            Args:
                name: Gone.
            \"\"\"
            return path


        # Save data as JSON,
        # then stop
        def save(data, seen=[]):
            print(json.dumps(data))
            sys.exit(1)
            # x = run()
            # Now fixed


        # Look through nested data
        def guard(data):
            try:
                pass
            except:
                pass
            for a in data:
                for b in a:
                    for c in b:
                        if c:
                            pass
        """,
    "pkg/orphan.py": "VALUE = 1  # pragma: no cover\n",
    "Tests/test_stray.py": "def test_stray():\n    assert len('a') == 1\n",
    "Tests/unit/meta/test_rex.py": META,
    "Tests/unit/pkg/test_mod.py": BROKEN_MOD_TESTS,
    "Tests/unit/pkg/test_other.py": """
        import pytest

        pytestmark = pytest.mark.integration


        def shared(value):
            return value + 1


        def test_other():
            assert shared(1) == 2
        """,
    "Tests/unit/pkg/test_empty.py": "VALUE = 1\n",
    "Tests/unit/pkg/test_split.py": "def test_split():\n    assert len('a') == 1\n",
    "Tests/unit/pkg/test_split/cases.py": "def test_hidden():\n    assert len('a') == 1\n",
    "Tests/unit/nowhere/test_lost.py": "def test_lost():\n    assert len('a') == 1\n",
    "Tests/integration/pkg/test_mod.py": "def test_in_process():\n    assert len('a') == 1\n",
    "Tests/empty/README.md": "",
    "Tests/unit/web/empty.test.js": "const UNUSED = 1;\n",
    "Tests/unit/web/greet.test.js": "test('only calls', () => { greet(); });\n",
    "Tests/unit/web/greet_spec.lua": "local UNUSED = 1\nit('only calls', function() greet() end)\n",
}


# Stands in for an eslint or luacheck run: fails when a file holds UNUSED
def fake_lint(files):
    dirty = []
    for path in files:
        with open(path, encoding = "utf-8") as handle:
            if "UNUSED" in handle.read():
                dirty.append(path)
    return subprocess.CompletedProcess(["lint"], 1 if dirty else 0, "\n".join(dirty), "")


# Stands in for a ruff run over a repository: fails when one of its Python files holds UNUSED
def fake_ruff(repo_root, check_format):
    return [fake_lint(glob.glob(os.path.join(repo_root, "**", "*.py"), recursive = True))]


# eslint, luacheck and ruff installed and faked, for a run in this process
@pytest.fixture
def linters(monkeypatch):
    monkeypatch.setattr(lint, "installed", lambda program: True)
    monkeypatch.setattr(lint, "ruff_command", lambda: ["ruff"])
    monkeypatch.setattr(lint, "run_ruff", fake_ruff)
    monkeypatch.setattr(lint, "run_eslint", lambda repo_root, configured, files: fake_lint(files))
    monkeypatch.setattr(lint, "run_luacheck", lambda repo_root, configured, tests, sources: [fake_lint(tests), fake_lint(sources)])


def write_repository(pytester, settings, files):
    pytester.makepyprojecttoml(textwrap.dedent(settings))
    for relative_path, text in files.items():
        path = pytester.path / relative_path
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding = "utf-8")
    pytester.syspathinsert()


def rule_names(reports):
    return {report.nodeid.split("::")[-1].split("[")[0] for report in reports}


def every_rule():
    return {name for name, _ in inspect.getmembers(suite.TestRex, inspect.isfunction) if name.startswith("test_")}


# The library rules a run reports on, from the ids of the parametrized check
def library_rules_in(reports):
    return {report.nodeid.split("[")[-1].rstrip("]") for report in reports
            if "::test_the_library_holds_to_the_rule[" in report.nodeid}


def run_the_suite(pytester):
    return pytester.inline_run(os.path.join("Tests", "unit", "meta"), "-p", "no:cacheprovider")


@pytest.mark.usefixtures("linters")
def test_a_clean_repository_passes_every_rule(pytester):
    write_repository(pytester, CLEAN_SETTINGS, CLEAN_FILES)

    passed, skipped, failed = run_the_suite(pytester).listoutcomes()

    assert [report.nodeid for report in failed] == []
    assert skipped == []
    assert rule_names(passed) == every_rule()
    assert library_rules_in(passed) == set(LIBRARY_RULES)


@pytest.mark.usefixtures("linters")
def test_a_broken_repository_fails_every_rule(pytester):
    write_repository(pytester, BROKEN_SETTINGS, BROKEN_FILES)

    _, _, failed = run_the_suite(pytester).listoutcomes()

    assert rule_names(failed) == every_rule()
    assert library_rules_in(failed) == set(LIBRARY_RULES)


def test_unconfigured_checks_skip(pytester):
    write_repository(pytester, "[tool.testrex]\nsuites = ['unit']\nintegration_suites = []\n", {
        "Tests/unit/meta/test_rex.py": META})

    _, skipped, _ = run_the_suite(pytester).listoutcomes()
    reasons = {report.longrepr[2] for report in skipped}

    assert "Skipped: no signature_packages in [tool.testrex]" in reasons
    assert "Skipped: no library_targets in [tool.testrex]" in reasons


def test_rules_turned_off_skip(pytester):
    write_repository(pytester, """
        [tool.testrex]
        library_targets = ["pkg"]
        integration_marker = ""
        pylint_source = false
        ruff = false
        check_coverage_config = false
        """, {
            "pkg/__init__.py": "",
            "lib/greet.js": "exports.greet = () => 1;\n",
            "Tests/integration/lib/greet.test.js": "test('greets', () => { assert.ok(1); });\n",
            "Tests/integration/pkg/test_run.py": "def test_run():\n    assert len('a') == 1\n",
            "Tests/unit/pkg/test_run.py": "def test_run():\n    assert len('a') == 1\n",
            "Tests/unit/meta/test_rex.py": META})

    _, skipped, _ = run_the_suite(pytester).listoutcomes()
    reasons = {report.longrepr[2] for report in skipped}

    assert {
        "Skipped: integration_marker is empty in [tool.testrex]", "Skipped: pylint_source is off in [tool.testrex]",
        "Skipped: ruff is off in [tool.testrex]", "Skipped: check_coverage_config is off in [tool.testrex]"} <= reasons


def test_a_script_test_carries_the_integration_marker_only_when_one_is_set(pytester):
    files = {"Tests/integration/lib/greet.test.js": "test('greets', () => { assert.ok(1); });\n"}
    write_repository(pytester, "[tool.testrex]\n", files)
    marked = pytester.inline_run("--collect-only", "-p", "no:cacheprovider", "-m", "integration")
    write_repository(pytester, "[tool.testrex]\nintegration_marker = ''\n", files)
    unmarked = pytester.inline_run("--collect-only", "-p", "no:cacheprovider", "-m", "integration")

    assert [item.path.name for item in marked.getcalls("pytest_collection_finish")[0].session.items] == ["greet.test.js"]
    assert unmarked.getcalls("pytest_collection_finish")[0].session.items == []


def test_script_rules_skip_without_their_linters(pytester, monkeypatch):
    write_repository(pytester, CLEAN_SETTINGS, CLEAN_FILES)
    monkeypatch.setattr(lint, "installed", lambda program: False)
    monkeypatch.setattr(lint, "ruff_command", lambda: None)

    _, skipped, _ = run_the_suite(pytester).listoutcomes()
    reasons = {report.longrepr[2] for report in skipped}

    assert reasons == {
        "Skipped: eslint not installed", "Skipped: luacheck not installed", "Skipped: ruff not installed"}


@pytest.mark.usefixtures("linters")
def test_script_rules_skip_without_the_grammar(pytester, monkeypatch):
    write_repository(pytester, CLEAN_SETTINGS, CLEAN_FILES)

    def missing(path, language):
        raise ParserMissing(f"reading {language} needs its grammar")
    monkeypatch.setattr(suite, "parsed_script", missing)

    _, skipped, _ = run_the_suite(pytester).listoutcomes()

    assert {report.nodeid.split("::")[-1] for report in skipped} == {
        f"{rule}[{os.path.join('integration', 'lib', name)}]" for name in ("greet.test.js", "greet_spec.lua")
        for rule in ("test_every_script_test_file_holds_at_least_one_test", "test_every_script_test_checks_something")}
    assert {report.longrepr[2] for report in skipped} == {
        "Skipped: reading javascript needs its grammar", "Skipped: reading lua needs its grammar"}


@pytest.mark.parametrize("argument", [
    "test_file", "python_file", "integration_file", "unit_file", "split_package", "mirror_directory",
    "script_test_file", "source_module"])
def test_every_parametrized_argument_is_used_by_a_rule(argument):
    assert any(argument in inspect.signature(member).parameters for _, member in inspect.getmembers(suite.TestRex, inspect.isfunction))
