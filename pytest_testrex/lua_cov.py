"""Lua statement coverage for pytest suites that run Lua.

coverage.py never sees Lua. With this plugin loaded and enabled, every lua or
luajit a test starts runs a hook through LUA_INIT (and LUA_INIT_5_2 to _5_5,
which newer versions read first) that records each line it runs in a file in
a trace directory; a LUA_INIT the environment already had runs after it. The
`lua_runtime` fixture puts the same hook in a lupa runtime, for Lua run inside
the test process. When the session ends the traces are measured against the
sources named by --lua-cov-source.

The unit is a statement, read from each source's syntax tree, built by
tree-sitter-lua: a statement counts as run when any traced line falls inside
it, and a statement nested in another (a function body, an if arm) is one of
its own. The lua extra installs the parser and lupa: pip install "pytest-testrex[lua]".

Enable with at least one of:
    --lua-cov-source PATH   source or directory (searched for *.lua); repeatable;
                            relative to pytest's rootdir
    --lua-cov-report        print the report (sources default to rootdir)
    --lua-cov-fail-under N  fail the run below N percent (implies the report)
and narrow it with --lua-cov-exclude GLOB. There is no branch option: a line
hook can't see which side of an `and` or `or` ran.
"""

import importlib
import os
import shutil
import tempfile

import pytest

from pytest_testrex import parsers, statement_coverage

PREFIX = "lua-cov"
SOURCE_EXTENSIONS = (".lua",)

# The hook and the tests share these; the hook needs only the trace directory
TRACE_DIR_VARIABLE = "LUA_COV_TRACE_DIR"
# The LUA_INIT value the hook was installed as, to tell it from one to chain
HOOK_VARIABLE = "LUA_COV_HOOK"
# What lua reads at start: 5.1 and LuaJIT LUA_INIT, later versions their own first
INIT_VARIABLES = ("LUA_INIT", "LUA_INIT_5_2", "LUA_INIT_5_3", "LUA_INIT_5_4", "LUA_INIT_5_5")

# Run through LUA_INIT, or with (trace directory, true) inside a lupa runtime.
# Records each line first run in a chunk loaded from a file ("@" sources),
# coroutines included, to its own fully buffered trace file, which the C
# exit() behind both os.exit and a normal end flushes. A line is
# "<line>\t<source>"; before the first relative source comes "cwd\t<dir>", the
# directory it is relative to. Run through LUA_INIT it then runs the LUA_INIT
# it replaced, from LUA_COV_INIT_<version> or LUA_COV_INIT. Returns a function
# that flushes and stops it. Written for Lua 5.1 to 5.5 and LuaJIT.
TRACE_HOOK = r"""local trace_dir, embedded = ...
trace_dir = trace_dir or os.getenv("LUA_COV_TRACE_DIR")
local stop
if trace_dir and trace_dir ~= "" then
    local getinfo, sethook = debug.getinfo, debug.sethook
    local own = getinfo(1, "S").source
    local seen, handle, cwd_written, stopped = {}, nil, false, false

    local function open_trace()
        local base = string.format("%s/%d-%d-%s", trace_dir, os.time(), math.floor(os.clock() * 1000000),
            (tostring({}):gsub("%W", "")))
        local name, count = base .. ".trace", 0
        local existing = io.open(name, "r")
        while existing do
            existing:close()
            count = count + 1
            name = base .. "-" .. count .. ".trace"
            existing = io.open(name, "r")
        end
        handle = io.open(name, "w")
        if handle then
            handle:setvbuf("full")
        end
        return handle
    end

    local function start_dir()
        local ok, pipe = pcall(io.popen, "pwd")
        local dir = ok and pipe and pipe:read("*l")
        if ok and pipe then
            pipe:close()
        end
        return dir or os.getenv("PWD") or "."
    end

    local function record(_, line)
        local source = getinfo(2, "S").source
        if stopped or source == own or source:sub(1, 1) ~= "@" then
            return
        end
        local lines = seen[source]
        if not lines then
            lines = {}
            seen[source] = lines
        end
        if lines[line] then
            return
        end
        lines[line] = true
        if not handle and not open_trace() then
            stopped = true
            return
        end
        local path = source:sub(2)
        if not cwd_written and path:sub(1, 1) ~= "/" then
            cwd_written = true
            handle:write("cwd\t", start_dir(), "\n")
        end
        handle:write(line, "\t", path, "\n")
    end

    local create, wrap = coroutine.create, coroutine.wrap
    coroutine.create = function(f)
        local co = create(f)
        sethook(co, record, "l")
        return co
    end
    coroutine.wrap = function(f)
        if type(f) ~= "function" then
            return wrap(f)
        end
        return wrap(function(...)
            sethook(record, "l")
            return f(...)
        end)
    end
    sethook(record, "l")

    stop = function()
        stopped = true
        sethook()
        if handle then
            handle:close()
            handle = nil
        end
    end
end
if not embedded then
    local major, minor = _VERSION:match("(%d+)%.(%d+)")
    local previous = os.getenv("LUA_COV_INIT")
    if major and (major ~= "5" or minor ~= "1") then
        previous = os.getenv("LUA_COV_INIT_" .. major .. "_" .. minor) or previous
    end
    if previous then
        local chunk, message
        if previous:sub(1, 1) == "@" then
            chunk, message = loadfile(previous:sub(2))
        else
            chunk, message = (loadstring or load)(previous, "=LUA_INIT")
        end
        if not chunk then
            error(message, 0)
        end
        chunk()
    end
end
return stop
"""

