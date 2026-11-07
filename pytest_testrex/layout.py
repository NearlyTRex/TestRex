# Imports
import fnmatch
import os

# Local imports
from pytest_testrex.discovery import defines_tests, is_ignored, parsed

###########################################################
# Layout
#
# Each suite mirrors the repository: a test lives at the path of the code it
# covers. A test module that outgrows the size limit becomes a directory of
# the same name, test_<module>/, holding test_<area>.py files, a conftest.py
# and a <module>_helpers.py they share. The hazards are quiet: a file that
# holds tests but is not named test_*.py is never collected, and a directory
# that mirrors nothing puts tests where nobody looks for them.
###########################################################

# Files in a split package that are not test modules by design
SUPPORT_FILES = {"conftest.py"}


# (root, subdirectories) under each suite, skipping caches, hidden and ignored directories
def walk_directories(suite_dirs, ignored_dirs = ()):
    for suite_dir in suite_dirs:
        for root, dirs, _ in os.walk(suite_dir):
            dirs[:] = sorted(
                name for name in dirs if name != "__pycache__" and not name.startswith(".")
                and not is_ignored(os.path.join(root, name), ignored_dirs))
            yield root, dirs


# Every test_<module> directory under the suites
def discover_split_packages(suite_dirs, ignored_dirs = ()):
    return sorted(os.path.join(root, name) for root, dirs in walk_directories(suite_dirs, ignored_dirs)
                  for name in dirs if name.startswith("test_"))


# Whether a directory has a .py file, or a file matching one of the script
# test patterns, anywhere under it
def holds_tests(directory, script_patterns = ()):
    return any(name.endswith(".py") or any(fnmatch.fnmatch(name, pattern) for pattern in script_patterns)
               for _, _, files in os.walk(directory) for name in files)


# Every directory that must mirror the repository: neither a split package nor
# inside one, and holding tests (a directory of fixture data mirrors nothing)
def discover_mirror_directories(suite_dirs, ignored_dirs = (), script_patterns = ()):
    found = []
    for root, dirs in walk_directories(suite_dirs, ignored_dirs):
        dirs[:] = [name for name in dirs if not name.startswith("test_")]
        found.extend(os.path.join(root, name) for name in dirs if holds_tests(os.path.join(root, name), script_patterns))
    return sorted(found)


# The suite directory a path is inside
def suite_of(path, suite_dirs):
    return next(suite for suite in suite_dirs if path.startswith(suite + os.sep))


# The names of the .py files directly in a directory, sorted
def python_files(directory):
    return sorted(name for name in os.listdir(directory)
                  if name.endswith(".py") and os.path.isfile(os.path.join(directory, name)))


# Whether a file name is one pytest collects tests from
def is_test_module_name(name):
    return name.startswith("test_") and name.endswith(".py")


# Files that define tests but are not named test_*.py, so pytest skips them
def uncollected_test_files(directory):
    return [name for name in python_files(directory)
            if name not in SUPPORT_FILES and not is_test_module_name(name)
            and defines_tests(parsed(os.path.join(directory, name)))]


# Where the code a split package covers would live: <repo>/<path>/<name> with
# one of the source extensions, or a package directory
def source_candidates(package, suite_dir, repo_root, extensions):
    relative_parts = os.path.relpath(package, suite_dir).split(os.sep)
    base = os.path.join(repo_root, *relative_parts[:-1], relative_parts[-1][len("test_"):])
    return [base + extension for extension in extensions] + [base]


# The name a standalone test file is a test of: the part a pattern's single *
# matched, as greet for greet.test.js under *.test.js
def script_stems(name, patterns):
    stems = []
    for pattern in patterns:
        if pattern.count("*") == 1:
            prefix, suffix = pattern.split("*")
            if fnmatch.fnmatch(name, pattern) and len(name) > len(prefix) + len(suffix):
                stems.append(name[len(prefix):len(name) - len(suffix)])
    return stems


# Where the code a standalone test file covers would live: the same path in
# the repository, named by its stem, with one of the language's extensions or
# as a directory
def script_source_candidates(path, suite_dir, repo_root, patterns, extensions):
    directory = os.path.join(repo_root, os.path.relpath(os.path.dirname(path), suite_dir))
    stems = script_stems(os.path.basename(path), patterns)
    return [os.path.normpath(os.path.join(directory, stem + extension)) for stem in stems for extension in extensions] + [
        os.path.normpath(os.path.join(directory, stem)) for stem in stems]


# The repository directories a test directory may mirror; a hidden one, such
# as .githooks, is mirrored without its dot
def mirror_targets(directory, suite_dir, repo_root):
    relative_path = os.path.relpath(directory, suite_dir)
    return [os.path.join(repo_root, relative_path), os.path.join(repo_root, "." + relative_path)]


# The test_<name>.py beside a test_<name>/ package, when both exist
def single_file_twin(package):
    twin = package + ".py"
    return twin if os.path.exists(twin) else None


# Whether directory sits at or under one of the meta directories, relative to tests_dir
def is_meta(directory, tests_dir, meta_dirs):
    relative_path = os.path.relpath(directory, tests_dir)
    return any(relative_path == meta or relative_path.startswith(meta + os.sep) for meta in meta_dirs)
