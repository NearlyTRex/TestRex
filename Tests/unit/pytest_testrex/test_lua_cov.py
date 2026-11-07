"""The Lua coverage plugin in process: statements, traces, the hook inside lupa, the fixtures and the hooks."""

import importlib
import os
import textwrap
from types import SimpleNamespace

import pytest

from fixture_helpers import unwrap
from pytest_testrex import lua_cov, parsers, statement_coverage

# Looked up by name: pylint can't read members of the compiled module
LUA54 = importlib.import_module("lupa.lua54")

# Every Lua lupa ships, so the hook is held to 5.1 to 5.5 and LuaJIT
LUPA_MODULES = ["lua51", "lua52", "lua53", "lua54", "lua55", "luajit20", "luajit21"]

# Runs a coroutine both ways; lines 6, 8 and 13 run only inside them, 17 never
COROUTINES = """\
local x = 0
local function f(n)
    return n + 1
end
local co = coroutine.create(function()
    x = f(x)
    coroutine.yield()
    x = f(x)
end)
coroutine.resume(co)
coroutine.resume(co)
local g = coroutine.wrap(function(a)
    x = x + a
end)
g(5)
if x > 100 then
    x = 0
end
return x
"""


def write_lua(tmp_path, name, text):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))
    return path


@pytest.fixture
def traces(tmp_path, monkeypatch):
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    monkeypatch.setenv(lua_cov.TRACE_DIR_VARIABLE, str(trace_dir))
    return trace_dir


# --- statements ---------------------------------------------------------

def test_find_statements_reads_each_kind_and_nests():
    source = textwrap.dedent("""\
        local a = 1 -- a comment
        b = 2;
        print(a)
        do
            f(g(1))
        end
        while a < 3 do a = a + 1 end
        repeat
            a = a - 1
        until a < 0
        if a then
            break
        elseif b then
            goto done
        else
            return
        end
        for i = 1, 2 do end
        function t.m:n()
            return function() end
        end
        local h = function()
            return 1
        end
        t.x = f(
            1)
        obj:method()
        """)
    assert lua_cov.find_statements(source) == [
        (1, 1), (2, 2), (3, 3), (5, 5), (7, 7), (8, 10), (9, 9), (11, 17), (12, 12), (14, 14), (16, 16),
        (18, 18), (19, 21), (20, 20), (22, 24), (23, 23), (25, 26), (27, 27)]


def test_declarations_labels_and_empty_blocks_are_not_statements():
    source = "local a\nlocal b, c <const>\n::top::\ndo\nend\n;\n-- note\n"
    assert lua_cov.find_statements(source) == []


def test_find_statements_refuses_what_does_not_parse():
    with pytest.raises(lua_cov.LuaParseError, match="cannot parse it .near line 2"):
        lua_cov.find_statements("x = 1\nx = = 2\n")


# --- traces and measuring -----------------------------------------------

def test_parse_trace_resolves_relative_sources_against_the_start_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    text = (f"3\t{tmp_path}/abs.lua\ncwd\t{tmp_path}\n1\t./sub/x.lua\n2\tsub/x.lua\n"
            "noise\n7\t\n\n")
    assert lua_cov.parse_trace(text) == {
        os.path.realpath(tmp_path / "abs.lua"): {3}, os.path.realpath(tmp_path / "sub" / "x.lua"): {1, 2}}


def test_read_traces_merges_every_file(tmp_path):
    (tmp_path / "a.trace").write_text(f"1\t{tmp_path}/x.lua\n")
    (tmp_path / "b.trace").write_text(f"4\t{tmp_path}/x.lua\n")
    assert lua_cov.read_traces(str(tmp_path)) == {os.path.realpath(tmp_path / "x.lua"): {1, 4}}


