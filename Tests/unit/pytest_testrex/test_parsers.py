"""The tree-sitter parsers for the languages read beside Python."""

import importlib

import pytest

from pytest_testrex import parsers


@pytest.fixture
def fresh_parsers():
    parsers.get_parser.cache_clear()
    yield
    parsers.get_parser.cache_clear()


def test_a_missing_grammar_says_which_extra_installs_it(monkeypatch, fresh_parsers):
    real_import = importlib.import_module

    def import_module(name):
        if name == "tree_sitter_lua":
            raise ImportError(name)
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", import_module)
    with pytest.raises(parsers.ParserMissing, match=r'needs tree-sitter-lua.*pytest-testrex\[lua\]') as caught:
        parsers.get_parser("lua")
    assert isinstance(caught.value.__cause__, ImportError)


@pytest.mark.parametrize("language", sorted(parsers.GRAMMARS))
def test_each_grammar_loads_once(language, fresh_parsers):
    parser = parsers.get_parser(language)
    assert parsers.get_parser(language) is parser


def test_parse_returns_the_root():
    root = parsers.parse("javascript", "let a = 1;\n")
    assert root.type == "program"
    assert [child.type for child in root.named_children] == ["lexical_declaration"]


def test_parse_names_the_line_of_the_first_error():
    with pytest.raises(ValueError, match=r"^tree-sitter-javascript cannot parse it \(near line 3\)$"):
        parsers.parse("javascript", "a();\nb();\nif (\n")


def test_parse_raises_the_error_it_is_given():
    class Unreadable(Exception):
        pass

    with pytest.raises(Unreadable, match="tree-sitter-lua cannot parse it"):
        parsers.parse("lua", "local = = 1\n", Unreadable)


def test_first_error_is_the_deepest_node_holding_it():
    root = parsers.get_parser("javascript").parse(b"f(1, ));\n").root_node
    node = parsers.first_error(root)
    assert node.has_error and not any(child.has_error for child in node.children)
