# Imports
import os
import re
import shutil
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


# Every suite file and the shared .py files atop tests_dir. Files, not directories:
# pylint names a directory's modules after it, so Tests/unit/mypackage would shadow mypackage.
def pylint_targets(tests_dir, suite_files):
    return list(suite_files) + [
        os.path.join(tests_dir, name) for name in sorted(os.listdir(tests_dir)) if name.endswith(".py")]


# Run pylint with the rcfile from cwd, with roots on PYTHONPATH, and return the finished process
def run_pylint(rcfile, cwd, roots, *arguments):
    env = dict(os.environ, PYTHONPATH = os.pathsep.join(roots))
    return subprocess.run(
        [sys.executable, "-m", "pylint", "--rcfile=" + rcfile, "--score=no", *arguments],
        cwd = cwd, env = env, capture_output = True, text = True, check = False)


# Pylint arguments that turn every rule off except these
def only_rules(rules):
    return ["--disable=all", "--enable=" + ",".join(rules)]

###########################################################
# eslint and luacheck
#
# The standalone JavaScript and Lua tests, and the sources a repository names,
# are linted with the configured config, else the repository's own. Without
# one, eslint gets a config shipped beside this module (its recommended rules,
# node and ES2022 globals), and luacheck the union of Lua versions as its
# standard, with busted's globals added for test files. luacheck takes these
# as options, since a config's file globs are relative to the config itself.
###########################################################

# Files eslint reads its config from, flat (eslint 9 on) and legacy
ESLINT_CONFIGS = tuple("eslint.config." + extension for extension in ("js", "mjs", "cjs", "ts", "mts", "cts")) + tuple(
    ".eslintrc" + extension for extension in ("", ".js", ".cjs", ".yaml", ".yml", ".json"))

# The shipped eslint configs, by whether eslint reads flat config
SHIPPED_ESLINT = {True: "eslint.config.mjs", False: "eslintrc.json"}

# The first eslint that reads flat config by default, and the first whose
# legacy config knows ES2022
FLAT_ESLINT = 9
ES2022_ESLINT = 8


# A file shipped beside this module
def shipped(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


# Whether a program is on PATH
def installed(program):
    return shutil.which(program) is not None


# eslint's major version, from what eslint --version prints; 0 when it says none
def eslint_major(cwd):
    result = subprocess.run(["eslint", "--version"], cwd = cwd, capture_output = True, text = True, check = False)
    found = re.search(r"(\d+)\.\d+", result.stdout)
    return int(found.group(1)) if found else 0


# Whether the repository configures eslint itself, in a config file or package.json
def has_eslint_config(repo_root):
    if any(os.path.isfile(os.path.join(repo_root, name)) for name in ESLINT_CONFIGS):
        return True
    package = os.path.join(repo_root, "package.json")
    if not os.path.isfile(package):
        return False
    with open(package, "r", encoding = "utf-8") as handle:
        return '"eslintConfig"' in handle.read()


# The arguments that point eslint at its config: the configured file, nothing
# when the repository has its own, else the shipped one for this eslint
def eslint_config_arguments(repo_root, configured, major):
    flat = major >= FLAT_ESLINT
    if not configured and has_eslint_config(repo_root):
        return []
    arguments = ["--config", configured or shipped(SHIPPED_ESLINT[flat])]
    if flat:
        return arguments
    if not configured and major >= ES2022_ESLINT:
        arguments += ["--env", "es2022", "--parser-options", "ecmaVersion:2022"]
    return ["--no-eslintrc"] + arguments


# Run eslint over files from repo_root, any warning failing, and return the finished process
def run_eslint(repo_root, configured, files):
    arguments = eslint_config_arguments(repo_root, configured, eslint_major(repo_root))
    return subprocess.run(
        ["eslint", "--no-color", "--max-warnings", "0", *arguments, *files],
        cwd = repo_root, capture_output = True, text = True, check = False)


# The luacheck argument lists to run: one over everything under the
# configured or the repository's own config, else the test files with busted's
# globals and the sources without
def luacheck_runs(repo_root, configured, tests, sources):
    if configured:
        return [["--config", configured, *tests, *sources]]
    if os.path.isfile(os.path.join(repo_root, ".luacheckrc")):
        return [[*tests, *sources]]
    runs = [["--no-config", "--std", "max+busted", *tests]] if tests else []
    return runs + ([["--no-config", "--std", "max", *sources]] if sources else [])


# Run luacheck over the test files and sources from repo_root, and return the finished processes
def run_luacheck(repo_root, configured, tests, sources):
    return [
        subprocess.run(["luacheck", "--no-color", "--codes", *arguments], cwd = repo_root, capture_output = True, text = True, check = False)
        for arguments in luacheck_runs(repo_root, configured, tests, sources)]
