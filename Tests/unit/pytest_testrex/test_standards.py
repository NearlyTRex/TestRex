# Imports
import ast

# Third-party imports
import pytest

# Local imports
from pytest_testrex import standards


def test_imports_are_resolved_to_the_names_they_stand_for(parse_sample):
    tree = parse_sample("""
        import json
        import os.path
        import subprocess as sp
        from shutil import copy as duplicate, move
        from . import sibling
        def run():
            import yaml
        """)

    assert standards.imported_names(tree) == {
        "json": "json", "os": "os", "sp": "subprocess", "duplicate": "shutil.copy", "move": "shutil.move", "yaml": "yaml"}


@pytest.mark.parametrize("expression, name", [
    ("sp.run", "subprocess.run"),
    ("dumps", "json.dumps"),
    ("open", "open"),
    ("os.path.join", "os.path.join"),
    ("make().run", None),
])
def test_a_name_is_followed_through_the_imports(expression, name):
    imports = {"sp": "subprocess", "dumps": "json.dumps", "os": "os"}

    assert standards.dotted_name(ast.parse(expression).body[0].value, imports) == name


def test_calls_the_repository_wraps_are_reported_however_they_were_imported(parse_sample):
    tree = parse_sample("""
        import subprocess as sp
        from json import dumps
        def save(path, data):
            sp.run(["sync"])
            with open(path, "w") as handle:
                handle.write(dumps(data))
            print(len(data))
        """)
    wrappers = {"subprocess.run": "joybox.command", "open": "joybox.fileops", "json.dumps": "joybox.serialization"}

    assert standards.unwrapped_calls(tree, wrappers) == [
        "line 5: subprocess.run, use joybox.command",
        "line 6: open, use joybox.fileops",
        "line 7: json.dumps, use joybox.serialization"]


def test_prints_are_found(parse_sample):
    tree = parse_sample("print('a')\nlogger.info('b')\nout.print('c')\n")

    assert standards.prints(tree) == ["line 1: print"]


def test_every_way_out_of_the_process_is_found(parse_sample):
    tree = parse_sample("""
        import os
        import sys
        def a():
            sys.exit(1)
        def b():
            raise SystemExit
        def c():
            raise SystemExit(2)
        def d():
            os._exit(3)
        def e():
            exit()
        def f():
            raise ValueError("no")
        def g():
            try:
                pass
            except ValueError:
                raise
        """)

    assert standards.exits(tree) == [
        "line 5: sys.exit", "line 7: raise SystemExit", "line 9: raise SystemExit", "line 11: os._exit", "line 13: exit"]


def test_defaults_a_call_could_change_are_found(parse_sample):
    tree = parse_sample("""
        import collections
        def a(items=[], table={}, seen=set(), *, more=dict(), fine=None, count=0): pass
        def b(order=collections.OrderedDict(), names=(), squares=[x for x in range(3)]): pass
        handle = lambda cache={}: cache
        """)

    assert standards.mutable_defaults(tree) == [
        "a line 3", "a line 3", "a line 3", "a line 3", "b line 4", "b line 4", "lambda line 5"]


def test_bare_excepts_are_found(parse_sample):
    tree = parse_sample("""
        try:
            run()
        except:
            pass
        try:
            run()
        except ValueError:
            pass
        """)

    assert standards.bare_excepts(tree) == ["line 4"]


def test_what_runs_at_import_time_is_found_but_functions_and_the_main_guard_are_not(parse_sample):
    tree = parse_sample("""
        import os
        import subprocess
        HOME = os.environ["HOME"]
        DEBUG = os.getenv("DEBUG")
        CONFIG = open("config.ini").read()
        class Tool:
            VERSION = subprocess.check_output(["tool", "--version"])
        def run():
            return os.environ["PATH"], open("x")
        if __name__ == "__main__":
            print(open("y").read())
        """)

    assert standards.import_time_io(tree) == [
        "line 4: os.environ", "line 5: os.getenv", "line 6: open", "line 8: subprocess.check_output"]


@pytest.mark.parametrize("text, narrates", [
    ("# Fixed: the user asked for a faster path", True),
    ("# As discussed, this returns a list", True),
    ("# This was previously a dict", True),
    ("# Changed from int to float", True),
    ("# I added the retry here", True),
    ("# Now fixed for good", True),
    ("# Added during this conversation", True),
    ("# Successfully updated \u2705", True),
    ("# pytest.mark remembers markers this session already registered", False),
    ("# Reloads the saved matrix; the mirror pass clobbers it", False),
])
def test_narration_is_found_in_comments(parse_sample, text, narrates):
    tree = parse_sample(text + "\nx = 1\n")

    assert bool(standards.narration(tree, text + "\nx = 1\n")) is narrates


def test_narration_is_found_in_docstrings_too(parse_sample):
    source = 'def run():\n    """Now fixed to return a list."""\n'

    assert standards.narration(parse_sample(source), source) == ["line 2: 'Now fixed'"]


@pytest.mark.parametrize("text, code", [
    ("x = run()", True),
    ("print(value)", True),
    ("import os", True),
    ("return result", True),
    ("for item in items:", True),
    ("if ready:", True),
    ("Imports", False),
    ("A function pytest collects", False),
    ("Run it (twice) before the build", False),
    ("pylint: disable=unused-import", False),
    ("noqa: E501", False),
    ("", False),
    ("x + y", False),
])
def test_a_comment_is_code_when_it_parses_as_a_statement(text, code):
    assert standards.is_code(text) is code


def test_commented_out_code_is_found_but_an_indented_example_is_not(parse_sample):
    source = (
        "# Use it like this:\n"
        "#\n"
        "#     from tool import run\n"
        "#     run()\n"
        "# result = compute()\n"
        "x = 1  # y = 2\n")

    assert standards.commented_out_code(parse_sample(source), source) == [
        "line 5: # result = compute()", "line 6: # y = 2"]


@pytest.mark.parametrize("body, depth", [
    ("pass", 0),
    ("if a:\n        pass", 1),
    ("for x in y:\n        if x:\n            while x:\n                pass", 3),
    ("with a:\n        def inner():\n            if b:\n                pass", 1),
])
def test_nesting_counts_compound_statements_but_not_nested_functions(body, depth):
    function = ast.parse(f"def run():\n    {body}\n").body[0]

    assert standards.nesting_depth(function) == depth


def test_functions_past_the_limits_are_reported(parse_sample):
    tree = parse_sample("""
        def short():
            return 1
        def long():
            a = 1
            b = 2
            c = 3
            d = 4
            return a + b + c + d
        def deep(x):
            for a in x:
                for b in a:
                    if b:
                        pass
        """)

    assert standards.long_functions(tree, 5, 2) == [
        "long line 4: 6 lines, at most 5", "deep line 10: nested 3 deep, at most 2"]


def test_every_standard_has_a_check():
    assert set(standards.STANDARDS) == set(standards.CHECKS) | set(standards.SOURCE_CHECKS) | {"long-functions"}
