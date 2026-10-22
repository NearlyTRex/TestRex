# Imports
import ast
import collections

# Local imports
from pytest_testrex.discovery import FUNCTION_DEFS, is_test_function

###########################################################
# File hygiene
#
# A test defined twice in one file silently replaces the first, which then
# never runs again and reports nothing when it would have failed. Large files
# are where this happens, so they are also kept to a size where it stays
# visible.
###########################################################

def duplicated(names):
    return sorted(name for name, count in collections.Counter(names).items() if count > 1)


def duplicate_tests(tree):
    return duplicated(node.name for node in tree.body if is_test_function(node))


# {class: names} for test methods defined twice within one class
def duplicate_test_methods(tree):
    return {
        node.name: names for node in tree.body if isinstance(node, ast.ClassDef)
        for names in [duplicated(member.name for member in node.body if is_test_function(member))]
        if names}


def duplicate_definitions(tree):
    return duplicated(node.name for node in tree.body if isinstance(node, FUNCTION_DEFS + (ast.ClassDef,)))


def duplicate_constants(tree):
    return duplicated(
        target.id for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name) and target.id.isupper())


# Lines of imports that come after the first real statement
def late_imports(tree):
    first_statement = None
    late = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if first_statement is not None:
                late.append(node.lineno)
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            if first_statement is None:
                first_statement = node.lineno
    return late


def line_count(path):
    with open(path, "r", encoding = "utf-8") as handle:
        return sum(1 for _ in handle)
