# Imports
import textwrap

# Third-party imports
import pytest

###########################################################
# Standalone test files under their real runners
###########################################################

CONFIGURED = "[tool.testrex]\nsuites = ['integration']\n"

NODE_TESTS = """
    const test = require("node:test");
    const assert = require("node:assert");

    test("adds", () => {
        assert.strictEqual(1 + 1, 2);
    });

    test("subtracts", () => {
        assert.strictEqual(2 - 1, 0);
    });
    """

BUSTED_TESTS = """
    describe("arithmetic", function()
        it("adds", function()
            assert.are.equal(2, 1 + 1)
        end)

        it("subtracts", function()
            assert.are.equal(0, 2 - 1)
        end)
    end)
    """


def write_tests(pytester, name, text):
    pytester.makepyprojecttoml(CONFIGURED)
    path = pytester.path / "Tests" / "integration" / name
    path.parent.mkdir(parents = True)
    path.write_text(textwrap.dedent(text), encoding = "utf-8")


@pytest.mark.requires_binary("node")
def test_node_runs_a_javascript_test_file_and_names_its_failures(pytester):
    write_tests(pytester, "arithmetic.test.js", NODE_TESTS)

    result = pytester.runpytest("-p", "no:cacheprovider")

    result.assert_outcomes(failed = 1)
    result.stdout.fnmatch_lines(["failed: subtracts"])


@pytest.mark.requires_binary("node")
def test_node_passes_a_clean_javascript_test_file(pytester):
    write_tests(pytester, "arithmetic.test.mjs", 'import test from "node:test";\ntest("runs", () => {});\n')

    result = pytester.runpytest("-p", "no:cacheprovider")

    result.assert_outcomes(passed = 1)


@pytest.mark.requires_binary("busted")
def test_busted_runs_a_lua_spec_and_names_its_failures(pytester):
    write_tests(pytester, "arithmetic_spec.lua", BUSTED_TESTS)

    result = pytester.runpytest("-p", "no:cacheprovider")

    result.assert_outcomes(failed = 1)
    result.stdout.fnmatch_lines(["failed: arithmetic subtracts"])
