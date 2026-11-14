# Imports
import os

# Third-party imports
import pytest

# Local imports
from pytest_testrex import layout


def relative_to(root, paths):
    return [os.path.relpath(path, str(root)) for path in paths]


def test_split_packages_are_found_at_any_depth_but_not_in_caches_hidden_or_data(write_file, tmp_path):
    write_file("unit/Shared/test_foo/test_a.py")
    write_file("unit/Shared/helpers/x.py")
    write_file("unit/Shared/__pycache__/test_cached/y.py")
    write_file("unit/.hidden/test_hidden/z.py")
    write_file("unit/data/test_sample/z.py")

    found = layout.discover_split_packages([str(tmp_path / "unit")], [str(tmp_path / "unit" / "data")])

    assert relative_to(tmp_path, found) == [os.path.join("unit", "Shared", "test_foo")]


def test_misnamed_test_files_are_flagged(write_file, tmp_path):
    write_file("test_foo/conftest.py", "def test_in_conftest(): pass\n")
    write_file("test_foo/test_ok.py", "def test_x(): pass\n")
    write_file("test_foo/foo_tests.py", "def test_y(): pass\n")
    write_file("test_foo/cases.py", "class TestCases:\n    pass\n")
    write_file("test_foo/foo_helpers.py", "def build(): pass\n")
    (tmp_path / "test_foo" / "test_dir.py").mkdir()

    package = str(tmp_path / "test_foo")

    assert layout.uncollected_test_files(package) == ["cases.py", "foo_tests.py"]
    assert layout.python_files(package) == ["cases.py", "conftest.py", "foo_helpers.py", "foo_tests.py", "test_ok.py"]


def test_test_module_names_start_with_test_and_end_with_py():
    assert layout.is_test_module_name("test_a.py")
    assert not layout.is_test_module_name("a_test.py")
    assert not layout.is_test_module_name("test_a.txt")


def test_a_split_package_maps_to_a_module_a_script_or_a_package(tmp_path):
    suite_dir = str(tmp_path / "unit")
    package = os.path.join(suite_dir, "Shared", "joybox", "test_amazon")
    base = os.path.join(str(tmp_path), "Shared", "joybox", "amazon")

    assert layout.source_candidates(package, suite_dir, str(tmp_path), (".py", ".sh")) == [base + ".py", base + ".sh", base]


def test_mirror_discovery_skips_split_packages_and_data_directories(write_file, tmp_path):
    for path in ("Shared/joybox/stores/a.py", "Shared/test_helm/sub/b.py", "meta/c.py", "Shared/fixtures/data.txt"):
        write_file(path)

    found = relative_to(tmp_path, layout.discover_mirror_directories([str(tmp_path)]))

    assert found == ["Shared", os.path.join("Shared", "joybox"), os.path.join("Shared", "joybox", "stores"), "meta"]


def test_directories_holding_only_script_tests_mirror_too(write_file, tmp_path):
    write_file("lib/greet.test.js")
    write_file("spec/greet_spec.lua")

    assert layout.discover_mirror_directories([str(tmp_path)]) == []
    assert relative_to(tmp_path, layout.discover_mirror_directories([str(tmp_path)], (), ["*.test.js"])) == ["lib"]


@pytest.mark.parametrize("name, patterns, stems", [
    ("greet.test.js", ["*.test.js", "*.test.mjs"], ["greet"]),
    ("greet_spec.lua", ["*_spec.lua"], ["greet"]),
    ("_spec.lua", ["*_spec.lua"], []),
    ("greet.test.js", ["*.*.js", "greet.test.js"], []),
])
def test_a_script_test_is_a_test_of_what_its_pattern_star_matched(name, patterns, stems):
    assert layout.script_stems(name, patterns) == stems


def test_a_script_test_maps_to_a_source_or_a_directory_of_its_stem(tmp_path):
    suite_dir = str(tmp_path / "Tests" / "integration")
    path = os.path.join(suite_dir, "lib", "greet.test.js")
    base = os.path.join(str(tmp_path), "lib", "greet")

    assert layout.script_source_candidates(path, suite_dir, str(tmp_path), ["*.test.js"], (".js", ".mjs")) == [
        base + ".js", base + ".mjs", base]


