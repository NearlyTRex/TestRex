"""JavaScript statement coverage for pytest suites that run node.

With this plugin loaded and enabled, NODE_V8_COVERAGE names a scratch
directory for the whole session, so every node a test starts, and every node
those start (`node --test` workers included), writes V8's block coverage there
when it exits. When the session ends that coverage is measured against the
scripts named by --js-cov-source.

A statement counts as run when V8 counted the code at its start more than
zero times in any process. Statements are read from each script's syntax
tree, built by tree-sitter-javascript, which the js extra installs:
pip install "pytest-testrex[js]".

Enable with at least one of:
    --js-cov-source PATH   script or directory (searched for *.js, *.mjs,
                           *.cjs); repeatable; relative to pytest's rootdir
    --js-cov-report        print the report (sources default to rootdir)
    --js-cov-fail-under N  fail the run below N percent (implies the report)

Narrow or change what is measured with:
    --js-cov-exclude GLOB  leave out scripts whose path (relative to rootdir)
                           matches, e.g. vendored ones; repeatable
    --js-cov-branch        also count the right side of each && || ?? and
                           each arm of a ?: conditional

Tests just run node and are measured through the inherited environment. A
test that builds its own environment takes it from the `js_traced_env` fixture.
"""

import bisect
import functools
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request

import pytest

from pytest_testrex import parsers, statement_coverage
from pytest_testrex.statement_coverage import describe_statement, is_excluded, is_worker

PREFIX = "js-cov"
TITLE = "JavaScript coverage"
SCRIPT_EXTENSIONS = (".js", ".mjs", ".cjs")

# Where node writes its coverage when it exits
COVERAGE_VARIABLE = "NODE_V8_COVERAGE"

# The statement and declaration kinds of tree-sitter-javascript, bar blocks
# and empty statements, which run nothing of their own, and labels, whose
# statement is one already
STATEMENTS = {
    "break_statement", "continue_statement", "debugger_statement", "do_statement", "export_statement",
    "expression_statement", "for_in_statement", "for_statement", "if_statement", "import_statement",
    "return_statement", "switch_statement", "throw_statement", "try_statement",
    "while_statement", "with_statement", "class_declaration", "function_declaration",
    "generator_function_declaration", "lexical_declaration", "using_declaration", "variable_declaration",
}

# Statements V8 gives a function range of their own, spanning just them; whether
# they ran is up to the code around them, not whether the function was called
DEFINITIONS = {"function_declaration", "generator_function_declaration"}

# Kinds whose report names only their first line, their body being statements of its own
COMPOUND = {
    "do_statement", "for_in_statement", "for_statement", "if_statement", "switch_statement", "try_statement", "while_statement", "with_statement", "class_declaration",
    "function_declaration", "generator_function_declaration",
}

LOGICAL_OPERATORS = {"&&", "||", "??"}

# Most characters of a missed branch shown in the report
BRANCH_TEXT_WIDTH = 72

NON_ASCII = re.compile(r"[^\x00-\x7f]")


class JsParseError(statement_coverage.SourceError):
    """A script that can't be measured: unreadable, too big or not parsable."""


###########################################################
# Statements and branches
###########################################################


def read_tree(source):
    """The syntax tree of a script, refusing one the parser can't make sense of."""
    return parsers.parse("javascript", source, JsParseError)


def utf16_offsets(source):
    """A function turning a UTF-8 byte offset in source into the UTF-16 offset V8 counts in."""
    byte_marks, unit_marks = [0], [0]
    extra_bytes = extra_units = 0
    for match in NON_ASCII.finditer(source):
        char = match.group()
        extra_bytes += len(char.encode()) - 1
        extra_units += ord(char) > 0xFFFF
        byte_marks.append(match.end() + extra_bytes)
        unit_marks.append(match.end() + extra_units)

    def convert(offset):
        index = bisect.bisect_right(byte_marks, offset) - 1
        return unit_marks[index] + offset - byte_marks[index]
    return convert


def walk(root):
    """Every named node under root, root included."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.named_children)


def is_statement(node):
    """Whether a node is a statement of its own, an export of a declaration being that declaration."""
    if node.type == "export_statement":
        return node.child_by_field_name("declaration") is None
    return node.type in STATEMENTS


def find_statements(root):
    """(start byte, end byte of a definition or None, (first, last) line) of each statement, in order.

    One holding other statements, or a compound kind, names only its first line."""
    nodes = sorted((node for node in walk(root) if is_statement(node)), key=lambda node: node.start_byte)
    found = []
    for index, node in enumerate(nodes):
        first, last = node.start_point[0] + 1, node.end_point[0] + 1
        holds = index + 1 < len(nodes) and nodes[index + 1].start_byte < node.end_byte
        if holds or node.type in COMPOUND:
            last = first
        found.append((node.start_byte, node.end_byte if node.type in DEFINITIONS else None, (first, last)))
    return found


def token_before(node, arm):
    """The operator token of node just before one of its operands."""
    return [child for child in node.children if not child.is_named and child.start_byte < arm.start_byte][-1]


def branch_arms(node):
    """The operands of node that run only on some paths: the right of && || ??, or both arms of ?:."""
    if node.type == "binary_expression" and node.child_by_field_name("operator").type in LOGICAL_OPERATORS:
        return [node.child_by_field_name("right")]
    if node.type == "ternary_expression":
        return [node.child_by_field_name("consequence"), node.child_by_field_name("alternative")]
    return []


def find_branches(root, data):
    """(start byte, line, text from its operator) of each branch arm in a script's bytes, in order."""
    found = []
    for node in walk(root):
        for arm in branch_arms(node):
            text = data[token_before(node, arm).start_byte:arm.end_byte].decode(errors="replace")
            text = " ".join(text.split())
            if len(text) > BRANCH_TEXT_WIDTH:
                text = text[:BRANCH_TEXT_WIDTH - 3] + "..."
            found.append((arm.start_byte, arm.start_point[0] + 1, text))
    return sorted(found)

