"""tree-sitter parsers for the languages TestRex reads beside Python.

Each grammar ships as its own package behind an extra, so a repo installs only
the languages it uses; asking for a missing one raises ParserMissing naming
the extra that brings it.
"""

import functools
import importlib

# {language: (grammar module, the extra that installs it)}
GRAMMARS = {
    "bash": ("tree_sitter_bash", "shell"),
    "javascript": ("tree_sitter_javascript", "js"),
    "lua": ("tree_sitter_lua", "lua"),
}


class ParserMissing(Exception):
    """A grammar, or tree-sitter itself, is not installed."""


@functools.lru_cache(maxsize=None)
def get_parser(language):
    """The tree-sitter parser for a language, or ParserMissing saying how to install it."""
    module_name, extra = GRAMMARS[language]
    try:
        grammar = importlib.import_module(module_name)
        from tree_sitter import Language, Parser
    except ImportError as error:
        raise ParserMissing(
            f"reading {language} needs {module_name.replace('_', '-')}; install it with: "
            f"pip install \"pytest-testrex[{extra}]\", or add tree-sitter and "
            f"{module_name.replace('_', '-')} to the hash-locked test requirements") from error
    return Parser(Language(grammar.language()))


def first_error(node):
    """The deepest node holding the first syntax error under a node that has one."""
    for child in node.children:
        if child.has_error:
            return first_error(child)
    return node


def parse(language, source, error=ValueError):
    """The syntax tree's root for source, raising error (with the line) when it doesn't parse."""
    root = get_parser(language).parse(source.encode()).root_node
    if root.has_error:
        raise error(f"tree-sitter-{language} cannot parse it (near line {first_error(root).start_point[0] + 1})")
    return root
