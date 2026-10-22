# Imports
import ast
import re

# Local imports
from pytest_testrex.discovery import FUNCTION_DEFS

###########################################################
# Documentation
#
# Every public function, class and method in the library says what it is
# for, in the repository's own style: a comment directly above it, a
# docstring, or either. Where a docstring has Google-style sections, they
# must agree with the signature, since documentation that names a parameter
# the function no longer takes is worse than none.
###########################################################

DOC_STYLES = ("comment", "docstring", "either")

SECTION_HEADER = re.compile(r"^(?P<name>Args|Arguments|Parameters|Returns|Return|Yields|Raises):\s*$")
# "name (type): description", "name: description", "*args: ...", "**kwargs: ..."
ARGUMENT_ENTRY = re.compile(r"^\*{0,2}(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*:")


# Names without a leading underscore are part of a module's interface
def is_public(name):
    return not name.startswith("_")


# Names that already say what they are: a test, whose name describes it, and
# a pytest hook, whose contract is pytest's own documentation
def is_self_describing(name):
    return name.startswith(("test_", "Test", "pytest_"))


# The public functions, classes and methods of a module, as (qualified name, node).
# Methods count only in public classes; nested functions never do.
def public_definitions(tree):
    found = []
    for node in tree.body:
        if isinstance(node, FUNCTION_DEFS) and is_public(node.name):
            found.append((node.name, node))
        elif isinstance(node, ast.ClassDef) and is_public(node.name):
            found.append((node.name, node))
            found.extend(
                ("%s.%s" % (node.name, member.name), member) for member in node.body
                if isinstance(member, FUNCTION_DEFS) and is_public(member.name))
    return found


# Whether the line directly above a definition, or above its first decorator, is a comment
def has_comment_above(node, lines):
    first = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    return first >= 2 and lines[first - 2].strip().startswith("#")


# Whether a definition is documented in the style asked for
def is_documented(node, lines, style):
    if style == "comment":
        return has_comment_above(node, lines)
    if style == "docstring":
        return bool(ast.get_docstring(node))
    return has_comment_above(node, lines) or bool(ast.get_docstring(node))


# "name (line N)" for each public definition not documented in the style
def undocumented(tree, source, style):
    lines = source.splitlines()
    return ["%s (line %d)" % (name, node.lineno) for name, node in public_definitions(tree)
            if not is_self_describing(node.name) and not is_documented(node, lines, style)]


SECTION_ALIASES = {"Arguments": "Args", "Parameters": "Args", "Return": "Returns"}


# The number of leading spaces on a line
def indent_of(line):
    return len(line) - len(line.lstrip())


# {section: [entries]} for the Google-style sections of a cleaned docstring. An
# entry is a line at the section's first indent; deeper lines continue it, and
# a line no deeper than the header ends the section.
def docstring_sections(docstring):
    sections = {}
    current = header_indent = entry_indent = None
    for line in docstring.splitlines():
        if not line.strip():
            continue
        header = SECTION_HEADER.match(line.strip())
        if header:
            current = SECTION_ALIASES.get(header["name"], header["name"])
            header_indent, entry_indent = indent_of(line), None
            sections[current] = []
        elif current and indent_of(line) > header_indent:
            if entry_indent is None:
                entry_indent = indent_of(line)
            if indent_of(line) == entry_indent:
                sections[current].append(line.strip())
        else:
            current = None
    return sections


# The parameter names an Args: section may document: everything but self and cls
def documentable_parameters(function):
    arguments = function.args
    names = [argument.arg for argument in arguments.posonlyargs + arguments.args + arguments.kwonlyargs]
    names += [argument.arg for argument in (arguments.vararg, arguments.kwarg) if argument]
    return [name for name in names if name not in ("self", "cls")]


# Whether a function returns or yields a value anywhere outside the functions nested in it
def returns_a_value(function):
    def visit(node):
        if isinstance(node, (FUNCTION_DEFS + (ast.Lambda, ast.ClassDef))) and node is not function:
            return False
        if isinstance(node, ast.Return) and node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None):
            return True
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        return any(visit(child) for child in ast.iter_child_nodes(node))
    return visit(function)


# "name: problem" for each docstring section that disagrees with its function
def section_mismatches(tree):
    found = []
    for name, node in public_definitions(tree):
        docstring = ast.get_docstring(node) if isinstance(node, FUNCTION_DEFS) else None
        if not docstring:
            continue
        sections = docstring_sections(docstring)
        parameters = documentable_parameters(node)
        documented = [match["name"] for match in map(ARGUMENT_ENTRY.match, sections.get("Args", [])) if match]
        stale = [argument for argument in documented if argument not in parameters]
        if stale:
            found.append("%s: Args names %s, which it does not take" % (name, stale))
        if ("Returns" in sections or "Yields" in sections) and not returns_a_value(node):
            found.append("%s: documents a return value but never returns one" % name)
    return found


# How many lines the comment block directly above a definition runs to
def comment_lines_above(node, lines):
    first = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    count = 0
    while first - 2 - count >= 0 and lines[first - 2 - count].strip().startswith("#"):
        count += 1
    return count


# How many lines a docstring's description runs to, before any Google-style section
def description_lines(docstring):
    described = []
    for line in docstring.splitlines():
        if SECTION_HEADER.match(line.strip()):
            break
        described.append(line)
    while described and not described[-1].strip():
        described.pop()
    return len(described)


# "name: N lines" for each public definition described at more than max_lines
def overlong(tree, source, max_lines):
    lines = source.splitlines()
    found = []
    for name, node in public_definitions(tree):
        if is_self_describing(node.name):
            continue
        docstring = ast.get_docstring(node)
        length = max(comment_lines_above(node, lines), description_lines(docstring) if docstring else 0)
        if length > max_lines:
            found.append("%s: %d lines, at most %d" % (name, length, max_lines))
    return found


# Words that carry no meaning of their own in a description
FILLER_WORDS = {"a", "an", "the", "of", "for", "to", "and", "or", "in", "on", "it", "its", "this", "that", "with",
                "by", "from", "as", "be", "is", "are", "function", "method", "class", "helper", "here"}


# The meaningful words of some text, lower case and without a plural s, so
# "Gets the settings" and get_settings compare equal
def content_words(text):
    words = set(re.findall(r"[a-z0-9]+", text.lower().replace("_", " "))) - FILLER_WORDS
    return {word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word for word in words}


# The description of a definition: its comment block, else its docstring before any section
def description_of(node, lines):
    count = comment_lines_above(node, lines)
    if count:
        first = node.decorator_list[0].lineno if node.decorator_list else node.lineno
        return " ".join(line.strip().lstrip("#") for line in lines[first - 1 - count:first - 1])
    docstring = ast.get_docstring(node) or ""
    return " ".join(docstring.splitlines()[:description_lines(docstring)]) if docstring else ""


# "name: description" for each description that only says the name again
def paraphrases(tree, source):
    lines = source.splitlines()
    found = []
    for name, node in public_definitions(tree):
        description = description_of(node, lines)
        words = content_words(description)
        if description and words <= content_words(node.name):
            found.append("%s: %r says no more than its name" % (name, description.strip()))
    return found


# A module docstring, which docstring style asks every library module to have
def has_module_docstring(tree):
    return bool(ast.get_docstring(tree))
