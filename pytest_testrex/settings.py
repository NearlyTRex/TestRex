# Imports
import dataclasses
import os
import tomllib

###########################################################
# Settings
#
# A repository opts in with a [tool.testrex] table in its pyproject.toml,
# found by walking up from pytest's rootdir. Without one the plugin does
# nothing, so installing it never changes another project's run. Every path
# is relative to the directory holding that pyproject.toml.
###########################################################

DEFAULT_FIXTURE_PROGRAMS = {
    "shell_sandbox": ["bash", "unshare"],
    "shell_traced_env": ["bash"],
}

DEFAULTS = {
    # Where the suites live, and their names under it
    "tests_dir": "Tests",
    "suites": ["unit", "integration"],
    # Suites whose files need a program outside the process, and say which
    "integration_suites": ["integration"],
    # Directories under tests_dir that mirror nothing on purpose
    "meta_dirs": ["unit/meta"],
    # Directories under tests_dir that hold data, not tests; never read
    "data_dirs": [],
    # What a split test_<name>/ package may cover besides a source directory
    "source_extensions": [".py", ".sh"],
    "max_lines": 900,
    # Fewer test files than this means discovery is looking in the wrong place
    "min_test_files": 1,
    # Markers that declare a program a test needs; requires_binary is built in,
    # and any other needs a pytest_testrex_requirement_checkers hook to enforce it
    "requirement_markers": ["requires_binary"],
    # Fixtures that need programs, and which, beyond the built-in shell ones
    "fixture_programs": {},
    # Pylint over the tests; empty uses the rcfile shipped with the plugin
    "pylint_rcfile": "",
    # Library code held to a few pylint rules its own linter lacks
    "library_targets": [],
    "library_rules": ["unspecified-encoding"],
    # Packages whose overrides must keep their base method's signature
    "signature_packages": [],
    # Programs a test may never start for real
    "sealed_programs": [],
    # Refuse in-process outbound connections unless a test is marked allow_network
    "block_network": True,
}


class SettingsError(Exception):
    pass


@dataclasses.dataclass(frozen = True, eq = False)
class Settings:
    repo_root: str
    tests_dir: str
    suites: tuple
    integration_suites: tuple
    meta_dirs: tuple
    data_dirs: tuple
    source_extensions: tuple
    max_lines: int
    min_test_files: int
    requirement_markers: tuple
    fixture_programs: dict
    pylint_rcfile: str
    library_targets: tuple
    library_rules: tuple
    signature_packages: tuple
    sealed_programs: frozenset
    block_network: bool

    @property
    def suite_dirs(self):
        return tuple(os.path.join(self.tests_dir, suite) for suite in self.suites)

    @property
    def integration_dirs(self):
        return tuple(os.path.join(self.tests_dir, suite) for suite in self.integration_suites)

    @property
    def ignored_dirs(self):
        return tuple(os.path.join(self.tests_dir, path) for path in self.data_dirs)

    @property
    def rcfile(self):
        if self.pylint_rcfile:
            return self.pylint_rcfile
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "pylintrc")


def check_types(table):
    for key, value in table.items():
        if key not in DEFAULTS:
            raise SettingsError("[tool.testrex] has no setting %r; known: %s" % (key, ", ".join(sorted(DEFAULTS))))
        expected = type(DEFAULTS[key])
        if type(value) is not expected:
            raise SettingsError("[tool.testrex] %s must be a %s, not %r" % (key, expected.__name__, value))


# The [tool.testrex] table in pyproject.toml, merged over the defaults, with
# paths made absolute against repo_root
def from_table(table, repo_root):
    check_types(table)
    values = dict(DEFAULTS, **table)
    unknown_suites = sorted(set(values["integration_suites"]) - set(values["suites"]))
    if unknown_suites:
        raise SettingsError("[tool.testrex] integration_suites names suites not in suites: %s" % unknown_suites)
    tests_dir = os.path.join(repo_root, values["tests_dir"])
    markers = ["requires_binary"] + [name for name in values["requirement_markers"] if name != "requires_binary"]
    return Settings(
        repo_root = repo_root,
        tests_dir = tests_dir,
        suites = tuple(values["suites"]),
        integration_suites = tuple(values["integration_suites"]),
        meta_dirs = tuple(os.path.normpath(path) for path in values["meta_dirs"]),
        data_dirs = tuple(os.path.normpath(path) for path in values["data_dirs"]),
        source_extensions = tuple(values["source_extensions"]),
        max_lines = values["max_lines"],
        min_test_files = values["min_test_files"],
        requirement_markers = tuple(markers),
        fixture_programs = {
            name: set(programs) for name, programs in dict(DEFAULT_FIXTURE_PROGRAMS, **values["fixture_programs"]).items()},
        pylint_rcfile = os.path.join(repo_root, values["pylint_rcfile"]) if values["pylint_rcfile"] else "",
        library_targets = tuple(os.path.join(repo_root, path) for path in values["library_targets"]),
        library_rules = tuple(values["library_rules"]),
        signature_packages = tuple(values["signature_packages"]),
        sealed_programs = frozenset(values["sealed_programs"]),
        block_network = values["block_network"])


# The pyproject.toml at or above start that has a [tool.testrex] table, as
# (path, table), or None
def find_table(start):
    directory = os.path.abspath(start)
    while True:
        path = os.path.join(directory, "pyproject.toml")
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                table = tomllib.load(handle).get("tool", {}).get("testrex")
            if table is not None:
                return path, table
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def load(start):
    found = find_table(start)
    if found is None:
        return None
    path, table = found
    return from_table(table, os.path.dirname(path))