# Statements a line hook sees run. A bare `local x` is not one: it can compile
# to nothing, or into the previous line's instruction. Labels compile to
# nothing, and a do ... end is only the statements inside it.
STATEMENTS = {
    "assignment_statement", "variable_declaration", "function_call", "function_declaration",
    "if_statement", "while_statement", "repeat_statement", "for_statement",
    "return_statement", "break_statement", "goto_statement",
}

# Where a function_call is a statement rather than part of an expression
BLOCKS = {"chunk", "block"}


class LuaParseError(statement_coverage.SourceError):
    """A Lua source that can't be measured: unreadable, too big or not parsable."""


###########################################################
# Statements
###########################################################


def is_statement(node):
    """Whether a node is a statement the hook can see run."""
    kind = node.type
    if kind not in STATEMENTS:
        return False
    if kind == "function_call":
        return node.parent.type in BLOCKS
    if kind == "assignment_statement":
        return node.parent.type != "variable_declaration"
    if kind == "variable_declaration":
        return any(child.type == "assignment_statement" for child in node.children)
    return True


def find_statements(source):
    """Distinct (first, last) lines of each statement, nested ones included, in order."""
    found = set()
    pending = [parsers.parse("lua", source, LuaParseError)]
    while pending:
        node = pending.pop()
        if is_statement(node):
            found.add((node.start_point[0] + 1, node.end_point[0] + 1))
        pending.extend(child for child in node.children if child.is_named and child.type != "comment")
    return sorted(found)


###########################################################
# Traces and measuring
###########################################################


def parse_trace(lines):
    """The lines a trace (text, or an iterable of its lines) says were run, per source (real paths)."""
    if isinstance(lines, str):
        lines = lines.splitlines()
    hits = {}
    cwd = ""
    for text in lines:
        kind, _, rest = text.rstrip("\n").partition("\t")
        if kind == "cwd":
            cwd = rest
        elif kind.isdigit() and rest:
            path = os.path.realpath(os.path.join(cwd, rest))
            hits.setdefault(path, set()).add(int(kind))
    return hits


def read_traces(trace_dir):
    """Merged hits of every trace file in a directory."""
    merged = {}
    for name in sorted(os.listdir(trace_dir)):
        with open(os.path.join(trace_dir, name), encoding="utf-8", errors="replace") as handle:
            hits = parse_trace(handle)
        for path, lines in hits.items():
            merged.setdefault(path, set()).update(lines)
    return merged


def is_statement_run(statement, lines_run):
    """Whether any traced line falls inside a statement's (first, last) lines."""
    first, last = statement
    return any(first <= line <= last for line in lines_run)


def measure_script(source, lines_run):
    """Statements run and missed in one source, given the lines traced in it."""
    lines = source.split("\n")
    statements = find_statements(source)
    missed = [statement for statement in statements if not is_statement_run(statement, lines_run)]
    return {"statements": len(statements), "covered": len(statements) - len(missed), "missed": missed,
            "missed_source": [statement_coverage.describe_statement(lines, statement) for statement in missed]}


def measure(root, sources, trace_dir, exclude=()):
    """Measure every source under sources, bar those matching an exclude glob, against the
    traces; keys are paths relative to root."""
    hits = read_traces(trace_dir)
    results = {}
    for path in statement_coverage.find_sources(sources, SOURCE_EXTENSIONS):
        name = os.path.relpath(path, root)
        if statement_coverage.is_excluded(name, exclude):
            continue
        try:
            source = statement_coverage.read_source(path, LuaParseError)
            results[name] = measure_script(source, hits.get(os.path.realpath(path), set()))
        except LuaParseError as error:
            raise LuaParseError(f"{name}: {error}") from error
    return results


###########################################################
# Environment
###########################################################


def chained_variable(name):
    """Where the hook finds the value of an init variable it replaced: LUA_INIT_5_4 -> LUA_COV_INIT_5_4."""
    return "LUA_COV_" + name.removeprefix("LUA_")


def traced_environment(env, hook, trace_dir):
    """A copy of env whose lua runs hook (a LUA_INIT value) first and then the LUA_INIT env had.

    A value that is already a hook keeps the one it chained, so tracing an environment twice changes nothing."""
    traced = dict(env)
    for name in INIT_VARIABLES:
        previous = traced.get(name)
        if previous is not None and previous == traced.get(HOOK_VARIABLE):
            previous = traced.get(chained_variable(name))
        if previous is None:
            traced.pop(chained_variable(name), None)
        else:
            traced[chained_variable(name)] = previous
        traced[name] = hook
    traced[HOOK_VARIABLE] = hook
    traced[TRACE_DIR_VARIABLE] = trace_dir
    return traced


