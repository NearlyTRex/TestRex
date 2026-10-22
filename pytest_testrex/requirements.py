# Imports
import ast
import os

# Local imports
from pytest_testrex.discovery import FUNCTION_DEFS, is_test_class, is_test_function, parameter_names, is_fixture

###########################################################
# Required programs
#
# A test that needs a program outside the process declares it with
# requires_binary (on PATH) or another requirement marker the repository adds,
# at module, class or test level. The markers are enforced at collection, so a
# machine without the program skips the test before any fixture starts, and
# the requirement is readable in one place rather than buried in a test body.
# A requirement that is only enforced at run time, or not declared at all,
# fails here instead of failing, or silently skipping, on someone else's machine.
###########################################################

SUBPROCESS_CALLS = {"run", "call", "check_call", "check_output", "Popen"}


# marker(...) calls within nodes, such as pytest.mark.requires_binary("git")
def marker_calls(nodes, marker):
    return [
        node for top in nodes for node in ast.walk(top)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == marker]


def marked_names(nodes, marker = "requires_binary"):
    return {
        argument.value for call in marker_calls(nodes, marker) for argument in call.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)}


# Each name an "a|b" requirement accepts
def accepted(names):
    return {option for name in names for option in name.split("|")}


def module_marks(tree):
    return [
        node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets)]


def declared_anywhere(tree, marker = "requires_binary"):
    decorators = [
        decorator for node in ast.walk(tree) if isinstance(node, FUNCTION_DEFS + (ast.ClassDef,))
        for decorator in node.decorator_list]
    return marked_names(module_marks(tree), marker) | marked_names(decorators, marker)


# (name, function, binaries declared for it at module, class or test level) per test
def declared_per_test(tree):
    module_level = marked_names(module_marks(tree))
    found = []
    for node in tree.body:
        if is_test_function(node):
            found.append((node.name, node, module_level | marked_names(node.decorator_list)))
        elif is_test_class(node):
            class_level = module_level | marked_names(node.decorator_list)
            found.extend(
                ("%s.%s" % (node.name, member.name), member, class_level | marked_names(member.decorator_list))
                for member in node.body if is_test_function(member))
    return found


# The conftest.py files whose fixtures a test file can see
def visible_conftests(path, tests_dir):
    found = []
    directory = os.path.dirname(path)
    while directory == tests_dir or directory.startswith(tests_dir + os.sep):
        conftest = os.path.join(directory, "conftest.py")
        if os.path.isfile(conftest) and conftest != path:
            found.append(conftest)
        directory = os.path.dirname(directory)
    return found


# The fixtures defined in trees, by name, with the fixtures each one requests;
# trees are nearest first, so a nearer fixture replaces a farther one
def fixture_parameters(trees):
    found = {}
    for tree in reversed(trees):
        for node in tree.body:
            if isinstance(node, FUNCTION_DEFS) and is_fixture(node):
                found[node.name] = set(parameter_names(node))
    return found


# The programs requesting these fixtures needs, through any depth of fixtures
def binaries_needed(requested, fixtures, fixture_programs):
    needed, seen, pending = set(), set(), list(requested)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        needed |= fixture_programs.get(name, set())
        pending.extend(fixtures.get(name, ()))
    return needed


# "test needs [programs]" for each test that uses a program fixture without declaring its programs
def undeclared_fixture_programs(tree, conftest_trees, fixture_programs):
    fixtures = fixture_parameters([tree] + list(conftest_trees))
    missing = []
    for name, function, declared in declared_per_test(tree):
        needed = binaries_needed(parameter_names(function), fixtures, fixture_programs)
        if not needed <= accepted(declared):
            missing.append("%s needs %s" % (name, sorted(needed - accepted(declared))))
    return missing


# Whether a call searches this machine's PATH: shutil.which(...) or which(...)
def is_host_lookup(node):
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    if isinstance(function, ast.Name):
        return function.id == "which"
    return (isinstance(function, ast.Attribute) and function.attr == "which"
            and isinstance(function.value, ast.Name) and function.value.id == "shutil")


def calls_skip(statements):
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "skip"
        for statement in statements for node in ast.walk(statement))


# Lines where a requirement is enforced at run time rather than by a marker: a
# function taking a fixture named after a marker, a which() check that skips,
# or a skipif whose condition looks up a program
def imperative_gates(tree, markers):
    looked_up = {
        target.id for node in tree.body if isinstance(node, ast.Assign)
        and any(is_host_lookup(sub) for sub in ast.walk(node.value))
        for target in node.targets if isinstance(target, ast.Name)}
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, FUNCTION_DEFS) and set(parameter_names(node)) & set(markers):
            lines.append(node.lineno)
        elif isinstance(node, ast.If) and any(is_host_lookup(sub) for sub in ast.walk(node.test)) and calls_skip(node.body):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "skipif":
            condition = list(ast.walk(node.args[0])) if node.args else []
            if any(is_host_lookup(sub) or (isinstance(sub, ast.Name) and sub.id in looked_up) for sub in condition):
                lines.append(node.lineno)
    return sorted(set(lines))


# Lines of requirement markers that name no program, or name one by anything but a string literal
def non_literal_markers(tree, markers):
    bad = []
    for marker in markers:
        for call in marker_calls([tree], marker):
            literal = all(isinstance(argument, ast.Constant) and isinstance(argument.value, str) for argument in call.args)
            if not call.args or not literal or call.keywords:
                bad.append(call.lineno)
    return sorted(bad)


def is_subprocess_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SUBPROCESS_CALLS
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess")


# Programs run for real through subprocess.<call>([<literal>, ...])
def subprocess_binaries(tree):
    found = set()
    for node in ast.walk(tree):
        if is_subprocess_call(node) and node.args and isinstance(node.args[0], ast.List) and node.args[0].elts:
            first = node.args[0].elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


# Whether the tests start this interpreter in a subprocess, which is a program
# outside the process that is always there to run
def runs_the_interpreter(tree):
    return any(
        is_subprocess_call(node) and node.args and isinstance(node.args[0], ast.List) and node.args[0].elts
        and ast.unparse(node.args[0].elts[0]) == "sys.executable"
        for node in ast.walk(tree))


# Whether a file declares any program it needs, through any requirement marker
def declares_a_program(tree, markers):
    return any(declared_anywhere(tree, marker) for marker in markers) or runs_the_interpreter(tree)
