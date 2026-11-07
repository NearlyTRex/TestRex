"""The Lua coverage plugin with real interpreters: the LUA_INIT hook in lua and luajit, and pytest runs that trace them."""

import os
import subprocess
import sys
import textwrap

import pytest

from pytest_testrex import lua_cov

# Each interpreter installed is held to the hook; the rest skip
LUAS = [
    pytest.param("lua5.1", marks=pytest.mark.requires_binary("lua5.1")),
    pytest.param("lua5.2", marks=pytest.mark.requires_binary("lua5.2")),
    pytest.param("lua5.3", marks=pytest.mark.requires_binary("lua5.3")),
    pytest.param("lua5.4", marks=pytest.mark.requires_binary("lua5.4")),
    pytest.param("lua", marks=pytest.mark.requires_binary("lua")),
    pytest.param("luajit", marks=pytest.mark.requires_binary("luajit")),
]


@pytest.fixture
def traced(tmp_path):
    """(environment running the hook, its trace directory), the hook written under tmp_path."""
    hook = tmp_path / "hook.lua"
    hook.write_text(lua_cov.TRACE_HOOK)
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    return lua_cov.traced_environment(os.environ, f"@{hook}", str(trace_dir)), trace_dir


def run_lua(lua, env, cwd, *args):
    return subprocess.run([lua, *args], env=env, cwd=cwd, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("lua", LUAS)
def test_traces_relative_scripts_their_modules_and_coroutines(lua, traced, tmp_path):
    env, trace_dir = traced
    project = tmp_path / "project"
    project.mkdir()
    (project / "mod.lua").write_text(textwrap.dedent("""\
        local M = {}
        function M.double(n)
            return n * 2
        end
        function M.never()
            return 0
        end
        return M
        """))
    (project / "main.lua").write_text(textwrap.dedent("""\
        package.path = "./?.lua;" .. package.path
        local mod = require("mod")
        local co = coroutine.wrap(function(n)
            coroutine.yield(mod.double(n))
        end)
        print(co(21))
        """))

    result = run_lua(lua, env, project, "main.lua")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "42\n"
    results = lua_cov.measure(str(project), [str(project)], str(trace_dir))
    assert results["main.lua"]["missed"] == []
    assert results["mod.lua"]["missed"] == [(6, 6)]


@pytest.mark.parametrize("lua", LUAS)
@pytest.mark.parametrize("ending, status", [
    ("", 0), ("error('boom')", 1), ("os.exit(3)", 3), ("os.exit(0, true)", 0)])
def test_every_way_of_ending_flushes_the_trace(lua, ending, status, traced, tmp_path):
    env, trace_dir = traced
    script = tmp_path / "end.lua"
    script.write_text(f"local x = 1\nx = x + 1\n{ending}\n")

    result = run_lua(lua, env, tmp_path, str(script))

    assert result.returncode == status, result.stderr
    assert lua_cov.read_traces(str(trace_dir)) == {
        os.path.realpath(script): {1, 2, 3} if ending else {1, 2}}


@pytest.mark.parametrize("lua", LUAS)
@pytest.mark.parametrize("init, shown", [("marker = 'from code'", "from code"), ("@{init_file}", "from file")])
def test_runs_the_lua_init_it_replaced(lua, init, shown, tmp_path):
    hook = tmp_path / "hook.lua"
    hook.write_text(lua_cov.TRACE_HOOK)
    (tmp_path / "traces").mkdir()
    (tmp_path / "init.lua").write_text("marker = 'from file'\n")
    script = tmp_path / "show.lua"
    script.write_text("print(marker)\n")
    base = {name: value for name, value in os.environ.items() if name not in lua_cov.ENVIRONMENT_VARIABLES}
    env = lua_cov.traced_environment(
        dict(base, LUA_INIT=init.format(init_file=tmp_path / "init.lua")), f"@{hook}", str(tmp_path / "traces"))

    result = run_lua(lua, env, tmp_path, str(script))

    assert result.stdout == shown + "\n", result.stderr


@pytest.mark.requires_binary("lua5.4")
def test_a_versioned_lua_init_wins_where_lua_reads_it(tmp_path):
    hook = tmp_path / "hook.lua"
    hook.write_text(lua_cov.TRACE_HOOK)
    (tmp_path / "traces").mkdir()
    script = tmp_path / "show.lua"
    script.write_text("print(marker)\n")
    base = {name: value for name, value in os.environ.items() if name not in lua_cov.ENVIRONMENT_VARIABLES}
    env = lua_cov.traced_environment(
        dict(base, LUA_INIT="marker = 'plain'", LUA_INIT_5_4="marker = 'versioned'"), f"@{hook}", str(tmp_path / "traces"))

    result = subprocess.run(["lua5.4", str(script)], env=env, capture_output=True, text=True, check=False)

    assert result.stdout == "versioned\n", result.stderr


# --- end to end ---------------------------------------------------------

def run_pytest(project, *args):
    env = {name: value for name, value in os.environ.items()
           if name not in lua_cov.ENVIRONMENT_VARIABLES and name != "PYTEST_ADDOPTS"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *args],
        cwd=project, env=env, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("lua", LUAS)
def test_end_to_end_inherited_and_built_environments(lua, tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "greet.lua").write_text(textwrap.dedent("""\
        local loud = arg[1] == "loud"
        if loud then
            print("HELLO")
        else
            print("hello")
        end
        """))
    (tmp_path / "test_greet.py").write_text(textwrap.dedent(f"""\
        import os
        import subprocess

        def test_quiet():
            out = subprocess.run([{lua!r}, "scripts/greet.lua"], capture_output=True, text=True, check=True)
            assert out.stdout == "hello\\n"

        def test_loud(lua_traced_env):
            out = subprocess.run([{lua!r}, "scripts/greet.lua", "loud"], env=lua_traced_env({{"PATH": os.environ["PATH"]}}),
                                 capture_output=True, text=True, check=True)
            assert out.stdout == "HELLO\\n"
        """))

    result = run_pytest(tmp_path, "--lua-cov-source", "scripts", "--lua-cov-fail-under", "100")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Total: 100.0%" in result.stdout
    assert "Floor: 100.0% (met)" in result.stdout
