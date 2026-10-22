# TestRex

[![CI](https://github.com/NearlyTRex/TestRex/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/NearlyTRex/TestRex/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/NearlyTRex/TestRex/actions/workflows/ci.yml)
[![Security](https://github.com/NearlyTRex/TestRex/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/NearlyTRex/TestRex/actions/workflows/security.yml)
[![PyPI](https://img.shields.io/pypi/v/pytest-testrex)](https://pypi.org/project/pytest-testrex/)
[![License](https://img.shields.io/github/license/NearlyTRex/TestRex)](LICENSE)

A pytest plugin that holds a test suite to one layout and one standard of test quality

My repos share one way of laying out and writing tests. This plugin carries the rules, so a repo
gets them, and every fix to them, through one dependency bump instead of a copied meta suite.

It does three things:

- **The meta suite.** Around thirty rules that read every test file and fail on tests that cannot
  fail, files in the wrong place, duplicated definitions and helpers, undeclared programs, broken
  override signatures and pylint findings. There are no exemption lists: a test that trips a rule
  is fixed.
- **Required programs.** `requires_binary` (and any marker a repo adds) skips a test while
  collecting, before any of its fixtures start, when a program it needs is missing.
- **Hermetic runs.** Outbound network is closed to tests unless they are marked `allow_network`,
  and the programs a repo seals (`sudo`, `ssh`, a password manager) are refused however a test
  starts them.

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
| Discovery | fewer than `min_test_files` were found, or a suite holds none, so the rules would be guarding nothing |
| Hygiene | a test, test method, helper or constant is defined twice; an import sits below the header; it is longer than `max_lines`; it holds no test |
| Quality | a test checks nothing; every check sits in a branch, loop or try; an assertion is true by construction; it only checks `is not None` or `isinstance`; an `except` swallows silently; a raising callable is built from `(_ for _ in ()).throw()`; a helper is copied between files |
| Layout | a split package holds no test modules, hides tests in a file pytest won't collect, covers no real module or has a single-file twin; a directory mirrors nothing in the repository |
| Programs | a program is checked for at run time instead of by a marker; a marker names a program by anything but a string literal; a test uses a program fixture without declaring its programs; `subprocess` runs a program the file never declares; an integration file declares no program at all |
| Signatures | an override in `signature_packages` renames, drops, reorders or changes the default of a parameter of the method it overrides |
| Pylint | pylint reports anything in the tests, with the shipped rcfile or `pylint_rcfile`; the library breaks a `library_rules` rule |

A check counts as an `assert`, a mock's `assert_*`, `pytest.fail`, a `pytest.raises` or
`pytest.warns` block, or a call to a helper that makes one, including helpers imported by name from
a `*_helpers.py` beside the test or above it.

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

## Settings

Every path is relative to the directory holding `pyproject.toml`. A setting the plugin doesn't know,
or one of the wrong type, stops the run.

| Setting | Default | What it does |
|---|---|---|
| `tests_dir` | `"Tests"` | Where the suites live |
| `suites` | `["unit", "integration"]` | The suites under `tests_dir` |
| `integration_suites` | `["integration"]` | Suites whose files must declare the programs they need |
| `meta_dirs` | `["unit/meta"]` | Directories that mirror nothing on purpose |
| `data_dirs` | `[]` | Directories under `tests_dir` holding data, never read as tests |
| `source_extensions` | `[".py", ".sh"]` | What a split `test_<name>/` package may cover besides a directory |
| `max_lines` | `900` | The longest a test file may be |
| `min_test_files` | `1` | Fewer test files means discovery is looking in the wrong place |
| `requirement_markers` | `["requires_binary"]` | Markers that declare a needed program; any beyond `requires_binary` need a hook |
| `fixture_programs` | `{}` | `{fixture: [programs]}` a test using the fixture must declare, beyond `shell_sandbox` and `shell_traced_env` |
| `pylint_rcfile` | the shipped one | Pylint config for the tests |
| `library_targets` | `[]` | Library paths held to `library_rules` |
| `library_rules` | `["unspecified-encoding"]` | Pylint rules the library's own linter lacks |
| `signature_packages` | `[]` | Packages whose overrides must keep their base method's signature |
| `sealed_programs` | `[]` | Programs a test may never start for real |
| `block_network` | `true` | Refuse in-process outbound connections unless a test is marked `allow_network` |

## Developing

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes --no-deps -r requirements-dev.txt
pip install --no-deps --no-build-isolation -e .
pytest -q
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