def test_measure_reports_run_and_missed_statements(tmp_path):
    write_lua(tmp_path, "src/a.lua", "local x = 1\nif x then\n    print(x)\nelse\n    print(-x)\nend\n")
    write_lua(tmp_path, "src/vendor/v.lua", "x = 1\n")
    write_lua(tmp_path, "src/readme.txt", "x = 1\n")
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    (trace_dir / "1.trace").write_text(f"cwd\t{tmp_path}\n1\tsrc/a.lua\n2\tsrc/a.lua\n3\tsrc/a.lua\n")

    results = lua_cov.measure(str(tmp_path), [str(tmp_path / "src")], str(trace_dir), exclude=["src/vendor/*"])

    assert results == {os.path.join("src", "a.lua"): {
        "statements": 4, "covered": 3, "missed": [(5, 5)], "missed_source": ["print(-x)"]}}
    report = statement_coverage.render_report(results, 100, title="Lua coverage", label="Script")
    assert "src/a.lua:5  print(-x)" in report
    assert "Floor: 100.0% (NOT MET)" in report


def test_measure_names_the_source_it_cannot_read(tmp_path, monkeypatch):
    write_lua(tmp_path, "bad.lua", "x = = 1\n")
    (tmp_path / "traces").mkdir()
    with pytest.raises(lua_cov.LuaParseError, match="^bad.lua: tree-sitter-lua cannot parse it"):
        lua_cov.measure(str(tmp_path), [str(tmp_path)], str(tmp_path / "traces"))
    monkeypatch.setattr(statement_coverage, "MAX_SOURCE_BYTES", 3)
    with pytest.raises(lua_cov.LuaParseError, match="^bad.lua: larger than 3 bytes"):
        lua_cov.measure(str(tmp_path), [str(tmp_path)], str(tmp_path / "traces"))


# --- the hook, inside lupa ----------------------------------------------

@pytest.mark.parametrize("lua", LUPA_MODULES)
def test_hook_traces_files_and_coroutines_in_every_lua(lua, lua_runtime, tmp_path, traces):
    script = write_lua(tmp_path, "co.lua", COROUTINES)
    runner = lua_runtime(lua=lua)
    assert runner.run_file(script) == 7
    runner.close()

    lines = lua_cov.read_traces(str(traces))[os.path.realpath(script)]
    assert {3, 6, 8, 13, 15, 19} <= lines
    assert 17 not in lines
    assert lua_cov.measure_script(COROUTINES, lines)["missed"] == [(17, 17)]


def test_hook_ignores_chunks_not_loaded_from_files(lua_runtime, traces):
    runner = lua_runtime()
    runner.lua.execute("local y = 1\nreturn y")
    assert runner.lua.eval("coroutine.wrap(function() return 2 end)()") == 2
    runner.close()
    assert not os.listdir(traces)


def test_hook_keeps_wrap_refusing_what_is_not_a_function(lua_runtime, traces):
    runner = lua_runtime()
    with pytest.raises(LUA54.LuaError, match="wrap"):
        runner.lua.execute("coroutine.wrap(42)")


def test_relative_sources_record_the_directory_pwd_names(lua_runtime, tmp_path, traces, monkeypatch):
    write_lua(tmp_path, "rel.lua", "x = 1\n")
    monkeypatch.chdir(tmp_path)
    runner = lua_runtime()
    runner.lua.execute(f"io.popen = function() return {{read = function() return '{tmp_path}' end, close = function() end}} end")
    runner.lua.execute("loadfile('rel.lua')()")
    runner.close()
    (trace,) = traces.iterdir()
    assert trace.read_text() == f"cwd\t{tmp_path}\n1\trel.lua\n"


@pytest.mark.parametrize("popen, pwd, expected", [
    ("nil", "/from/pwd", "/from/pwd"),
    ("function() return nil end", "/from/pwd", "/from/pwd"),
    ("nil", None, "."),
])
def test_start_directory_falls_back_to_pwd(popen, pwd, expected, lua_runtime, tmp_path, traces, monkeypatch):
    write_lua(tmp_path, "rel.lua", "x = 1\n")
    monkeypatch.chdir(tmp_path)
    if pwd is None:
        monkeypatch.delenv("PWD", raising=False)
    else:
        monkeypatch.setenv("PWD", pwd)
    runner = lua_runtime()
    runner.lua.execute(f"io.popen = {popen}")
    runner.lua.execute("loadfile('rel.lua')()")
    runner.close()
    (trace,) = traces.iterdir()
    assert trace.read_text().splitlines()[0] == f"cwd\t{expected}"


