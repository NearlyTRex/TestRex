# Local imports
from pytest_testrex import hygiene, parsers
from pytest_testrex.discovery import SCRIPT_LANGUAGES


def test_duplicates_are_found_in_any_iterable():
    assert hygiene.duplicated(iter(["b", "a", "b", "c", "a"])) == ["a", "b"]
    assert hygiene.duplicated([]) == []


def test_tests_defined_twice_are_found(parse_sample):
    tree = parse_sample("def test_a(): pass\ndef test_a(): pass\ndef test_b(): pass\ndef helper(): pass\ndef helper(): pass\n")

    assert hygiene.duplicate_tests(tree) == ["test_a"]
    assert hygiene.duplicate_definitions(tree) == ["helper", "test_a"]


def test_test_methods_defined_twice_are_found_per_class(parse_sample):
    tree = parse_sample("""
        class TestA:
            def test_x(self): pass
            def test_x(self): pass
        class TestB:
            def test_x(self): pass
        """)

    assert hygiene.duplicate_test_methods(tree) == {"TestA": ["test_x"]}


def test_only_upper_case_constants_assigned_twice_are_found(parse_sample):
    tree = parse_sample("LIMIT = 1\nLIMIT = 2\nvalue = 1\nvalue = 2\nA, B = 1, 2\n")

    assert hygiene.duplicate_constants(tree) == ["LIMIT"]


def test_late_imports_are_reported_but_a_docstring_and_the_header_are_not(parse_sample):
    tree = parse_sample('"""Docstring."""\nimport os\nfrom sys import path\nLIMIT = 3\nimport json\ndef f():\n    import re\n')

    assert hygiene.late_imports(tree) == [5]


def test_lines_are_counted(write_file):
    assert hygiene.line_count(str(write_file("a.py", "one\ntwo\nthree"))) == 3


def test_a_script_test_file_holds_tests_when_it_calls_test_or_it():
    javascript, lua = SCRIPT_LANGUAGES["javascript"], SCRIPT_LANGUAGES["lua"]

    assert hygiene.holds_script_tests(parsers.parse("javascript", "test.todo('later');\n"), javascript)
    assert not hygiene.holds_script_tests(parsers.parse("javascript", "describe('only a group', () => {});\n"), javascript)
    assert hygiene.holds_script_tests(parsers.parse("lua", "it('runs', function() end)\n"), lua)
    assert not hygiene.holds_script_tests(parsers.parse("lua", "local x = 1\n"), lua)
