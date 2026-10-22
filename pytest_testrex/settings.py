# Imports
import dataclasses
import os
import tomllib

# Local imports
from pytest_testrex.documentation import DOC_STYLES
from pytest_testrex.standards import STANDARDS

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
    # How library_targets document public code: "comment", "docstring" or "either"
    "doc_style": "",
    # Most lines a definition's description may run to; 0 sets no limit
    "doc_max_lines": 0,
    # {call: what to use instead} for calls the library makes through a wrapper,
    # and the wrappers' own files, which make the calls
    "wrappers": {},
    "wrapper_modules": [],
    # Built-in coding standards library_targets are held to
    "standards": [],
    # Command entry points, which may print and exit
    "command_paths": [],
    # The long-functions standard's limits
    "max_function_lines": 40,
    "max_nesting": 3,
    # {library rule: findings allowed}, to adopt a rule before every finding is
    # fixed; a count that drops must be lowered, so progress is never lost
    "baseline": {},
}

# The rules over library code, by the names baseline counts them under
LIBRARY_RULES = ("documented", "doc-sections", "doc-length", "doc-paraphrase", "wrappers") + STANDARDS


# A [tool.testrex] table that names or types a setting wrongly
class SettingsError(Exception):
    pass


# The [tool.testrex] settings, with every path absolute
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
    doc_style: str
    doc_max_lines: int
    wrappers: dict
    wrapper_modules: tuple
    standards: tuple
    command_paths: tuple
    max_function_lines: int
    max_nesting: int
    baseline: dict

    # The suites, as directories
    @property
    def suite_dirs(self):
        return tuple(os.path.join(self.tests_dir, suite) for suite in self.suites)

    # The integration suites, as directories
    @property
    def integration_dirs(self):
        return tuple(os.path.join(self.tests_dir, suite) for suite in self.integration_suites)

    # The data directories, which no rule reads
    @property
    def ignored_dirs(self):
        return tuple(os.path.join(self.tests_dir, path) for path in self.data_dirs)

    # The pylint rcfile the tests are held to: the repository's own, else the shipped one
    @property
    def rcfile(self):
        if self.pylint_rcfile:
            return self.pylint_rcfile
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "pylintrc")


# Refuse settings the plugin doesn't know, and values of the wrong type
def check_types(table):
    for key, value in table.items():
        if key not in DEFAULTS:
            raise SettingsError("[tool.testrex] has no setting %r; known: %s" % (key, ", ".join(sorted(DEFAULTS))))
        expected = type(DEFAULTS[key])
        if type(value) is not expected:
            raise SettingsError("[tool.testrex] %s must be a %s, not %r" % (key, expected.__name__, value))


# The library rule settings name only rules, styles and counts that exist
def check_library_settings(values):
    if values["doc_style"] not in ("",) + DOC_STYLES:
        raise SettingsError("[tool.testrex] doc_style must be one of %s, not %r" % (list(DOC_STYLES), values["doc_style"]))
    unknown = sorted(set(values["standards"]) - set(STANDARDS))
    if unknown:
        raise SettingsError("[tool.testrex] standards has no %s; known: %s" % (unknown, ", ".join(STANDARDS)))
    unknown = sorted(set(values["baseline"]) - set(LIBRARY_RULES))
    if unknown:
        raise SettingsError("[tool.testrex] baseline has no rule %s; known: %s" % (unknown, ", ".join(LIBRARY_RULES)))
    if values["max_function_lines"] < 1 or values["max_nesting"] < 1:
        raise SettingsError("[tool.testrex] max_function_lines and max_nesting must be at least 1")
    if values["doc_max_lines"] < 0:
        raise SettingsError("[tool.testrex] doc_max_lines must be 0 (no limit) or more, not %d" % values["doc_max_lines"])
    counts = [rule for rule, count in values["baseline"].items() if type(count) is not int or count < 0]
    if counts:
        raise SettingsError("[tool.testrex] baseline counts must be whole numbers of findings: %s" % sorted(counts))


# The [tool.testrex] table in pyproject.toml, merged over the defaults, with
# paths made absolute against repo_root
def from_table(table, repo_root):
    check_types(table)
    values = dict(DEFAULTS, **table)
    unknown_suites = sorted(set(values["integration_suites"]) - set(values["suites"]))
    if unknown_suites:
        raise SettingsError("[tool.testrex] integration_suites names suites not in suites: %s" % unknown_suites)
    check_library_settings(values)
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
        block_network = values["block_network"],
        doc_style = values["doc_style"],
        doc_max_lines = values["doc_max_lines"],
        wrappers = dict(values["wrappers"]),
        wrapper_modules = tuple(os.path.join(repo_root, path) for path in values["wrapper_modules"]),
        standards = tuple(values["standards"]),
        command_paths = tuple(os.path.join(repo_root, path) for path in values["command_paths"]),
        max_function_lines = values["max_function_lines"],
        max_nesting = values["max_nesting"],
        baseline = dict(values["baseline"]))


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


# The settings for the repository at or above start, or None when it has no [tool.testrex] table
def load(start):
    found = find_table(start)
    if found is None:
        return None
    path, table = found
    return from_table(table, os.path.dirname(path))
