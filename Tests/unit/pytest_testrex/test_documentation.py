# Imports
import ast
import textwrap

# Third-party imports
import pytest

# Local imports
from pytest_testrex import documentation


def parse(text):
    source = textwrap.dedent(text)
    return ast.parse(source), source


def test_public_definitions_are_module_functions_classes_and_public_methods_of_public_classes():
    tree, _ = parse("""
        def run(): pass
        def _hidden(): pass
        class Tool:
            def go(self): pass
            def _inner(self): pass
            def __init__(self): pass
        class _Private:
            def go(self): pass
        """)

    assert [name for name, _ in documentation.public_definitions(tree)] == ["run", "Tool", "Tool.go"]


@pytest.mark.parametrize("style, expected", [
    ("comment", ["by_docstring (line 7)", "bare (line 9)"]),
    ("docstring", ["by_comment (line 3)", "decorated (line 6)", "bare (line 9)"]),
    ("either", ["bare (line 9)"]),
])
def test_each_style_accepts_its_own_documentation(style, expected):
    tree, source = parse('''
        # Says what it does
        def by_comment(): pass
        # Above the decorator
        @cache
        def decorated(): pass
        def by_docstring():
            """Says what it does."""
        def bare(): pass
        ''')

    assert documentation.undocumented(tree, source, style) == expected


def test_tests_and_pytest_hooks_describe_themselves():
    tree, source = parse("""
        def test_runs(): pass
        class TestTool:
            def test_go(self): pass
        def pytest_configure(config): pass
        def helper(): pass
        """)

    assert documentation.undocumented(tree, source, "comment") == ["helper (line 6)"]


def test_a_comment_needs_to_be_directly_above():
    tree, source = parse("""
        # Not this one

        def run(): pass
        """)

    assert documentation.undocumented(tree, source, "comment") == ["run (line 4)"]


def test_sections_are_read_with_their_entries_and_not_their_continuations():
    docstring = ast.get_docstring(ast.parse(textwrap.dedent('''
        def run(path, count):
            """Run it.

            Arguments:
                path (str): Where.
                    Continued here.
                count: How many.

            Return:
                int: The result.
            Example:
                text
            Not a section line.
            """
        ''')).body[0])

    assert documentation.docstring_sections(docstring) == {
        "Args": ["path (str): Where.", "count: How many."], "Returns": ["int: The result."]}


def test_an_unindented_line_ends_a_section():
    assert documentation.docstring_sections("Run.\n\nArgs:\n    path: Where.\nTrailing prose.\n") == {"Args": ["path: Where."]}


def test_documentable_parameters_leave_out_self_and_cls():
    method = ast.parse("def run(self, a, /, b, *args, c, **kwargs): pass").body[0]

    assert documentation.documentable_parameters(method) == ["a", "b", "c", "args", "kwargs"]


@pytest.mark.parametrize("body, returns", [
    ("return 1", True),
    ("yield 1", True),
    ("yield from other()", True),
    ("return", False),
    ("return None", False),
    ("def inner():\n        return 1", False),
    ("callback = lambda: 1", False),
    ("pass", False),
])
def test_a_value_is_returned_only_by_the_function_itself(body, returns):
    function = ast.parse(f"def run():\n    {body}\n").body[0]

    assert documentation.returns_a_value(function) is returns


def test_sections_that_disagree_with_the_signature_are_reported():
    tree, _ = parse('''
        def stale(path):
            """Run it.

            Args:
                path: Where.
                count (int): Gone.
                *args: Extra.
            """
        def splat(*args, **kwargs):
            """Run it.

            Args:
                *args: Positional.
                **kwargs: Keyword.
            """
        def claims(path):
            """Run it.

            Returns:
                int: Nothing, really.
            """
            print(path)
        def honest(path):
            """Run it.

            Returns:
                int: The count.
            """
            return len(path)
        def plain():
            """No sections."""
        def bare(): pass
        class Tool:
            """Args:
                gone: Not a function's.
            """
        ''')

    assert documentation.section_mismatches(tree) == [
        "stale: Args names ['count', 'args'], which it does not take",
        "claims: documents a return value but never returns one"]


def test_comment_blocks_and_descriptions_are_measured():
    tree, source = parse('''
        x = 1
        # One
        # Two
        def commented(): pass
        def documented():
            """One.

            Two.

            Args:
                a: Not counted.
            """
        ''')
    lines = source.splitlines()
    commented, documented = tree.body[1], tree.body[2]

    assert documentation.comment_lines_above(commented, lines) == 2
    assert documentation.comment_lines_above(documented, lines) == 0
    assert documentation.description_lines(ast.get_docstring(documented)) == 3


def test_descriptions_past_the_limit_are_reported_but_tests_are_not():
    tree, source = parse('''
        # One
        # Two
        def commented(): pass
        def documented():
            """One.
            Two.
            Three."""
        # One
        # Two
        # Three
        def test_long(): pass
        def bare(): pass
        ''')

    assert documentation.overlong(tree, source, 2) == ["documented: 3 lines, at most 2"]
    assert documentation.overlong(tree, source, 3) == []


@pytest.mark.parametrize("text, words", [
    ("Gets the settings", {"get", "setting"}),
    ("get_settings", {"get", "setting"}),
    ("A helper for the class", set()),
    ("Is it ok", {"ok"}),
])
def test_content_words_drop_filler_case_and_plurals(text, words):
    assert documentation.content_words(text) == words


def test_a_description_that_repeats_the_name_is_a_paraphrase():
    tree, source = parse('''
        # Get the settings
        def get_settings(): pass
        # The settings this run loaded, or None without a table
        def load_settings(): pass
        def read_file():
            """Reads a file."""
        def write_file():
            """Writes the file atomically, through a temporary beside it."""
        def bare(): pass
        ''')

    assert documentation.paraphrases(tree, source) == [
        "get_settings: 'Get the settings' says no more than its name",
        "read_file: 'Reads a file.' says no more than its name"]


def test_a_module_docstring_is_found():
    assert documentation.has_module_docstring(ast.parse('"""Says what it is."""\n'))
    assert not documentation.has_module_docstring(ast.parse("x = 1\n"))
