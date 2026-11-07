# Third-party imports
import pytest

# Local imports
from pytest_testrex import lint

###########################################################
# eslint and luacheck, run for real with the shipped defaults
###########################################################

CLEAN_MODULE = 'import test from "node:test";\nimport assert from "node:assert";\ntest("a", () => { assert.ok(new URL("http://a")); });\n'
CLEAN_COMMONJS = 'const test = require("node:test");\nconst assert = require("node:assert");\ntest("a", () => { assert.ok(1); });\n'
DIRTY = 'const assert = require("node:assert");\nconst unused = 1;\nassert.ok(1);\n'

CLEAN_SPEC = 'describe("a", function()\n  it("adds", function()\n    assert.are.equal(2, 1 + 1)\n  end)\nend)\n'


@pytest.mark.requires_binary("eslint")
def test_eslint_passes_modules_and_commonjs_under_the_shipped_config(write_file, tmp_path):
    files = [str(write_file("a.test.mjs", CLEAN_MODULE)), str(write_file("b.test.cjs", CLEAN_COMMONJS)),
             str(write_file("c.test.js", CLEAN_MODULE))]

    result = lint.run_eslint(str(tmp_path), "", files)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.requires_binary("eslint")
def test_eslint_fails_an_unused_variable_under_the_shipped_config(write_file, tmp_path):
    result = lint.run_eslint(str(tmp_path), "", [str(write_file("a.test.js", DIRTY))])

    assert result.returncode != 0
    assert "no-unused-vars" in result.stdout


@pytest.mark.requires_binary("eslint")
def test_eslint_uses_the_configured_config(write_file, tmp_path):
    major = lint.eslint_major(str(tmp_path))
    if major >= lint.FLAT_ESLINT:
        config = write_file("lint.config.mjs", 'export default [{rules: {"no-console": "error"}}];\n')
    else:
        config = write_file("lint.json", '{"rules": {"no-console": "error"}}\n')

    result = lint.run_eslint(str(tmp_path), str(config), [str(write_file("a.test.js", "console.log(1);\n"))])

    assert result.returncode != 0
    assert "no-console" in result.stdout


@pytest.mark.requires_binary("luacheck")
def test_luacheck_allows_busted_globals_in_tests_but_not_in_sources(write_file, tmp_path):
    spec = str(write_file("a_spec.lua", CLEAN_SPEC))
    source = str(write_file("a.lua", 'it("leaks", function() end)\n'))

    clean, dirty = lint.run_luacheck(str(tmp_path), "", [spec], [source])

    assert clean.returncode == 0, clean.stdout
    assert dirty.returncode != 0
    assert "W113" in dirty.stdout