def test_trace_names_never_collide(lua_runtime, tmp_path, traces):
    script = write_lua(tmp_path, "s.lua", "x = 1\n")
    for _ in range(3):
        runner = lua_runtime()
        runner.lua.execute("os.time = function() return 1 end; os.clock = function() return 0 end; "
                           "tostring = function() return 'same' end")
        runner.run_file(script)
        runner.close()
    assert sorted(path.name for path in traces.iterdir()) == ["1-0-same-1.trace", "1-0-same-2.trace", "1-0-same.trace"]


def test_an_unwritable_trace_directory_leaves_the_program_running(lua_runtime, tmp_path, monkeypatch):
    monkeypatch.setenv(lua_cov.TRACE_DIR_VARIABLE, str(tmp_path / "missing"))
    script = write_lua(tmp_path, "s.lua", "local x = 1\nreturn x + 1\n")
    runner = lua_runtime()
    assert runner.run_file(script) == 2
    assert runner.run_file(script) == 2
    runner.close()
    assert not (tmp_path / "missing").exists()


def test_hook_is_inert_without_a_trace_directory(monkeypatch):
    monkeypatch.delenv(lua_cov.TRACE_DIR_VARIABLE, raising=False)
    runtime = LUA54.LuaRuntime()
    assert runtime.execute(lua_cov.TRACE_HOOK, None, True) is None
    assert runtime.eval("(debug.gethook())") is None


# --- chaining the LUA_INIT it replaced ------------------------------------

@pytest.mark.parametrize("lua, variables, expected", [
    ("lua54", {"LUA_COV_INIT": "marker = 'plain'"}, "plain"),
    ("lua54", {"LUA_COV_INIT": "marker = 'plain'", "LUA_COV_INIT_5_4": "marker = 'versioned'"}, "versioned"),
    ("lua51", {"LUA_COV_INIT": "marker = 'plain'", "LUA_COV_INIT_5_1": "marker = 'versioned'"}, "plain"),
    ("luajit21", {"LUA_COV_INIT": "marker = 'plain'", "LUA_COV_INIT_5_4": "marker = 'versioned'"}, "plain"),
    ("lua53", {"LUA_COV_INIT_5_3": ""}, None),
    ("lua52", {}, None),
])
def test_hook_runs_the_init_it_replaced(lua, variables, expected, traces, monkeypatch):
    for name in lua_cov.ENVIRONMENT_VARIABLES + ("LUA_COV_INIT_5_1",):
        if name != lua_cov.TRACE_DIR_VARIABLE:
            monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    runner = lua_cov.LuaRunner(importlib.import_module("lupa." + lua))
    runner.lua.execute(lua_cov.TRACE_HOOK, None, False)
    assert runner.globals.marker == expected
    assert runner.lua.eval("(debug.gethook())") is not None


def test_hook_runs_an_init_file_and_reports_one_that_fails(tmp_path, traces, monkeypatch):
    init = write_lua(tmp_path, "init.lua", "marker = 'from file'\n")
    runtime = LUA54.LuaRuntime()
    monkeypatch.setenv("LUA_COV_INIT_5_4", f"@{init}")
    runtime.execute(lua_cov.TRACE_HOOK, None, False)
    assert runtime.globals().marker == "from file"
    monkeypatch.setenv("LUA_COV_INIT_5_4", "this is not lua")
    with pytest.raises(LUA54.LuaError, match="LUA_INIT"):
        LUA54.LuaRuntime().execute(lua_cov.TRACE_HOOK, None, False)
    monkeypatch.setenv("LUA_COV_INIT_5_4", f"@{tmp_path}/missing.lua")
    with pytest.raises(LUA54.LuaError, match="missing.lua"):
        LUA54.LuaRuntime().execute(lua_cov.TRACE_HOOK, None, False)


# --- lua_runtime ----------------------------------------------------------