def test_the_suite_a_path_is_in_is_found(tmp_path):
    suites = [str(tmp_path / "unit"), str(tmp_path / "unit2")]

    assert layout.suite_of(str(tmp_path / "unit2" / "a"), suites) == suites[1]


def test_a_hidden_directory_is_mirrored_without_its_dot(tmp_path):
    suite_dir = str(tmp_path / "unit")

    assert layout.mirror_targets(os.path.join(suite_dir, "githooks"), suite_dir, str(tmp_path)) == [
        os.path.join(str(tmp_path), "githooks"), os.path.join(str(tmp_path), ".githooks")]


def test_a_single_file_twin_is_found(write_file, tmp_path):
    package = tmp_path / "test_foo"
    package.mkdir()
    assert layout.single_file_twin(str(package)) is None

    write_file("test_foo.py")
    assert layout.single_file_twin(str(package)) == str(tmp_path / "test_foo.py")


def test_meta_directories_cover_what_is_under_them(tmp_path):
    tests_dir = str(tmp_path)
    meta = [os.path.join("unit", "meta")]

    assert layout.is_meta(os.path.join(tests_dir, "unit", "meta"), tests_dir, meta)
    assert layout.is_meta(os.path.join(tests_dir, "unit", "meta", "deep"), tests_dir, meta)
    assert not layout.is_meta(os.path.join(tests_dir, "unit", "metadata"), tests_dir, meta)


def test_a_source_stem_drops_an_ordering_number_and_turns_dashes_into_underscores():
    assert layout.source_stem("10-create-resources.py") == "create_resources"
    assert layout.source_stem("setup.sh") == "setup"
    assert layout.source_stem("2_post_upgrade.py") == "post_upgrade"


def test_source_modules_are_found_under_targets_without_init_files_caches_or_tests(write_file, tmp_path):
    write_file("pkg/__init__.py")
    write_file("pkg/a.py")
    write_file("pkg/sub/b.sh")
    write_file("pkg/notes.txt")
    write_file("pkg/__pycache__/c.py")
    write_file("pkg/.hidden/d.py")
    write_file("pkg/Tests/e.py")
    write_file("tool.py")

    found = layout.discover_source_modules(
        str(tmp_path), [str(tmp_path / "pkg"), str(tmp_path / "tool.py"), str(tmp_path / "pkg" / "a.py")],
        (".py", ".sh"), str(tmp_path / "pkg" / "Tests"))

    assert found == [os.path.join("pkg", "a.py"), os.path.join("pkg", "sub", "b.sh"), "tool.py"]


def test_non_source_directories_are_hidden_caches_virtualenvs_and_metadata():
    assert all(layout.is_non_source_directory(name) for name in (".git", "__pycache__", "venv", "x.egg-info", "build"))
    assert not layout.is_non_source_directory("pkg")


def test_the_tests_for_a_source_file_may_sit_in_any_suite_as_a_module_or_a_package(tmp_path):
    suites = [str(tmp_path / "unit"), str(tmp_path / "integration")]

    found = layout.mirrored_tests(os.path.join("scripts", "10-do-thing.sh"), suites)

    assert found == [
        os.path.join(suites[0], "scripts", "test_do_thing.py"), os.path.join(suites[0], "scripts", "test_do_thing"),
        os.path.join(suites[1], "scripts", "test_do_thing.py"), os.path.join(suites[1], "scripts", "test_do_thing")]


def test_a_script_may_be_tested_by_a_standalone_test_file_named_by_a_pattern(tmp_path):
    suite = str(tmp_path / "integration")

    found = layout.mirrored_tests(os.path.join("lib", "greet.js"), [suite], ["*.test.js", "test-*-*.js"])

    assert found == [os.path.join(suite, "lib", name) for name in ("test_greet.py", "test_greet", "greet.test.js")]
