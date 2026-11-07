# Imports
import os

# Third-party imports
import pytest

# Local imports
from pytest_testrex import discovery, parsers


def test_python_files_are_found_under_every_suite_but_not_in_caches_or_data(write_file, tmp_path):
    for path in ("unit/test_a.py", "unit/a_helpers.py", "unit/__pycache__/test_c.py",
                 "unit/fixtures/test_d.py", "integration/sub/test_b.py", "unit/notes.txt"):
        write_file(path)
    suites = [str(tmp_path / "unit"), str(tmp_path / "integration")]
    ignored = [str(tmp_path / "unit" / "fixtures")]

    tests = discovery.discover_python_files(suites, True, ignored)
    everything = discovery.discover_python_files(suites, False, ignored)

    assert [os.path.relpath(path, tmp_path) for path in tests] == [
        os.path.join("integration", "sub", "test_b.py"), os.path.join("unit", "test_a.py")]
    assert len(everything) == 3


def test_tests_are_collected_from_the_module_and_test_classes(parse_sample):
    tree = parse_sample("""
        def test_a(): pass
        async def test_b(): pass
        def helper(): pass
        class TestC:
            def test_d(self): pass
            def setup(self): pass
        class Helper:
            def test_e(self): pass
        """)

    assert [node.name for node in discovery.collected_tests(tree)] == ["test_a", "test_b", "test_d"]


def test_a_test_class_that_only_inherits_its_tests_still_defines_tests(parse_sample):
    assert discovery.defines_tests(parse_sample("class TestRex(suite.TestRex):\n    pass\n"))
    assert not discovery.defines_tests(parse_sample("class Helper:\n    def test_a(self): pass\n"))


def test_fixtures_and_their_parameters_are_read(parse_sample):
    fixture, plain = parse_sample("""
        @pytest.fixture(scope = "session")
        def server(tmp_path, /, port, *, host): pass
        def plain(a): pass
        """).body

    assert discovery.is_fixture(fixture)
    assert not discovery.is_fixture(plain)
    assert discovery.parameter_names(fixture) == ["tmp_path", "port", "host"]


def test_a_helper_module_is_found_beside_or_above_the_test_within_the_tests(write_file, tmp_path):
    helper = write_file("Tests/unit/pkg_helpers.py")
    top = write_file("Tests/shared.py")
    write_file("elsewhere.py")
    test = str(tmp_path / "Tests" / "unit" / "deep" / "test_x.py")
    tests_dir = str(tmp_path / "Tests")

    assert discovery.find_helper_module(test, "pkg_helpers", tests_dir) == str(helper)
    assert discovery.find_helper_module(test, "shared", tests_dir) == str(top)
    assert discovery.find_helper_module(test, "elsewhere", tests_dir) is None


def test_a_file_outside_the_tests_finds_no_helpers(tmp_path):
    assert discovery.find_helper_module(str(tmp_path / "x" / "test_x.py"), "x", str(tmp_path / "Tests")) is None


def test_checking_helpers_are_followed_through_imports(write_file, tmp_path):
    write_file("Tests/check_helpers.py", "def check_one(x):\n    assert x\ndef build():\n    return 1\n")
    write_file("Tests/unit/more_helpers.py", "from check_helpers import check_one\ndef check_two(x):\n    check_one(x)\n")
    test = write_file("Tests/unit/test_x.py", """
        import more_helpers
        import os
        from check_helpers import check_one as verify, build
        from . import relative
        def test_x():
            verify(build())
        """)

    names = discovery.checker_names(str(test), str(tmp_path / "Tests"))

    assert names == {"verify", "check_one", "check_two"}


def test_helpers_that_import_each_other_do_not_loop(write_file, tmp_path):
    write_file("Tests/a_helpers.py", "from b_helpers import check_b\ndef check_a(x):\n    check_b(x)\n")
    write_file("Tests/b_helpers.py", "import a_helpers\ndef check_b(x):\n    assert x\n")

    names = discovery.checker_names(str(tmp_path / "Tests" / "a_helpers.py"), str(tmp_path / "Tests"))

    assert names == {"check_a", "check_b"}