###########################################################
# Coverage and measuring
###########################################################


def path_of(url):
    """The real path a file:// script url names, or None for any other url."""
    if not url.startswith("file://"):
        return None
    return os.path.realpath(urllib.request.url2pathname(urllib.parse.urlparse(url).path))


def script_ranges(script):
    """(start, end, count) of every range V8 gave one script."""
    return [(found["startOffset"], found["endOffset"], found["count"])
            for function in script["functions"] for found in function["ranges"]]


def read_coverage(coverage_dir):
    """{real path: [the ranges one process left for it, ...]} from every coverage file in a directory.

    A file node had not finished writing is passed over."""
    scripts = {}
    for name in sorted(os.listdir(coverage_dir)):
        if not (name.startswith("coverage-") and name.endswith(".json")):
            continue
        try:
            with open(os.path.join(coverage_dir, name), encoding="utf-8") as handle:
                data = json.load(handle)
        except ValueError:
            continue
        for script in data.get("result", []):
            path = path_of(script["url"])
            if path:
                scripts.setdefault(path, []).append(script_ranges(script))
    return scripts


def count_at(ranges, offset, skip=None):
    """V8's count at an offset: that of the smallest range holding it, 0 outside them all.

    A range spanning exactly skip, a definition's (start, end), is passed over."""
    best = None
    for start, end, count in ranges:
        if not start <= offset < end or (start, end) == skip:
            continue
        if best is None or end - start <= best[0]:
            best = (end - start, count)
    return best[1] if best else 0


def is_run(processes, offset, skip=None):
    """Whether any process ran the code at an offset."""
    return any(count_at(ranges, offset, skip) > 0 for ranges in processes)


def measure_script(source, processes, branch=False):
    """Statements run and missed, given the ranges each process left for the script.
    With branch, each branch arm also counts as a statement of its own."""
    root = read_tree(source)
    convert = utf16_offsets(source)
    lines = source.split("\n")
    statements = find_statements(root)
    total = len(statements)
    missed = [(lines_of, describe_statement(lines, lines_of)) for start, end, lines_of in statements
              if not is_run(processes, convert(start), None if end is None else (convert(start), convert(end)))]
    if branch:
        branches = find_branches(root, source.encode())
        total += len(branches)
        missed += [((line, line), text) for start, line, text in branches if not is_run(processes, convert(start))]
    missed.sort(key=lambda item: item[0])
    return {"statements": total, "covered": total - len(missed), "missed": [lines_of for lines_of, _ in missed],
            "missed_source": [text for _, text in missed]}


def measure(root, sources, branch=False, exclude=(), coverage_dir=None):
    """Measure every script under sources, bar those matching an exclude glob, against the
    coverage node left in coverage_dir; keys are paths relative to root."""
    coverage = read_coverage(coverage_dir)
    results = {}
    for script in statement_coverage.find_sources(sources, SCRIPT_EXTENSIONS):
        name = os.path.relpath(script, root)
        if is_excluded(name, exclude):
            continue
        try:
            source = statement_coverage.read_source(script, JsParseError)
            results[name] = measure_script(source, coverage.get(os.path.realpath(script), []), branch)
        except JsParseError as error:
            raise JsParseError(f"{name}: {error}") from error
    return results

###########################################################
# Plugin
###########################################################


def pytest_addoption(parser):
    statement_coverage.add_options(
        parser, PREFIX, TITLE,
        "JavaScript file or directory of *.js, *.mjs, *.cjs to measure, relative to rootdir (repeatable)",
        "also count the right side of each && || ?? and each arm of a ?: conditional as a statement")


def pytest_configure(config):
    config.js_cov_dir = None
    if not statement_coverage.is_enabled(config, PREFIX) or is_worker(config):
        return
    statement_coverage.get_sources(config, PREFIX)
    try:
        parsers.get_parser("javascript")
    except parsers.ParserMissing as error:
        raise pytest.UsageError(str(error)) from error
    config.js_cov_dir = tempfile.mkdtemp(prefix="js-cov-")
    config.js_cov_saved_env = os.environ.get(COVERAGE_VARIABLE)
    os.environ[COVERAGE_VARIABLE] = config.js_cov_dir


def pytest_unconfigure(config):
    coverage_dir = getattr(config, "js_cov_dir", None)
    if not coverage_dir:
        return
    if config.js_cov_saved_env is None:
        os.environ.pop(COVERAGE_VARIABLE, None)
    else:
        os.environ[COVERAGE_VARIABLE] = config.js_cov_saved_env
    shutil.rmtree(coverage_dir, ignore_errors=True)


@pytest.fixture
def js_traced_env(request):
    """Build a node environment measured for coverage, from env or a copy of os.environ.

    Without JavaScript coverage enabled it returns the environment unchanged."""
    # An xdist worker measures nothing itself but inherits the controller's directory
    enabled = statement_coverage.is_enabled(request.config, PREFIX)
    coverage_dir = os.environ.get(COVERAGE_VARIABLE) if enabled else None

    def build(env=None):
        traced = dict(os.environ if env is None else env)
        if coverage_dir:
            traced[COVERAGE_VARIABLE] = coverage_dir
        return traced
    return build


def pytest_sessionfinish(session, exitstatus):
    coverage_dir = getattr(session.config, "js_cov_dir", None)
    if coverage_dir:
        statement_coverage.finish(session, PREFIX, functools.partial(measure, coverage_dir=coverage_dir))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    statement_coverage.summarize(terminalreporter, config, PREFIX, TITLE, "Script")
