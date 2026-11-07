# Imports
import os
import re
import subprocess

# Third-party imports
import pytest

# Local imports
from pytest_testrex import plugin
from pytest_testrex.discovery import SCRIPT_LANGUAGES, is_ignored, script_language

###########################################################
# Standalone JavaScript and Lua tests
#
# Loaded by pytest from the pytest11 entry point, and inert without a
# [tool.testrex] table. Each file under the suites that matches
# js_test_patterns or lua_test_patterns is one pytest item, run from the
# repository root by node --test or busted with the environment pytest has,
# so coverage set up through it reaches them. It passes when the runner exits
# 0, and fails naming the tests the runner's TAP output marks not ok.
###########################################################

# A TAP result line for a failed test, and a directive that excuses one
NOT_OK = re.compile(r"^\s*not ok \d+(?:\s+-)?\s*(.*)$")
DIRECTIVE = re.compile(r"\s+#\s*(\w+).*$")
EXCUSED = {"todo", "skip"}


# The names of the tests TAP output marks not ok, leaving out TODO and SKIP ones
def failing_tests(output):
    names = []
    for line in output.splitlines():
        found = NOT_OK.match(line)
        if found is None:
            continue
        directive = DIRECTIVE.search(found.group(1))
        if directive is None or directive.group(1).lower() not in EXCUSED:
            names.append(DIRECTIVE.sub("", found.group(1)))
    return names


# A test file whose runner exited with failures
class ScriptFailure(Exception):
    pass


# Run a test file with its language's runner from cwd, and return the finished process
def run_script(runner, path, cwd):
    return subprocess.run([*runner, path], cwd = cwd, capture_output = True, text = True, check = False)


# The language of a file pytest offers, when it is a standalone test file under a suite
def language_of(path, settings):
    inside = any(path.startswith(suite + os.sep) for suite in settings.suite_dirs)
    if not inside or is_ignored(os.path.dirname(path), settings.ignored_dirs):
        return None
    return script_language(os.path.basename(path), settings.script_test_patterns)


def pytest_collect_file(file_path, parent):
    settings = plugin.get_settings(parent.config)
    if settings is None:
        return None
    language = language_of(str(file_path), settings)
    if language is None:
        return None
    return ScriptFile.from_parent(parent, path = file_path, language = language)


# A standalone test file, collected as the one item that runs it
class ScriptFile(pytest.File):
    def __init__(self, *, language, **kwargs):
        super().__init__(**kwargs)
        self.language = language

    # The one item, named after the runner
    def collect(self):
        yield ScriptTest.from_parent(self, name = SCRIPT_LANGUAGES[self.language].runner[0], language = self.language)


# A run of one standalone test file, which needs its runner on PATH
class ScriptTest(pytest.Item):
    def __init__(self, *, language, **kwargs):
        super().__init__(**kwargs)
        self.runner = SCRIPT_LANGUAGES[language].runner
        self.add_marker(pytest.mark.requires_binary(self.runner[0]))

    # Run the file, failing with the tests the runner reports failed
    def runtest(self):
        result = run_script(self.runner, str(self.path), plugin.get_settings(self.config).repo_root)
        if result.returncode != 0:
            failed = failing_tests(result.stdout)
            heading = "failed: " + ", ".join(failed) if failed else "%s exited with %d" % (self.runner[0], result.returncode)
            raise ScriptFailure(heading + "\n\n" + result.stdout + result.stderr)

    # The failed tests and the runner's output, without a Python traceback
    def repr_failure(self, excinfo, style = None):
        if isinstance(excinfo.value, ScriptFailure):
            return str(excinfo.value)
        return super().repr_failure(excinfo, style)

    # The file, and the command that runs it
    def reportinfo(self):
        return self.path, 0, "%s %s" % (" ".join(self.runner), os.path.relpath(self.path, self.config.rootpath))