###########################################################
# Standalone JavaScript and Lua tests
###########################################################

JAVASCRIPT = discovery.SCRIPT_LANGUAGES["javascript"]
LUA = discovery.SCRIPT_LANGUAGES["lua"]
PATTERNS = {"javascript": ("*.test.js", "*.test.mjs"), "lua": ("*_spec.lua",)}

JS_TESTS = """
const assert = require("node:assert");
function check(v) { assert.ok(v); }
const viaCheck = (v) => { check(v); };
let declared;
const plain = 1;
describe("group", () => {
  it("works", () => { viaCheck(1); });
  test("sub", async (t) => { await t.test("inner", () => { t.assert.ok(1); }); });
  test.skip(() => { run(); });
  test.todo("later");
});
"""

LUA_TESTS = """
local function check(v) assert.is_true(v) end
local via_check = function(v) check(v) end
local a, b = function() end, 2
local plain = 3
function M:method() return 1 end
describe("group", function()
  it("works", function() via_check(1) end)
  spec([[long]], function() M:method() end)
  pending("later")
end)
"""


def test_a_file_name_picks_its_language_from_the_patterns():
    assert discovery.script_language("greet.test.mjs", PATTERNS) == "javascript"
    assert discovery.script_language("greet_spec.lua", PATTERNS) == "lua"
    assert discovery.script_language("greet.test.cjs", PATTERNS) is None


def test_script_tests_are_found_under_the_suites_but_not_in_modules_or_data(write_file, tmp_path):
    for path in ("unit/a.test.js", "unit/node_modules/b.test.js", "unit/data/c_spec.lua",
                 "integration/sub/d_spec.lua", "unit/e.js"):
        write_file(path)
    suites = [str(tmp_path / "unit"), str(tmp_path / "integration")]

    found = discovery.discover_script_tests(suites, PATTERNS, [str(tmp_path / "unit" / "data")])

    assert [os.path.relpath(path, tmp_path) for path in found] == [
        os.path.join("integration", "sub", "d_spec.lua"), os.path.join("unit", "a.test.js")]


def test_a_script_is_parsed_once_with_its_grammar(write_file):
    path = str(write_file("a.test.js", "test('a', () => {});\n"))

    tree = discovery.parsed_script(path, "javascript")

    assert tree.type == "program"
    assert discovery.parsed_script(path, "javascript") is tree


def test_javascript_tests_are_every_test_and_it_call_with_their_callbacks():
    tests = discovery.script_tests(parsers.parse("javascript", JS_TESTS), JAVASCRIPT)

    assert [label for label, _ in tests] == [
        '"works" (line 8)', '"sub" (line 9)', '"inner" (line 9)', "<unnamed> (line 10)", '"later" (line 11)']
    assert [callback is None for _, callback in tests] == [False, False, False, False, True]


def test_javascript_checkers_are_functions_that_assert_directly_or_through_one_another():
    assert discovery.script_checkers(parsers.parse("javascript", JS_TESTS), JAVASCRIPT) == {"check", "viaCheck"}


def test_lua_tests_are_every_it_test_and_spec_call():
    tree = parsers.parse("lua", LUA_TESTS)

    assert [label for label, _ in discovery.script_tests(tree, LUA)] == ['"works" (line 8)', "[[long]] (line 9)"]
    assert discovery.script_checkers(tree, LUA) == {"check", "via_check"}


def test_lua_methods_are_named_with_a_dot():
    tree = parsers.parse("lua", LUA_TESTS)

    assert ("M.method", "function_declaration") in [(name, node.type) for name, node in discovery.script_functions(tree, LUA)]


@pytest.mark.parametrize("name, expected", [
    ("assert", True), ("assert.strictEqual", True), ("t.assert.ok", True), ("self.assertEqual", True),
    ("expect", True), ("expected.value", False), ("greet", False)])
def test_assertions_are_named_assert_or_expect(name, expected):
    assert discovery.is_assertion_name(name) is expected
