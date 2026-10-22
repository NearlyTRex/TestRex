# Imports
import os
import subprocess
import sys

###########################################################
# Pylint
#
# Pylint runs over every test file with the rcfile, and any message fails.
# The shipped rcfile only turns off rules that are pytest idioms rather than
# defects; everything else, such as unused variables, undefined names, calls
# that do not match a signature and files opened without an encoding, is
# enforced. Library code gets only the few rules its own linter lacks.
###########################################################

# Tests import the helpers beside them by name, through each conftest's
# sys.path entry, which pylint has to be told about
def import_roots(tests_dir, all_files):
    roots = {tests_dir}
    roots.update(os.path.dirname(path) for path in all_files if os.path.basename(path) == "conftest.py")
    return sorted(roots)


# Every file in the suites, and the .py files at the top of tests_dir that
# they share. Files, not directories: given a directory, pylint names its
# modules after it, and a test directory mirroring a package, such as
# Tests/unit/mypackage, would then shadow the package itself.
def pylint_targets(tests_dir, suite_files):
    return list(suite_files) + [
        os.path.join(tests_dir, name) for name in sorted(os.listdir(tests_dir)) if name.endswith(".py")]


def run_pylint(rcfile, cwd, roots, *arguments):
    env = dict(os.environ, PYTHONPATH = os.pathsep.join(roots))
    return subprocess.run(
        [sys.executable, "-m", "pylint", "--rcfile=" + rcfile, "--score=no", *arguments],
        cwd = cwd, env = env, capture_output = True, text = True, check = False)


def only_rules(rules):
    return ["--disable=all", "--enable=" + ",".join(rules)]