# Every variable traced_environment may set or remove
ENVIRONMENT_VARIABLES = INIT_VARIABLES + tuple(map(chained_variable, INIT_VARIABLES)) + (
    HOOK_VARIABLE, TRACE_DIR_VARIABLE)


def apply_environment(values):
    """Set os.environ's ENVIRONMENT_VARIABLES to values, removing those values lacks or holds as None."""
    for name in ENVIRONMENT_VARIABLES:
        if values.get(name) is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = values[name]


###########################################################
# Lua in the test process
###########################################################


LUPA_HINT = ("lua_runtime needs lupa; install it with: pip install \"pytest-testrex[lua]\", "
             "or add lupa to the hash-locked test requirements")

# Loads a file under its own name, so its chunk name is "@<path>"
LOAD_FILE = """function(path)
    local chunk, message = loadfile(path)
    if not chunk then
        error(message, 0)
    end
    return chunk
end"""


class LuaRunner:
    """A lupa LuaRuntime, traced for coverage when trace_dir is set: lua is the
    runtime, globals its global table (install fakes there before running),
    run_file(path, *args) runs a file with args as its `...`."""

    def __init__(self, module, trace_dir=None, **options):
        self.lua = module.LuaRuntime(**options)
        self.globals = self.lua.globals()
        self.stop_trace = self.lua.execute(TRACE_HOOK, trace_dir, True) if trace_dir else None
        self.load_file = self.lua.eval(LOAD_FILE)

    def run_file(self, path, *args):
        """Run a Lua file, loaded by its real path, with args as `...`; returns what it returns."""
        return self.load_file(os.path.realpath(path))(*args)

    def close(self):
        """Flush and stop the trace; the runtime runs on untraced."""
        if self.stop_trace is not None:
            self.stop_trace()
            self.stop_trace = None


@pytest.fixture
def lua_runtime():
    """Make LuaRunners, lupa runtimes traced for coverage when it is on: lua_runtime(lua="lua54", **options).

    lua names the lupa module (lua51 to lua55, luajit21); options go to its LuaRuntime."""
    made = []

    def make(lua="lua54", **options):
        try:
            module = importlib.import_module("lupa." + lua)
        except ImportError as error:
            pytest.fail(f"{LUPA_HINT} ({error})", pytrace=False)
        runner = LuaRunner(module, os.environ.get(TRACE_DIR_VARIABLE), **options)
        made.append(runner)
        return runner
    yield make
    for runner in made:
        runner.close()


@pytest.fixture
def lua_traced_env():
    """Build a lua environment traced for coverage, from env or a copy of os.environ.

    Without Lua coverage enabled it returns the environment unchanged."""
    def build(env=None):
        source = os.environ if env is None else env
        if os.environ.get(TRACE_DIR_VARIABLE) and os.environ.get(HOOK_VARIABLE):
            return traced_environment(source, os.environ[HOOK_VARIABLE], os.environ[TRACE_DIR_VARIABLE])
        return dict(source)
    return build


###########################################################
# Plugin
###########################################################


def pytest_addoption(parser):
    statement_coverage.add_options(
        parser, PREFIX, "Lua coverage",
        "Lua source or directory of *.lua to measure, relative to rootdir (repeatable)")


def pytest_configure(config):
    config.lua_cov_scratch = None
    if not statement_coverage.is_enabled(config, PREFIX) or statement_coverage.is_worker(config):
        return
    statement_coverage.get_sources(config, PREFIX)
    try:
        parsers.get_parser("lua")
    except parsers.ParserMissing as error:
        raise pytest.UsageError(str(error)) from error
    scratch = tempfile.mkdtemp(prefix="lua-cov-")
    trace_dir = os.path.join(scratch, "traces")
    os.makedirs(trace_dir)
    hook_file = os.path.join(scratch, "trace-hook.lua")
    with open(hook_file, "w", encoding="utf-8") as hook:
        hook.write(TRACE_HOOK)
    config.lua_cov_scratch = scratch
    config.lua_cov_trace_dir = trace_dir
    config.lua_cov_saved_env = {name: os.environ.get(name) for name in ENVIRONMENT_VARIABLES}
    apply_environment(traced_environment(os.environ, "@" + hook_file, trace_dir))


def pytest_unconfigure(config):
    scratch = getattr(config, "lua_cov_scratch", None)
    if not scratch:
        return
    apply_environment(config.lua_cov_saved_env)
    shutil.rmtree(scratch, ignore_errors=True)


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if not getattr(config, "lua_cov_scratch", None):
        return
    statement_coverage.finish(session, PREFIX, lambda root, sources, _branch, exclude: measure(
        root, sources, config.lua_cov_trace_dir, exclude))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    statement_coverage.summarize(terminalreporter, config, PREFIX, "Lua coverage", "Script")