# A WirePlumber-style script: it reads its arguments from `...` and reacts to
# objects the host announces
WIREPLUMBER_STYLE = """\
local args = ...
local om = ObjectManager { Interest { type = "node" } }
om:connect("object-added", function(_, node)
    if node.properties["media.class"] == args.class then
        Log.info("linking " .. node.name)
    else
        Log.info("ignoring " .. node.name)
    end
end)
om:activate()
"""


def fake_host(runner):
    """An ObjectManager that announces two nodes on activate, and a Log that keeps what it is told."""
    logged, interests = [], []
    callbacks = {}

    def activate(_):
        for name, media_class in (("mic", "Audio/Source"), ("speaker", "Audio/Sink")):
            node = runner.lua.table_from({"name": name, "properties": runner.lua.table_from({"media.class": media_class})})
            callbacks["object-added"](None, node)

    def object_manager(spec):
        interests.append(spec[1]["type"])
        return runner.lua.table_from({
            "connect": lambda _, signal, callback: callbacks.__setitem__(signal, callback), "activate": activate})

    runner.globals.Interest = lambda spec: spec
    runner.globals.ObjectManager = object_manager
    runner.globals.Log = runner.lua.table_from({"info": logged.append})
    return logged, interests


def test_lua_runtime_runs_a_host_script_with_arguments_and_fakes(lua_runtime, tmp_path, traces):
    script = write_lua(tmp_path, "scripts/link.lua", WIREPLUMBER_STYLE)
    runner = lua_runtime()
    logged, interests = fake_host(runner)

    runner.run_file(script, runner.lua.table_from({"class": "Audio/Source"}))
    runner.close()

    assert interests == ["node"]
    assert logged == ["linking mic", "ignoring speaker"]
    results = lua_cov.measure(str(tmp_path), [str(tmp_path / "scripts")], str(traces))
    assert results[os.path.join("scripts", "link.lua")]["missed"] == []


def test_lua_runtime_without_coverage_installs_no_hook(lua_runtime, monkeypatch):
    monkeypatch.delenv(lua_cov.TRACE_DIR_VARIABLE, raising=False)
    runner = lua_runtime(lua="lua53", unpack_returned_tuples=True)
    assert runner.stop_trace is None
    assert runner.lua.eval("_VERSION") == "Lua 5.3"
    assert runner.lua.eval("(debug.gethook())") is None


def test_lua_runtime_reports_a_file_it_cannot_load(lua_runtime, tmp_path):
    with pytest.raises(LUA54.LuaError, match="nope.lua"):
        lua_runtime().run_file(tmp_path / "nope.lua")


def test_lua_runtime_without_lupa_says_how_to_install_it(lua_runtime):
    with pytest.raises(pytest.fail.Exception, match=r'pip install "pytest-testrex\[lua\]"'):
        lua_runtime(lua="lua99")


def test_lua_runtime_closes_its_runners_at_teardown(tmp_path, traces):
    script = write_lua(tmp_path, "s.lua", "x = 1\n")
    fixture = unwrap(lua_cov.lua_runtime)()
    make = next(fixture)
    make().run_file(script)
    with pytest.raises(StopIteration):
        next(fixture)
    (trace,) = traces.iterdir()
    assert trace.read_text() == f"1\t{os.path.realpath(script)}\n"


# --- the environment ------------------------------------------------------

def test_traced_environment_chains_what_was_there_and_is_idempotent():
    env = {"LUA_INIT": "x = 1", "LUA_INIT_5_4": "@/init.lua", "LUA_COV_INIT_5_3": "stale", "PATH": "/bin"}
    traced = lua_cov.traced_environment(env, "@/hook.lua", "/traces")
    assert traced == {
        "PATH": "/bin", "LUA_INIT": "@/hook.lua", "LUA_INIT_5_2": "@/hook.lua", "LUA_INIT_5_3": "@/hook.lua",
        "LUA_INIT_5_4": "@/hook.lua", "LUA_INIT_5_5": "@/hook.lua", "LUA_COV_INIT": "x = 1",
        "LUA_COV_INIT_5_4": "@/init.lua", "LUA_COV_HOOK": "@/hook.lua", "LUA_COV_TRACE_DIR": "/traces"}
    assert lua_cov.traced_environment(traced, "@/hook.lua", "/traces") == traced
    nested = lua_cov.traced_environment(traced, "@/inner.lua", "/inner")
    assert nested["LUA_COV_INIT"] == "x = 1" and nested["LUA_INIT"] == "@/inner.lua"
    assert env["LUA_INIT"] == "x = 1"


