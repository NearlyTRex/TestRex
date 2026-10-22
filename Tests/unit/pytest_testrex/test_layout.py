# Imports
import os

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
