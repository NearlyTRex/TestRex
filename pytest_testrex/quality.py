# Imports
import ast
import collections
import hashlib

# Local imports
from pytest_testrex.discovery import FUNCTION_DEFS, checks_in, collected_tests

###########################################################
# Test quality
#
# A test that cannot fail reads as coverage and protects nothing. These catch
# the shapes that let a test pass whatever the code does: asserting nothing,
# asserting only inside a branch that may not run, swallowing the exception it
# exists to see, an assertion true by construction, checking only that a value
# exists or has a type, and a helper pasted into several files that then drift
# apart. There are no exemption lists: a test that trips one is fixed.
###########################################################

CONDITIONAL = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try)


# Whether a test makes a check anywhere, even one that may never run
def has_any_check(function, checkers = frozenset()):
    return bool(checks_in(function.body, (), checkers))


# A check that runs whenever the test does: not inside a branch, loop or try
def has_unconditional_check(function, checkers = frozenset()):
    return bool(checks_in(function.body, CONDITIONAL, checkers))


# name (line N), to point at a function in a failure
def label(function):
    return "%s (line %d)" % (function.name, function.lineno)


# Tests that make no check at all
def unchecked_tests(tree, checkers = frozenset()):
    return [label(function) for function in collected_tests(tree) if not has_any_check(function, checkers)]


# Tests whose every check sits in a branch, loop or try
def conditional_tests(tree, checkers = frozenset()):
    return [
        label(function) for function in collected_tests(tree)
        if has_any_check(function, checkers) and not has_unconditional_check(function, checkers)]


# Lines of except handlers whose whole body is pass (or a bare string)
def swallowed_handlers(tree):
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                body = [statement for statement in handler.body
                        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))]
                if all(isinstance(statement, ast.Pass) for statement in body):
                    lines.append(handler.lineno)
    return sorted(lines)


# Why an assertion cannot fail, or None
def tautology(assertion):
    test = assertion.test
    if isinstance(test, ast.Constant) and test.value:
        return "a constant that is always true"
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.Is)):
        left, right = test.left, test.comparators[0]
        if ast.unparse(left) == ast.unparse(right):
            return "compares a value with itself"
        if isinstance(right, ast.BoolOp) and isinstance(right.op, ast.Or) and ast.unparse(right.values[0]) == ast.unparse(left):
            return "compares a value with itself or a fallback"
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        if any(isinstance(value, ast.Constant) and value.value for value in test.values):
            return "has an or branch that is always true"
    return None


# "test line N: why" for each assertion in a test that cannot fail
def tautologies(tree):
    return [
        "%s line %d: %s" % (function.name, node.lineno, tautology(node))
        for function in collected_tests(tree) for node in ast.walk(function)
        if isinstance(node, ast.Assert) and tautology(node)]


# An assert that only says a value exists or has a type
def is_weak_assertion(assertion):
    test = assertion.test
    if isinstance(test, ast.Call):
        return ast.unparse(test.func) == "isinstance"
    return (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.IsNot)
            and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value is None)


# Tests whose only checks are weak, so they pass for almost any value
def weak_only_tests(tree, checkers = frozenset()):
    weak = []
    for function in collected_tests(tree):
        checks = checks_in(function.body, (), checkers)
        if checks and all(isinstance(check, ast.Assert) and is_weak_assertion(check) for check in checks):
            weak.append(label(function))
    return weak


# Lines that build a raising callable as (_ for _ in ()).throw(...), which
# reads as a puzzle; a def that raises says the same thing
def generator_throws(tree):
    return sorted(
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "throw"
        and isinstance(node.func.value, ast.GeneratorExp))


# (name, source) of every module level function that is not a test. The source
# includes the module constants it reads, so the same function over a
# different table is not mistaken for a copy.
def module_helpers(tree):
    constants = {
        target.id: ast.unparse(node) for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)}
    found = []
    for node in tree.body:
        if isinstance(node, FUNCTION_DEFS) and not node.name.startswith("test_") and not node.name.startswith("__"):
            names = sorted({name.id for name in ast.walk(node) if isinstance(name, ast.Name)})
            found.append((node.name, ast.unparse(node) + "".join("\n" + constants[name] for name in names if name in constants)))
    return found


# (name, files) for each helper whose identical source is in several files;
# two different helpers sharing a name are reported apart
def copied_helpers(sources_by_file):
    where = collections.defaultdict(set)
    for path, helpers in sources_by_file.items():
        for name, source in helpers:
            where[(name, hashlib.sha256(source.encode()).hexdigest())].add(path)
    return sorted((name, sorted(files)) for (name, _), files in where.items() if len(files) > 1)
