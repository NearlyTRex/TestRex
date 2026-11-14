"""The JavaScript coverage plugin against real node: the coverage it writes, measured, and pytest runs end to end."""

import os
import subprocess
import textwrap

import pytest

from pytest_testrex import js_cov

pytestmark = [pytest.mark.integration, pytest.mark.requires_binary("node")]


def write(directory, name, text):
    path = directory / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def run_node(tmp_path, *args):
    """Run node in tmp_path with coverage on; the coverage directory it wrote to."""
    coverage_dir = tmp_path / "coverage"
    coverage_dir.mkdir(exist_ok=True)
    env = dict(os.environ, NODE_V8_COVERAGE=str(coverage_dir))
    subprocess.run(["node", *args], cwd=tmp_path, env=env, check=True, capture_output=True, text=True)
    return coverage_dir


def measure(tmp_path, coverage_dir, *names, branch=False):
    return js_cov.measure(str(tmp_path), [str(tmp_path / name) for name in names], branch=branch,
                          coverage_dir=coverage_dir)


# --- what node writes, measured --------------------------------------------------

def test_commonjs_misses_only_the_function_never_called(tmp_path):
    write(tmp_path, "lib.js", """\
        function used(x) {
          return x + 1;
        }
        function never() {
          return 0;
        }
        module.exports = { used, never };
        """)
    write(tmp_path, "main.js", """\
        const lib = require("./lib");
        lib.used(1);
        """)
    results = measure(tmp_path, run_node(tmp_path, "main.js"), "lib.js", "main.js")
    assert results["lib.js"]["missed_source"] == ["return 0;"]
    assert results["lib.js"]["statements"] == 5
    assert results["main.js"]["missed"] == []


def test_esm_modules_are_measured(tmp_path):
    write(tmp_path, "lib.mjs", """\
        export function half(x) {
          if (x % 2) {
            throw new Error("odd");
          }
          return x / 2;
        }
        export const unused = () => 1;
        """)
    write(tmp_path, "main.mjs", """\
        import { half } from "./lib.mjs";
        console.log(half(4));
        """)
    results = measure(tmp_path, run_node(tmp_path, "main.mjs"), "lib.mjs", "main.mjs")
    assert results["lib.mjs"]["missed_source"] == ['throw new Error("odd");']
    assert results["main.mjs"]["covered"] == 2


def test_a_child_process_node_starts_is_measured_too(tmp_path):
    write(tmp_path, "parent.cjs", """\
        const { spawnSync } = require("child_process");
        spawnSync(process.execPath, ["child.cjs"], { stdio: "inherit" });
        """)
    write(tmp_path, "child.cjs", """\
        const ran = true;
        console.log(ran);
        """)
    results = measure(tmp_path, run_node(tmp_path, "parent.cjs"), "child.cjs")
    assert results["child.cjs"] == {"statements": 2, "covered": 2, "missed": [], "missed_source": []}


def test_node_test_workers_are_measured(tmp_path):
    write(tmp_path, "lib.js", """\
        exports.sign = (x) => {
          if (x < 0) {
            return -1;
          }
          return 1;
        };
        """)
    write(tmp_path, "lib.test.js", """\
        const test = require("node:test");
        const assert = require("node:assert");
        const { sign } = require("./lib");
        test("positive", () => {
          assert.strictEqual(sign(2), 1);
        });
        """)
    results = measure(tmp_path, run_node(tmp_path, "--test", "lib.test.js"), "lib.js")
    assert results["lib.js"]["missed_source"] == ["return -1;"]


def test_offsets_after_text_that_is_not_ascii_are_right(tmp_path):
    write(tmp_path, "wide.js", """\
        const s = "é😀𝄞";
        function f(x) {
          if (x) {
            return "ü😀";
          }
          return s;
        }
        f(false);
        """)
    results = measure(tmp_path, run_node(tmp_path, "wide.js"), "wide.js")
    assert results["wide.js"]["missed_source"] == ['return "ü😀";']


def test_branch_mode_names_the_arms_never_taken(tmp_path):
    write(tmp_path, "branches.js", """\
        function pick(x) {
          const a = x && "rhs";
          const b = x || "fallback";
          const c = x ?? "none";
          return x ? "yes" : "no";
        }
        pick(1);
        """)
    coverage_dir = run_node(tmp_path, "branches.js")
    assert measure(tmp_path, coverage_dir, "branches.js")["branches.js"]["missed"] == []
    result = measure(tmp_path, coverage_dir, "branches.js", branch=True)["branches.js"]
    assert result["missed_source"] == ['|| "fallback"', '?? "none"', ': "no"']


# --- end to end ---------------------------------------------------------

@pytest.fixture
def project(pytester, monkeypatch):
    monkeypatch.delenv("NODE_V8_COVERAGE", raising=False)
    (pytester.path / "src").mkdir()
    write(pytester.path / "src", "greet.js", """\
        function greet(name) {
          return name ? `hello ${name}` : "hello";
        }
        console.log(greet(process.argv[2]));
        """)
    pytester.makepyfile(test_greet="""\
        import os
        import subprocess

        def test_plain():
            out = subprocess.run(["node", "src/greet.js"], capture_output=True, text=True, check=True)
            assert out.stdout == "hello\\n"

        def test_named(js_traced_env):
            env = js_traced_env({"PATH": os.environ["PATH"]})
            out = subprocess.run(["node", "src/greet.js", "you"], env=env, capture_output=True, text=True,
                                 check=True)
            assert out.stdout == "hello you\\n"
        """)
    return pytester


def test_end_to_end_full_coverage(project):
    result = project.runpytest("--js-cov-source", "src", "--js-cov-branch", "--js-cov-fail-under", "100")
    result.stdout.fnmatch_lines(["*javascript coverage*", "JavaScript coverage (branches count as statements)",
                                 "*greet.js*100.0%*", "Floor: 100.0% (met)"])
    assert result.ret == 0
    assert "NODE_V8_COVERAGE" not in os.environ


def test_end_to_end_a_missed_arm_fails_the_floor(project):
    result = project.runpytest("--js-cov-source", "src", "--js-cov-branch", "--js-cov-fail-under", "100",
                               "-k", "plain")
    result.stdout.fnmatch_lines(["*greet.js:2  ? `hello ${name}`", "Floor: 100.0% (NOT MET)"])
    assert result.ret == pytest.ExitCode.TESTS_FAILED


def test_end_to_end_disabled_by_default(project):
    result = project.runpytest()
    assert result.ret == 0
    assert "javascript coverage" not in result.stdout.str()
