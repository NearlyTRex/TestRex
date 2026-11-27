# Imports
import os

# Third-party imports
import pytest

# Local imports
from pytest_testrex import imports, library, settings


###########################################################
# Import cycles
#
# A cycle is counted as Python runs the imports: a submodule import runs its
# packages' __init__ files first, so a loop through one counts.
###########################################################

def cycles_in(write_file, tmp_path, files):
    for relative, text in files.items():
        write_file(relative, text)
    found = imports.cycles(library.discover_library_files([str(tmp_path / "src")]))
    return [(os.path.relpath(path, tmp_path), text) for path, text in found]


def test_a_module_is_named_by_its_path_below_its_top_package(write_file, tmp_path):
    write_file("src/pkg/__init__.py")
    write_file("src/pkg/sub/__init__.py")

    assert imports.module_name(str(write_file("src/pkg/sub/mod.py"))) == "pkg.sub.mod"
    assert imports.module_name(str(tmp_path / "src/pkg/sub/__init__.py")) == "pkg.sub"
    assert imports.module_name(str(write_file("src/tool.py"))) == "tool"


def test_two_modules_importing_each_other_are_a_cycle(write_file, tmp_path):
    found = cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "from pkg import b\n",
        "src/pkg/b.py": "import pkg.a\n",
    })

    assert found == [(os.path.join("src", "pkg", "a.py"), "import cycle among 2 modules: pkg.a -> pkg.b -> pkg.a")]


def test_a_loop_through_a_package_init_is_a_cycle(write_file, tmp_path):
    # base imports one store, which runs the stores package, which imports every store, which imports base
    found = cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/base.py": "from pkg.stores import lookups\n",
        "src/pkg/stores/__init__.py": "from pkg.stores import shop, lookups\n",
        "src/pkg/stores/lookups.py": "",
        "src/pkg/stores/shop.py": "from pkg import base\n",
    })

    assert found == [(os.path.join("src", "pkg", "base.py"),
                      "import cycle among 3 modules: pkg.base -> pkg.stores -> pkg.stores.shop -> pkg.base")]


def test_reaching_a_sibling_through_its_own_package_is_no_cycle(write_file, tmp_path):
    assert cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "from pkg import a, b\n",
        "src/pkg/a.py": "from pkg import b\nimport pkg.b\n",
        "src/pkg/b.py": "",
    }) == []


def test_taking_a_name_from_the_importing_package_is_a_cycle(write_file, tmp_path):
    found = cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "from pkg import a\nVALUE = 1\n",
        "src/pkg/a.py": "from pkg import VALUE\n",
    })

    assert [text for _, text in found] == ["import cycle among 2 modules: pkg -> pkg.a -> pkg"]


def test_relative_imports_resolve_against_the_package(write_file, tmp_path):
    found = cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/sub/__init__.py": "",
        "src/pkg/sub/a.py": "from . import b\n",
        "src/pkg/sub/b.py": "from ..sub import a\n",
        "src/pkg/c.py": "from .sub.a import thing\n",
    })

    assert [text for _, text in found] == ["import cycle among 2 modules: pkg.sub.a -> pkg.sub.b -> pkg.sub.a"]


@pytest.mark.parametrize("deferred", [
    "def load():\n    from pkg import a\n",
    "async def load():\n    import pkg.a\n",
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pkg import a\n",
    "import typing\nif typing.TYPE_CHECKING:\n    from pkg import a\n",
])
def test_an_import_that_does_not_run_at_import_time_is_no_edge(write_file, tmp_path, deferred):
    assert cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "from pkg import b\n",
        "src/pkg/b.py": deferred,
    }) == []


@pytest.mark.parametrize("executed", [
    "try:\n    from pkg import a\nexcept ImportError:\n    a = None\n",
    "try:\n    pass\nexcept ImportError:\n    from pkg import a\n",
    "class Holder:\n    from pkg import a\n",
    "if True:\n    pass\nelse:\n    from pkg import a\n",
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\nelse:\n    from pkg import a\n",
    "match 1:\n    case 1:\n        from pkg import a\n",
])
def test_an_import_run_at_import_time_is_an_edge_wherever_it_sits(write_file, tmp_path, executed):
    found = cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "from pkg import b\n",
        "src/pkg/b.py": executed,
    })

    assert [text for _, text in found] == ["import cycle among 2 modules: pkg.a -> pkg.b -> pkg.a"]


def test_imports_from_outside_the_library_are_ignored(write_file, tmp_path):
    assert cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "import os\nfrom collections import abc\nfrom pkg import *\n",
        "src/pkg/a.py": "import json\n",
    }) == []


def test_a_loop_is_the_shortest_one_through_the_groups_first_module(write_file, tmp_path):
    found = cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "from pkg import b, d\n",
        "src/pkg/b.py": "from pkg import c\n",
        "src/pkg/c.py": "from pkg import a\n",
        "src/pkg/d.py": "from pkg import a\n",
    })

    assert [text for _, text in found] == ["import cycle among 4 modules: pkg.a -> pkg.d -> pkg.a"]


def test_a_module_reached_twice_in_one_round_is_searched_once(write_file, tmp_path):
    found = cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "from pkg import b, c\n",
        "src/pkg/b.py": "from pkg import d\n",
        "src/pkg/c.py": "from pkg import d\n",
        "src/pkg/d.py": "from pkg import a\n",
    })

    assert [text for _, text in found] == ["import cycle among 4 modules: pkg.a -> pkg.b -> pkg.d -> pkg.a"]


def test_a_group_with_no_loop_back_to_its_start_is_its_own_path():
    graph = {"a": {"b"}, "b": set()}

    assert imports.shortest_loop(graph, ["a", "b"]) == ["a", "b"]


def test_separate_cycles_are_each_reported(write_file, tmp_path):
    found = cycles_in(write_file, tmp_path, {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "from pkg import b\n",
        "src/pkg/b.py": "from pkg import a\n",
        "src/pkg/c.py": "from pkg import d\n",
        "src/pkg/d.py": "from pkg import c\n",
    })

    assert [text.split(": ")[1] for _, text in found] == ["pkg.a -> pkg.b -> pkg.a", "pkg.c -> pkg.d -> pkg.c"]


def test_the_rule_lists_each_cycle_under_its_first_modules_file(write_file, tmp_path):
    write_file("src/pkg/__init__.py")
    write_file("src/pkg/a.py", "from pkg import b\n")
    write_file("src/pkg/b.py", "from pkg import a\n")
    configured = settings.from_table({"library_targets": ["src"], "standards": ["import-cycles"]}, str(tmp_path))

    found = library.findings(configured, "import-cycles", library.discover_library_files([str(tmp_path / "src")]))

    assert found == [f"{os.path.join('src', 'pkg', 'a.py')}: import cycle among 2 modules: pkg.a -> pkg.b -> pkg.a"]
