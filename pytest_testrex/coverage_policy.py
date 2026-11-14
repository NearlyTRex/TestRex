# Imports
import configparser
import os
import re
import tomllib

# Local imports
from pytest_testrex.layout import is_non_source_directory

###########################################################
# Coverage policy
#
# A coverage figure only means something if it is earned. Excluding a file
# with omit, or a line with a pragma or an exclusion pattern, raises the
# figure without a test, so a repository declares which few exclusions it
# allows and every other one is a finding.
###########################################################

PRAGMA = re.compile(r"pragma:\s*no\s*cover")

# A real pyproject.toml is a few KB; the limit bounds the settings parsed
MAX_TOML_BYTES = 1024 * 1024

# Files that can hold coverage settings, and the section prefix each uses
INI_PREFIX = {".coveragerc": "", "setup.cfg": "coverage:", "tox.ini": "coverage:"}


# The Python files coverage measures: everything but the tests, hidden
# directories, virtualenvs and build outputs
def measured_files(repo_root, tests_dir):
    found = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(
            name for name in dirs if not is_non_source_directory(name) and os.path.join(root, name) != tests_dir)
        found.extend(os.path.join(root, name) for name in sorted(files) if name.endswith(".py"))
    return found


# "path:line" for every no-cover pragma in the files
def pragma_lines(files, repo_root):
    found = []
    for path in files:
        with open(path, "r", encoding = "utf-8") as handle:
            found.extend("%s:%d" % (os.path.relpath(path, repo_root), number)
                         for number, line in enumerate(handle, 1) if PRAGMA.search(line))
    return found


# The lines of a multi-line ini value, without blanks
def ini_lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


# The values of one coverage option, from every ini-style file that sets it
def ini_values(repo_root, section, option):
    values = []
    for name, prefix in INI_PREFIX.items():
        path = os.path.join(repo_root, name)
        if not os.path.isfile(path):
            continue
        parser = configparser.ConfigParser(interpolation = None)
        parser.read(path, encoding = "utf-8")
        values.extend(ini_lines(parser.get(prefix + section, option, fallback = "")))
    return values


# The values of one coverage option, from pyproject.toml's [tool.coverage] tables
def toml_values(repo_root, section, option):
    path = os.path.join(repo_root, "pyproject.toml")
    if not os.path.isfile(path):
        return []
    with open(path, "rb") as handle:
        raw = handle.read(MAX_TOML_BYTES + 1)
    if len(raw) > MAX_TOML_BYTES:
        raise ValueError("%s is larger than %d bytes" % (path, MAX_TOML_BYTES))
    table = tomllib.loads(raw.decode("utf-8")).get("tool", {}).get("coverage", {}).get(section, {})
    value = table.get(option, [])
    return [value] if isinstance(value, str) else list(value)


# Every omit pattern, and every exclusion pattern, the repository declares
def declared_exclusions(repo_root):
    omit = ini_values(repo_root, "run", "omit") + toml_values(repo_root, "run", "omit")
    exclude = [value for option in ("exclude_lines", "exclude_also")
               for value in ini_values(repo_root, "report", option) + toml_values(repo_root, "report", option)]
    return omit, exclude


# The declared patterns the repository has not allowed
def disallowed(declared, allowed):
    return sorted(set(declared) - set(allowed))