def test_lua_traced_env_adds_the_hook_only_when_tracing(monkeypatch):
    build = unwrap(lua_cov.lua_traced_env)()
    monkeypatch.delenv(lua_cov.TRACE_DIR_VARIABLE, raising=False)
    assert build({"A": "1"}) == {"A": "1"}
    assert build()["PATH"] == os.environ["PATH"]
    monkeypatch.setenv(lua_cov.TRACE_DIR_VARIABLE, "/traces")
    monkeypatch.setenv(lua_cov.HOOK_VARIABLE, "@/hook.lua")
    traced = build({"A": "1", "LUA_INIT": "y = 2"})
    assert traced["LUA_INIT_5_4"] == "@/hook.lua" and traced["LUA_COV_INIT"] == "y = 2"
    assert traced["LUA_COV_TRACE_DIR"] == "/traces" and traced["A"] == "1"
    assert build()["PATH"] == os.environ["PATH"]


# --- plugin hooks -------------------------------------------------------

def make_config(tmp_path, source=(), report=False, floor=None, worker=False, exclude=()):
    options = {"--lua-cov-source": list(source), "--lua-cov-report": report, "--lua-cov-fail-under": floor,
               "--lua-cov-exclude": list(exclude)}

    def getoption(name, default=None):
        return options.get(name, default)
    config = SimpleNamespace(rootpath=tmp_path, getoption=getoption)
    if worker:
        config.workerinput = {}
    return config


@pytest.fixture
def clean_environment(monkeypatch):
    for name in lua_cov.ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_addoption_registers_no_branch_option():
    added = []
    group = SimpleNamespace(addoption=lambda *a, **k: added.append(a[0]))
    lua_cov.pytest_addoption(SimpleNamespace(getgroup=lambda name: group))
    assert added == ["--lua-cov-source", "--lua-cov-exclude", "--lua-cov-report", "--lua-cov-fail-under"]


def test_configure_is_inert_when_disabled_or_on_a_worker(tmp_path, clean_environment):
    for config in (make_config(tmp_path), make_config(tmp_path, report=True, worker=True)):
        lua_cov.pytest_configure(config)
        assert config.lua_cov_scratch is None
        lua_cov.pytest_unconfigure(config)
        lua_cov.pytest_sessionfinish(SimpleNamespace(config=config), 0)
        lua_cov.pytest_terminal_summary(None, 0, config)
    assert "LUA_INIT" not in os.environ


def test_configure_installs_the_hook_and_unconfigure_restores(tmp_path, clean_environment, monkeypatch):
    monkeypatch.setenv("LUA_INIT_5_4", "@/mine.lua")
    config = make_config(tmp_path, report=True)
    lua_cov.pytest_configure(config)
    scratch = config.lua_cov_scratch
    hook = os.environ["LUA_INIT"]
    assert hook == os.environ["LUA_INIT_5_5"] == "@" + os.path.join(scratch, "trace-hook.lua")
    with open(hook[1:], encoding="utf-8") as handle:
        assert handle.read() == lua_cov.TRACE_HOOK
    assert os.environ["LUA_COV_INIT_5_4"] == "@/mine.lua"
    assert os.path.isdir(os.environ[lua_cov.TRACE_DIR_VARIABLE])
    lua_cov.pytest_unconfigure(config)
    assert os.environ["LUA_INIT_5_4"] == "@/mine.lua"
    assert not {"LUA_INIT", "LUA_COV_INIT_5_4", lua_cov.TRACE_DIR_VARIABLE} & set(os.environ)
    assert not os.path.exists(scratch)


