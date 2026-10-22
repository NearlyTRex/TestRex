# Imports
import ast

# Third-party imports
import pytest

# Local imports
from pytest_testrex import quality
from pytest_testrex.discovery import collected_tests, local_checkers


@pytest.fixture
def only_test(parse_sample):
    def build(body):
        return collected_tests(parse_sample("def test_x(mock):\n" + body))[0]
    return build


def test_a_bare_call_checks_nothing(only_test):
    assert not quality.has_any_check(only_test("    run()\n"))


@pytest.mark.parametrize("body", [
    "    assert run()\n",
    "    mock.assert_called_once_with(1)\n",
    "    pytest.fail('no')\n",
    "    with pytest.raises(ValueError):\n        run()\n",
    "    with pytest.warns(UserWarning):\n        run()\n",
    "    verify(run())\n",
])
def test_asserts_mock_checks_fails_raises_blocks_and_known_checkers_count(only_test, body):
    assert quality.has_unconditional_check(only_test(body), frozenset({"verify"}))


@pytest.mark.parametrize("body", [
    "    if ok:\n        assert run()\n",
    "    for x in xs:\n        assert x\n",
    "    while x:\n        assert x\n",
    "    try:\n        run()\n    except ValueError:\n        assert False\n",
])
def test_a_check_inside_a_branch_loop_or_try_is_conditional(only_test, body):
    function = only_test(body)

    assert quality.has_any_check(function)
    assert not quality.has_unconditional_check(function)


def test_a_try_finally_without_a_handler_is_not_a_branch(only_test):
    assert quality.has_unconditional_check(only_test("    try:\n        assert run()\n    finally:\n        undo()\n"))


def test_a_check_beside_a_branch_still_runs(only_test):
    assert quality.has_unconditional_check(only_test("    if ok:\n        pass\n    assert run()\n"))


def test_unchecked_and_conditional_tests_are_named_with_their_lines(parse_sample):
    tree = parse_sample("""
        def test_none():
            run()
        def test_branch():
            if ok:
                assert run()
        def test_fine():
            assert run()
        """)

    assert quality.unchecked_tests(tree) == ["test_none (line 2)"]
    assert quality.conditional_tests(tree) == ["test_branch (line 4)"]


def test_a_helper_that_checks_counts_through_any_depth(parse_sample):
    tree = parse_sample("def check(x):\n    assert x\ndef check_twice(x):\n    check(x)\n    check(x)\ndef plain(x):\n    return x\n")

    assert local_checkers(tree) == {"check", "check_twice"}


def test_a_helper_that_calls_an_imported_checker_counts(parse_sample):
    tree = parse_sample("def check_run(seams):\n    verify(seams)\n")

    assert local_checkers(tree) == set()
    assert local_checkers(tree, frozenset({"verify"})) == {"check_run"}


def test_a_handler_that_only_passes_is_a_swallow(parse_sample):
    tree = parse_sample("""
        def a():
            try:
                run()
            except ValueError:
                pass
        def b():
            try:
                run()
            except ValueError:
                return None
        def c():
            try:
                run()
            except ValueError:
                "ignored"
        """)

    assert quality.swallowed_handlers(tree) == [5, 15]


@pytest.mark.parametrize("expression, cannot_fail", [
    ("True", True),
    ("cmd[0] == cmd[0]", True),
    ("value is value", True),
    ("op.path == (op.path or 'x')", True),
    ("result or True", True),
    ("cmd[0] == (op.path or 'x')", False),
    ("result == 3", False),
    ("result or default", False),
    ("not result", False),
])
def test_tautologies_are_recognised(expression, cannot_fail):
    assert bool(quality.tautology(ast.parse("assert " + expression).body[0])) is cannot_fail


def test_tautologies_are_reported_per_test(parse_sample):
    tree = parse_sample("def test_x():\n    assert True\n    assert run() == 2\n")

    assert quality.tautologies(tree) == ["test_x line 2: a constant that is always true"]


@pytest.mark.parametrize("body, weak", [
    ("    assert run() is not None\n", True),
    ("    assert isinstance(run(), dict)\n", True),
    ("    assert run() is not None\n    assert isinstance(run(), dict)\n", True),
    ("    assert run() == 1\n", False),
    ("    assert callable(run())\n", False),
    ("    assert run() is not False\n", False),
    ("    assert run() is not None\n    mock.assert_called_once()\n", False),
    ("    assert isinstance(run(), dict)\n    with pytest.raises(ValueError):\n        run()\n", False),
    ("    run()\n", False),
])
def test_only_existence_or_type_checks_are_weak(parse_sample, body, weak):
    assert bool(quality.weak_only_tests(parse_sample("def test_x(mock):\n" + body))) is weak


def test_a_generator_throw_is_found_and_a_raising_function_is_not(parse_sample):
    found = parse_sample("f = lambda: (_ for _ in ()).throw(ValueError('x'))\n")
    clean = parse_sample("def f():\n    raise ValueError('x')\ng = gen.throw(ValueError('x'))\n")

    assert quality.generator_throws(found) == [1]
    assert quality.generator_throws(clean) == []


def test_identical_helpers_are_matched_by_source_and_tests_are_not_helpers(parse_sample):
    one = quality.module_helpers(parse_sample("def run(a):\n    return a\ndef test_x():\n    pass\ndef __dir__():\n    return []\n"))
    two = quality.module_helpers(parse_sample("def run(a):\n    return a\n"))
    other = quality.module_helpers(parse_sample("def run(a, b):\n    return a\n"))

    assert one == two
    assert one != other
    assert [name for name, _ in one] == ["run"]


def test_two_sets_of_copies_sharing_a_name_are_both_reported():
    one = [("write", "def write(): return 1")]
    two = [("write", "def write(): return 2")]

    assert quality.copied_helpers({"a.py": one, "b.py": one, "c.py": two, "d.py": two, "e.py": []}) == [
        ("write", ["a.py", "b.py"]), ("write", ["c.py", "d.py"])]


def test_the_same_function_over_a_different_constant_is_not_a_copy(parse_sample):
    one = quality.module_helpers(parse_sample("KINDS = {'a': 1}\ndef kind(r):\n    return KINDS[r]\n"))
    other = quality.module_helpers(parse_sample("KINDS = {'b': 2}\ndef kind(r):\n    return KINDS[r]\n"))

    assert one != other
