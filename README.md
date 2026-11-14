# TestRex

[![CI](https://github.com/NearlyTRex/TestRex/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/NearlyTRex/TestRex/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/NearlyTRex/TestRex/actions/workflows/ci.yml)
[![Security](https://github.com/NearlyTRex/TestRex/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/NearlyTRex/TestRex/actions/workflows/security.yml)
[![PyPI](https://img.shields.io/pypi/v/pytest-testrex)](https://pypi.org/project/pytest-testrex/)
[![License](https://img.shields.io/github/license/NearlyTRex/TestRex)](LICENSE)

A pytest plugin that holds a test suite to one layout and one standard of test quality

My repos share one way of laying out and writing tests. This plugin carries the rules, so a repo
gets them, and every fix to them, through one dependency bump instead of a copied meta suite.

It does seven things:

- **The meta suite.** Around forty rules that read every test file and fail on tests that cannot
  fail, files in the wrong place, duplicated definitions and helpers, undeclared programs, tests
  that change the process or skip without a reason, broken override signatures, modules without
  tests, coverage raised by exclusions, and pylint and ruff findings. There are no exemption lists:
  a test that trips a rule is fixed.
- **Required programs.** `requires_binary` (and any marker a repo adds) skips a test while
  collecting, before any of its fixtures start, when a program it needs is missing.
- **Hermetic runs.** Outbound network is closed to tests unless they are marked `allow_network`,
  and the programs a repo seals (`sudo`, `ssh`, a password manager) are refused however a test
  starts them.
- **No leaked processes.** A test that leaves a process running, its own child or an orphan
  further down, fails and the process is killed.
- **Shell scripts.** Coverage for the bash scripts tests run, which coverage.py never sees, and a
  disposable machine to run setup scripts in as root without touching the real one.
- **JavaScript and Lua.** Coverage for the JS and Lua the tests run, `*.test.js` and `*_spec.lua`
  files collected as tests, and the quality rules, eslint and luacheck held over them.
- **Library standards.** Documentation and coding-standard rules for the repository's own code,
  each adopted with a baseline count that may only fall, so a codebase moves towards them a fix at
  a time.

## Setting up a repo

Install it with the test dependencies. With a hash-locked `requirements-dev.in`:

```text
pytest-testrex
```

Then opt in with a `[tool.testrex]` table in `pyproject.toml`. Without one the plugin does nothing,
so having it installed never changes another project's run:

```toml
[tool.testrex]
suites = ["unit", "integration"]
```

and run the meta suite by subclassing it in a test module under a meta directory, by default
`Tests/unit/meta/`:

```python
# Tests/unit/meta/test_testrex.py
from pytest_testrex import suite


class TestRex(suite.TestRex):
    """The suite's own rules, from pytest-testrex."""
```

The plugin parametrizes each rule over the files it reads, so a failure names the file:

```text
FAILED Tests/unit/meta/test_testrex.py::TestRex::test_every_test_checks_something[unit/pkg/test_mod.py]
    asserts nothing: ['test_parse (line 12)']
```

## Layout

Each suite mirrors the repository: a test lives at the path of the code it covers.

```text
pkg/strings.py                → Tests/unit/pkg/test_strings.py
pkg/net/fetch.py              → Tests/unit/pkg/net/test_fetch.py
scripts/setup.sh              → Tests/unit/scripts/test_setup.py
.githooks/pre-commit          → Tests/unit/githooks/test_pre_commit.py
pkg/net/fetch.py (real HTTP)  → Tests/integration/pkg/net/test_fetch.py
```

What decides the suite is whether a test needs a program outside the process, not whether it
touches real files. A test that works in `tmp_path` with the code and its Python dependencies alone
is a unit test; one that runs `git`, `docker` or `7zz` goes in `integration/` and declares it.

A test file that outgrows `max_lines` becomes a directory of the same name, `test_<module>/`, holding
`test_<area>.py` files, a `conftest.py` and a `<module>_helpers.py` they share. Because the tree
mirrors the source, two suites can hold files with the same basename, so run pytest with
`--import-mode=importlib`.

## The rules

| Area | A test file fails when |
|---|---|
| Discovery | fewer than `min_test_files` were found, or a suite holds none, so the rules would be guarding nothing; a test file sits outside the suites |
| Hygiene | a test, test method, helper or constant is defined twice; an import sits below the header; it is longer than `max_lines`; it holds no test |
| Practices | a test changes the process directly (`os.environ`, `os.chdir`, `sys.path`, `sys.modules`, `sys.argv`, the standard streams, the umask) instead of through `monkeypatch`; `pytest.raises(Exception)` has no `match`; a `pytest.raises` block holds more than the call that raises; a skip, `skipif` or `xfail` gives no reason; a `# noqa` or `# type: ignore` names no codes, or pylint is switched off for a file or for everything |
| Quality | a test checks nothing; every check sits in a branch, loop or try; an assertion is true by construction; it only checks `is not None` or `isinstance`; an `except` swallows silently; a raising callable is built from `(_ for _ in ()).throw()`; a helper is copied between files |
| Layout | a split package holds no test modules, hides tests in a file pytest won't collect, covers no real module or has a single-file twin; a directory mirrors nothing in the repository |
| Programs | a program is checked for at run time instead of by a marker; a marker names a program by anything but a string literal; a test uses a program fixture without declaring its programs; `subprocess` runs a program the file never declares; an integration file declares no program at all |
| Markers | an integration file has no module-level `pytestmark` with `integration_marker`, or a unit file has one, so `pytest -m "not integration"` would run the wrong tests |
| Coverage | a module under `library_targets` or `require_tests_for` has no `test_<module>.py`, `test_<module>/` or standalone test file at its mirrored path; a no-cover pragma, or a coverage `omit` or exclusion pattern outside `coverage_omit_allowed` and `coverage_exclude_allowed`, raises the figure without a test |
| Signatures | an override in `signature_packages` renames, drops, reorders or changes the default of a parameter of the method it overrides |
| Pylint | pylint reports anything in the tests, with the shipped rcfile or `pylint_rcfile`; the library breaks a `library_rules` rule; pylint reports more in the library than the `pylint-source` baseline allows |
| Ruff | `ruff check` reports anything in the repository, or `ruff format --check` would change a file when `ruff_format` is on |
| JavaScript and Lua | a `*.test.js` or `*_spec.lua` file holds no `test`/`it`, has a test that makes no `assert`/`expect` call (directly or through a function in the file), mirrors no `<name>.js` or `<name>.lua`, or sits outside `integration_suites`; eslint or luacheck reports anything in those files or in `js_sources`/`lua_sources` |

A check counts as an `assert`, a mock's `assert_*`, `pytest.fail`, a `pytest.raises` or
`pytest.warns` block, or a call to a helper that makes one, including helpers imported by name from
a `*_helpers.py` beside the test or above it.

## Pylint and ruff

The tests are held to pylint with the shipped rcfile, which turns off only what pytest idioms trip.
The library is held to pylint too, with a shipped library rcfile that leaves out only the rules
other checks own: documentation (the `documented` rule), line length (the formatter), string
formatting style, and size (`long-functions` and `long-modules`). Its messages count against a
`pylint-source` baseline, like the library standards below, so a large codebase adopts it a fix at a
time. Point `pylint_source_rcfile` at the repository's own pylint config to use that instead.

Ruff runs over the whole repository from its root, the way
[NearlyTRex/Workflows](https://github.com/NearlyTRex/Workflows)' CI runs it: under the repository's
own `[tool.ruff]`, `ruff.toml` or `.ruff.toml`, else with only the defect rules CI selects
(`E4,E7,E9,F`), since ruff's own default set has grown past them. It uses the ruff installed beside
pytest's Python, else the one on `PATH`, and skips when there is none. `ruff_format = true` also
holds the repository to ruff's formatting.

A pylint run whose parallel mode crashes, as it does on some newer Pythons, is repeated in one
process. Pylint runs with a fixed `PYTHONHASHSEED`: which import cycles it reports depends on set
order, so without one the `pylint-source` count would change from run to run.

## Library standards

The rules above read the tests. These read the code under `library_targets`, and each is off until
`[tool.testrex]` turns it on.

| Rule | Turned on by | Fails when |
|---|---|---|
| `documented` | `doc_style` | a public function, class or method has no comment directly above it (`"comment"`), no docstring (`"docstring"`), or neither (`"either"`); docstring style also wants a module docstring |
| `doc-sections` | `doc_style` | a docstring's `Args:` names a parameter the function doesn't take, or `Returns:` documents a value it never returns |
| `doc-length` | `doc_max_lines` | a description runs past that many lines; `Args:` and the other sections don't count |
| `doc-paraphrase` | `doc_style` | a description says no more than the name, as `# Get the settings` over `get_settings` |
| `wrappers` | `wrappers` | the library calls something directly that the repository wraps, such as `open` instead of its file helpers; the wrappers' own files, `wrapper_modules`, may |
| `no-print`, `no-exit` | `standards` | library code prints, or exits instead of raising; `command_paths` may do both |
| `mutable-defaults` | `standards` | a default argument is a list, dict or set every call shares |
| `bare-except` | `standards` | an `except:` names no exception, so it also catches `KeyboardInterrupt` |
| `silent-except` | `standards` | an `except` handler's whole body is `pass`, hiding the failure it catches |
| `import-time-io` | `standards` | importing the module reads the environment, opens a file or runs a program |
| `no-narration` | `standards` | a comment or docstring, in the library or the tests, tells how the code came to be: "now fixed", "was previously", "as discussed", "I added" |
| `commented-out-code` | `standards` | a comment is a statement commented out; an indented example in a comment block is not |
| `blanket-suppression` | `standards` | a `# noqa` or `# type: ignore` names no codes, or pylint is switched off for a file or for every message |
| `long-functions` | `standards` | a function runs past `max_function_lines` (40) or nests past `max_nesting` (3) |
| `long-modules` | `standards` | a module runs past `max_module_lines` (900), the same limit test files have |

A module past the limit becomes a package of the same name. Its class is assembled from mixin
modules, one per area, and re-exported, so callers still `from pkg.sync import Syncer` and the class
behaves as before:

```text
pkg/sync.py               →  pkg/sync/__init__.py    from .local import LocalMixin
                                                     from .remote import RemoteMixin
                                                     class Syncer(LocalMixin, RemoteMixin): ...
                             pkg/sync/local.py       class LocalMixin: ...
                             pkg/sync/remote.py      class RemoteMixin: ...
```

Tests and pytest hooks are described by their names, so the documentation rules leave them alone.
Calls are matched through imports: `from subprocess import run as go; go()` is `subprocess.run`.

```toml
[tool.testrex]
library_targets = ["Shared"]
doc_style = "comment"
doc_max_lines = 3
wrappers = { "open" = "joybox.fileops", "json.dumps" = "joybox.serialization" }
wrapper_modules = ["Shared/joybox/fileops.py", "Shared/joybox/serialization.py"]
command_paths = ["Shared/joybox/cli"]
standards = ["no-print", "no-exit", "mutable-defaults", "bare-except", "no-narration"]

[tool.testrex.baseline]
documented = 819
no-print = 40
```

**Adopting a rule gradually.** A codebase rarely meets a new rule on the day it is turned on, so
each rule counts its findings across the whole library and compares the count with its baseline,
zero when it has none. More findings than the baseline fail, listing them. Fewer fail too, asking
for the baseline to be lowered to the new count, so a fix stays fixed and the count only falls. The
baseline is a number, not a list of excused places: a new finding anywhere is a failure.

## Required programs

```python
pytestmark = pytest.mark.requires_binary("docker")       # whole module

@pytest.mark.requires_binary("gpg", "xorriso|mkisofs")   # "a|b" takes either
def test_sign_image(): ...
```

A repo with its own kind of requirement, such as tools it installs itself, names the marker in
`requirement_markers` and says how to check it from its `conftest.py`:

```python
def pytest_testrex_requirement_checkers(config):
    return {"requires_tool": lambda names: [f"{name} (tool)" for name in names if not installed(name)]}
```

## Leaked processes

Any repo with TestRex installed gets this; it needs no `[tool.testrex]` table. On Linux each
pytest process becomes a child subreaper, so a process whose parent exits is adopted by pytest
instead of escaping to init: a browser behind a launcher script that `quit()` stopped, or a daemon
that double-forked. When a test that started anything ends, whatever it started that is still
running fails the test with its command line, and is killed.

A process gets `process_guard_settle_seconds` (default 5) to finish exiting before it counts. A
session or module fixture's long-running process is not blamed on the tests that use it. Tests
that launch nothing skip the check. `-p no:testrex_process_guard` turns it off.

## Shell scripts

Both plugins load with the package and do nothing until asked.

**Shell coverage** measures the bash scripts the tests run, by statement, or with
`--shell-cov-branch` also by each right-hand side of `&&` and `||`. It reads scripts with
tree-sitter-bash, which the `shell` extra installs (`pip install "pytest-testrex[shell]"`, or add
`tree-sitter` and `tree-sitter-bash` to a hash-locked requirements file):

```bash
pytest --shell-cov-source scripts --shell-cov-source install.sh --shell-cov-fail-under 100
```

| Option | What it does |
|---|---|
| `--shell-cov-source PATH` | A script, or a directory searched for `*.sh` and `*.bash`, relative to the rootdir; repeatable |
| `--shell-cov-exclude GLOB` | Leaves out scripts whose path from the rootdir matches, such as vendored ones; repeatable |
| `--shell-cov-branch` | Also counts the right-hand side of each `&&` and `\|\|` as a statement that must run |
| `--shell-cov-report` | Prints the report without a floor |
| `--shell-cov-fail-under N` | Fails the run below N percent |

Every bash a test starts is traced through `BASH_ENV`, inherited from the environment. A test that
builds its own environment takes it from the `shell_traced_env` fixture. Only bash is traced: `sh`
(dash) never reads `BASH_ENV`.

**The shell sandbox** runs a script as root in a user namespace with no network, with `/etc`,
`/var`, `/home` and the rest replaced by empty directories the test owns. `PATH` holds recording
stubs and an allowlist of harmless tools, so a command nobody planned for fails rather than running
for real:

```python
@pytest.mark.requires_binary("bash", "unshare")
def test_enables_the_service(shell_sandbox):
    shell_sandbox.run("scripts/setup.sh", "install")
    assert shell_sandbox.ran("systemctl", "enable", "myservice")
```

It needs Linux with unprivileged user namespaces. Ubuntu 24.04 restricts them, so CI sets
`kernel.apparmor_restrict_unprivileged_userns=0` first. Where they are unavailable its tests skip,
or fail with `--shell-sandbox-required`. Override the `shell_sandbox_options` fixture to add stubs
(`extra_stubs`), tools (`extra_tools`), accounts and hidden directories.

## JavaScript and Lua

**Coverage** works like shell coverage, one plugin per language, each off until its options are
given. The `js` and `lua` extras install the parsers (`pip install "pytest-testrex[js,lua]"`).

```bash
pytest --js-cov-source web --js-cov-branch --js-cov-fail-under 100 \
       --lua-cov-source scripts --lua-cov-fail-under 100
```

The options mirror the shell ones: `--js-cov-source`, `-exclude`, `-report`, `-branch` and
`-fail-under`, and the same for `--lua-cov-`, which has no `-branch`.

- **JavaScript.** Every node a test starts, and every node it starts in turn, `node --test` workers
  included, writes V8 coverage through an inherited `NODE_V8_COVERAGE`. A statement ran when V8
  counted its start in any process. `--js-cov-branch` also counts the right side of each `&&`, `||`
  and `??` and each arm of `?:`.
- **Lua.** Every `lua` or `luajit` a test starts, Lua 5.1 to 5.5, runs a line hook through an
  inherited `LUA_INIT`, chaining any `LUA_INIT` already set. A statement ran when any traced line falls
  inside it. A line hook can't see which side of `and`/`or` ran, so there is no branch option.

A test that builds its own environment takes it from `js_traced_env` or `lua_traced_env`.

**Lua inside the test process.** `lua_runtime` makes a [lupa](https://github.com/scoder/lupa)
runtime with the same hook, for scripts written for a host such as WirePlumber or a game engine.
Fake the host's API in its globals, then run the script with the arguments it reads through `...`:

```python
def test_pins_game_streams(lua_runtime):
    runner = lua_runtime()                       # lua="lua54" by default; lua51..lua55, luajit21
    runner.globals.Log = runner.lua.eval("{ info = function() end }")
    runner.run_file("scripts/policy.lua", runner.lua.table_from({"allow": "Game.exe"}))
    assert ...
```

**Standalone tests.** Under the suites, files matching `js_test_patterns` run with
`node --test` and files matching `lua_test_patterns` with `busted`, one pytest item per file, from
the repository root with pytest's environment, so the coverage above reaches them. A failure names
the tests the runner's TAP output marks `not ok`. An item skips when its runner is not installed.
These files need a program outside the process, so they belong in an integration suite.

**Lint.** eslint runs over the JS test files and `js_sources`, and luacheck over the Lua test files
and `lua_sources`, each as a meta-suite rule that skips when the linter is not installed:

- **eslint config.** It uses `eslint_config`, else the repository's own, else a shipped
  recommended-rules config for node with `.cjs` as CommonJS.
- **luacheck config.** It uses `luacheck_config`, else the repository's `.luacheckrc`, else
  `--std max`, with busted's globals in test files.

## Settings

Every path is relative to the directory holding `pyproject.toml`. A setting the plugin doesn't know,
or one of the wrong type, stops the run.

| Setting | Default | What it does |
|---|---|---|
| `tests_dir` | `"Tests"` | Where the suites live |
| `suites` | `["unit", "integration"]` | The suites under `tests_dir` |
| `integration_suites` | `["integration"]` | Suites whose files must declare the programs they need |
| `integration_marker` | `"integration"` | The marker every integration file, and no unit file, sets on the whole module; the plugin registers it and puts it on standalone script tests; `""` turns the rule off |
| `meta_dirs` | `["unit/meta"]` | Directories that mirror nothing on purpose |
| `data_dirs` | `[]` | Directories under `tests_dir` holding data, never read as tests |
| `source_extensions` | `[".py", ".sh", ".js", ".mjs", ".cjs", ".lua"]` | What a split `test_<name>/` package may cover besides a directory |
| `max_lines` | `900` | The longest a test file may be |
| `min_test_files` | `1` | Fewer test files means discovery is looking in the wrong place |
| `requirement_markers` | `["requires_binary"]` | Markers that declare a needed program; any beyond `requires_binary` need a hook |
| `fixture_programs` | `{}` | `{fixture: [programs]}` a test using the fixture must declare, beyond `shell_sandbox`, `shell_traced_env`, `js_traced_env` and `lua_traced_env`; `"a\|b"` is met by declaring either |
| `js_test_patterns` | `["*.test.js", "*.test.mjs", "*.test.cjs"]` | JavaScript test files run by `node --test`; `[]` turns them off |
| `lua_test_patterns` | `["*_spec.lua"]` | Lua test files run by `busted`; `[]` turns them off |
| `js_sources`, `lua_sources` | `[]` | Files or directories eslint and luacheck also lint |
| `eslint_config`, `luacheck_config` | `""` | Lint config; empty uses the repository's own, else the shipped default |
| `pylint_rcfile` | the shipped one | Pylint config for the tests |
| `library_targets` | `[]` | Library paths held to `library_rules` |
| `library_rules` | `["unspecified-encoding"]` | Pylint rules the library's own linter lacks |
| `pylint_source` | `true` | Hold `library_targets` to pylint, against the `pylint-source` baseline |
| `pylint_source_rcfile` | the shipped one | Pylint config for the library |
| `ruff`, `ruff_format` | `true`, `false` | Hold the repository to `ruff check`, and to `ruff format --check` |
| `require_tests` | `true` | Every module under `library_targets` and `require_tests_for` needs tests |
| `require_tests_for` | `[]` | Directories or files beyond `library_targets` whose modules need tests |
| `tests_not_required` | `[]` | Files under those that are not modules, such as a shipped config; say why beside each |
| `check_coverage_config` | `true` | Fail on no-cover pragmas and on coverage exclusions not allowed below |
| `coverage_omit_allowed` | `["Tests/*", ".venv/*", "venv/*"]` | Coverage `omit` patterns a repository may declare |
| `coverage_exclude_allowed` | `["if __name__ == .__main__.:"]` | Coverage `exclude_lines` and `exclude_also` patterns a repository may declare |
| `signature_packages` | `[]` | Packages whose overrides must keep their base method's signature |
| `sealed_programs` | `[]` | Programs a test may never start for real |
| `block_network` | `true` | Refuse in-process outbound connections unless a test is marked `allow_network` |
| `doc_style` | `""` | How library code is documented: `"comment"`, `"docstring"` or `"either"` |
| `doc_max_lines` | `0` | The longest a description may run; `0` sets no limit |
| `wrappers` | `{}` | `{call: what to use instead}` for calls the library makes through a wrapper |
| `wrapper_modules` | `[]` | The wrappers' own files, which make those calls |
| `standards` | `[]` | The built-in coding standards to hold the library to |
| `command_paths` | `[]` | Command entry points, which may print and exit |
| `max_function_lines`, `max_nesting` | `40`, `3` | The `long-functions` limits |
| `max_module_lines` | `900` | The `long-modules` limit |
| `baseline` | `{}` | `{rule: findings allowed}`, to adopt a library rule or `pylint-source` before every finding is fixed |

## Developing

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes --no-deps -r requirements-dev.txt
pip install --no-deps --no-build-isolation -e .
pytest -q
```

The sandbox tests need unprivileged user namespaces and skip without them. The JavaScript tests
need node and eslint, and the Lua ones lua (any of 5.1 to 5.4, or luajit), busted and luacheck
(`apt install nodejs eslint lua5.4 luajit lua-busted lua-check`); each skips without its
program. The shell coverage tests need bash, and its cross-check against a real parser needs
`shfmt`, which `shfmt-py` puts next to the venv's Python. To check any script's statements against shfmt:

```bash
python Tests/shfmt_oracle.py path/to/a.sh path/to/b.sh
```

The library is held to its own rules: `Tests/unit/meta/test_testrex.py` runs the suite over these
tests, and `Tests/unit/pytest_testrex/test_suite.py` checks that a clean sample repository passes
every rule and a broken one fails every rule. CI runs through
[NearlyTRex/Workflows](https://github.com/NearlyTRex/Workflows) at 100% line and branch coverage.

## Releasing

Run **Prepare Release** from the Actions tab with `patch`, `minor`, `major` or an exact version. It
opens a pull request bumping `pyproject.toml`; merging it tags the version, publishes a GitHub
Release with the sdist and wheel, and publishes them to PyPI through trusted publishing from the
`pypi` environment.