def test_configure_refuses_a_missing_source_or_parser(tmp_path, clean_environment, monkeypatch):
    with pytest.raises(pytest.UsageError, match="--lua-cov-source .*nope does not exist"):
        lua_cov.pytest_configure(make_config(tmp_path, source=["nope"]))

    def missing(language):
        raise parsers.ParserMissing(f"reading {language} needs tree-sitter-lua")
    monkeypatch.setattr(parsers, "get_parser", missing)
    with pytest.raises(pytest.UsageError, match="reading lua needs tree-sitter-lua"):
        lua_cov.pytest_configure(make_config(tmp_path, report=True))
    assert "LUA_INIT" not in os.environ


def reporter_lines():
    lines = []
    return lines, SimpleNamespace(write_sep=lambda *a, **k: lines.append(a[1]), write_line=lines.append)


def test_session_finish_measures_gates_and_reports(tmp_path, clean_environment):
    write_lua(tmp_path, "s.lua", "x = 1\ny = 2\n")
    config = make_config(tmp_path, source=["s.lua"], floor=100.0)
    lua_cov.pytest_configure(config)
    try:
        trace_dir = os.environ[lua_cov.TRACE_DIR_VARIABLE]
        with open(os.path.join(trace_dir, "1.trace"), "w", encoding="utf-8") as handle:
            handle.write(f"1\t{tmp_path}/s.lua\n")
        session = SimpleNamespace(config=config, exitstatus=0)
        lua_cov.pytest_sessionfinish(session, 0)
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        lines, reporter = reporter_lines()
        lua_cov.pytest_terminal_summary(reporter, 0, config)
        assert lines[0] == "lua coverage"
        assert "s.lua:2  y = 2" in lines[1] and "Floor: 100.0% (NOT MET)" in lines[1]
    finally:
        lua_cov.pytest_unconfigure(config)


def test_session_finish_reports_a_source_it_cannot_measure(tmp_path, clean_environment):
    write_lua(tmp_path, "bad.lua", "x = = 1\n")
    config = make_config(tmp_path, report=True)
    lua_cov.pytest_configure(config)
    try:
        session = SimpleNamespace(config=config, exitstatus=0)
        lua_cov.pytest_sessionfinish(session, 0)
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
        lines, reporter = reporter_lines()
        lua_cov.pytest_terminal_summary(reporter, 0, config)
        assert lines[1].startswith("Could not measure: bad.lua: tree-sitter-lua cannot parse it")
        assert "--lua-cov-exclude" in lines[2]
    finally:
        lua_cov.pytest_unconfigure(config)


# --- end to end, in process -----------------------------------------------

def test_end_to_end_through_lua_runtime(pytester, monkeypatch):
    for name in lua_cov.ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    # loaded by -p alone, as a repo without the entry points would
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    pytester.path.joinpath("scripts").mkdir()
    pytester.path.joinpath("scripts", "greet.lua").write_text(textwrap.dedent("""\
        local name = ...
        if name == "loud" then
            return "HELLO"
        end
        return "hello " .. name
        """))
    pytester.makepyfile(test_greet=textwrap.dedent("""\
        def test_quiet(lua_runtime):
            assert lua_runtime().run_file("scripts/greet.lua", "world") == "hello world"
        """))

    missed = pytester.runpytest_inprocess("-p", "pytest_testrex.lua_cov", "--lua-cov-source", "scripts",
                                          "--lua-cov-fail-under", "100")
    assert missed.ret == pytest.ExitCode.TESTS_FAILED
    missed.stdout.fnmatch_lines(["*= lua coverage =*", "  scripts/greet.lua:3  return \"HELLO\"", "*NOT MET*"])

    pytester.makepyfile(test_loud=textwrap.dedent("""\
        def test_loud(lua_runtime):
            assert lua_runtime().run_file("scripts/greet.lua", "loud") == "HELLO"
        """))
    full = pytester.runpytest_inprocess("-p", "pytest_testrex.lua_cov", "--lua-cov-source", "scripts", "--lua-cov-fail-under", "100")
    assert full.ret == pytest.ExitCode.OK
    full.stdout.fnmatch_lines(["Total: 100.0%", "Floor: 100.0% (met)"])
    assert "LUA_INIT" not in os.environ
