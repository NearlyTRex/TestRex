# Imports
import ast

# Local imports
from pytest_testrex.standards import dotted_name, imported_names

###########################################################
# Practices
#
# Habits that make tests flaky or hide what they check: changing the whole
# process where later tests inherit it, a pytest.raises that accepts any error
# or wraps more than the call that raises, and a skip nobody can explain.
###########################################################

# Calls that change the whole process, and so every test that runs after them
PROCESS_CALLS = {
    "os.chdir", "os.umask", "os.putenv", "os.unsetenv", "locale.setlocale",
    "sys.path.insert", "sys.path.append", "sys.path.extend", "sys.path.remove", "sys.path.pop", "sys.path.clear",
    "os.environ.pop", "os.environ.update", "os.environ.setdefault", "os.environ.clear", "os.environ.popitem",
}

# Objects the process shares, which a test replaces only through monkeypatch or a fixture
PROCESS_OBJECTS = {"sys.path", "sys.argv", "sys.stdin", "sys.stdout", "sys.stderr", "os.environ"}

# Containers the process shares, whose items a test sets only through monkeypatch
PROCESS_MAPPINGS = {"sys.modules", "os.environ"}

# What pytest takes a reason from as its first argument, when the call has one
SKIPS = {
    "pytest.skip": True,
    "pytest.xfail": True,
    "pytest.mark.skip": True,
    "pytest.mark.xfail": False,
    "pytest.mark.skipif": False,
}

# The errors a pytest.raises names without saying which one it means
BROAD_ERRORS = {"Exception", "BaseException"}


# The line number a "line N: ..." finding starts with
def line_of(finding):
    return int(finding.split(":")[0].split()[1])


# What an assignment or deletion changes in the process, as "line N: what", or None
def process_target(node, target, imports):
    if isinstance(target, ast.Subscript) and dotted_name(target.value, imports) in PROCESS_MAPPINGS:
        return "line %d: %s[...]" % (node.lineno, dotted_name(target.value, imports))
    if isinstance(target, ast.Attribute) and dotted_name(target, imports) in PROCESS_OBJECTS:
        return "line %d: %s" % (node.lineno, dotted_name(target, imports))
    return None


# The targets an assignment, augmented assignment or deletion writes to
def written_targets(node):
    return [node.target] if isinstance(node, ast.AugAssign) else node.targets


# "line N: what" for each place a test changes the process for every later one: os.environ, the
# working directory, the umask, sys.path, sys.modules and the standard streams
def process_mutations(tree):
    imports = imported_names(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and dotted_name(node.func, imports) in PROCESS_CALLS:
            found.append("line %d: %s(...)" % (node.lineno, dotted_name(node.func, imports)))
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
            found.extend(
                finding for target in written_targets(node)
                for finding in [process_target(node, target, imports)] if finding)
    return sorted(found, key = line_of)


# Each pytest.raises call as a (call, with statement or None) pair, through the imports
def raises_calls(tree):
    imports = imported_names(tree)
    withs = {id(item.context_expr): node for node in ast.walk(tree) if isinstance(node, ast.With) for item in node.items}
    return [(node, withs.get(id(node))) for node in ast.walk(tree)
            if isinstance(node, ast.Call) and dotted_name(node.func, imports) == "pytest.raises"]


# line N for each pytest.raises(Exception) without a match, which passes for any error at all
def broad_raises(tree):
    imports = imported_names(tree)
    return ["line %d" % line for line in sorted(
        call.lineno for call, _ in raises_calls(tree)
        if call.args and dotted_name(call.args[0], imports) in BROAD_ERRORS
        and not any(keyword.arg == "match" for keyword in call.keywords))]


# line N for each pytest.raises block that holds more than one statement, so a line other than the
# one that raises can raise the expected error and pass
def crowded_raises(tree):
    return ["line %d" % line for line in sorted(
        statement.lineno for _, statement in raises_calls(tree) if statement is not None and len(statement.body) > 1)]


# Whether a node is one of the skip markers used without a call, as in @pytest.mark.skip
def is_bare_mark(node, imports):
    name = dotted_name(node, imports)
    return name in SKIPS and name.startswith("pytest.mark.")


# Whether a skip call gives its reason, positionally where pytest takes one or by keyword
def gives_reason(call, imports):
    positional = SKIPS[dotted_name(call.func, imports)] and call.args
    return bool(positional) or any(keyword.arg == "reason" for keyword in call.keywords)


# line N for each skip, xfail or skipif that gives no reason, as a call or as a bare marker
def unexplained_skips(tree):
    imports = imported_names(tree)
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and dotted_name(node.func, imports) in SKIPS:
            if not gives_reason(node, imports):
                found.append(node.lineno)
        elif isinstance(node, ast.Attribute) and id(node) not in called and is_bare_mark(node, imports):
            found.append(node.lineno)
    return ["line %d" % line for line in sorted(found)]
