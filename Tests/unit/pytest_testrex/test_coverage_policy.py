# Imports
import os

# Third-party imports
import pytest

# Local imports
from pytest_testrex import coverage_policy


def test_measured_files_leave_out_tests_hidden_directories_and_virtualenvs(write_file, tmp_path):
    write_file("pkg/a.py")
    write_file("pkg/b.txt")
    write_file("Tests/unit/test_a.py")
    write_file(".venv/lib/c.py")
    write_file("venv/lib/d.py")
    write_file("pkg.egg-info/e.py")
    write_file("build/f.py")

    found = coverage_policy.measured_files(str(tmp_path), str(tmp_path / "Tests"))

    assert found == [str(tmp_path / "pkg" / "a.py")]


def test_every_no_cover_pragma_is_reported_with_its_line(write_file, tmp_path):
    path = write_file("pkg/a.py", "x = 1\ny = 2  # pragma: no cover\nz = 3  #pragma:no  cover\n")
    clean = write_file("pkg/b.py", "x = 1\n")

    found = coverage_policy.pragma_lines([str(path), str(clean)], str(tmp_path))

    assert found == [os.path.join("pkg", "a.py") + ":2", os.path.join("pkg", "a.py") + ":3"]


def test_ini_values_are_read_from_each_file_that_sets_them(write_file, tmp_path):
    write_file(".coveragerc", "[run]\nomit =\n    tests/*\n    venv/*\n")
    write_file("setup.cfg", "[coverage:run]\nomit = scripts/*\n")
    write_file("tox.ini", "[testenv]\ndeps = pytest\n")

    assert coverage_policy.ini_values(str(tmp_path), "run", "omit") == ["tests/*", "venv/*", "scripts/*"]


def test_a_pyproject_larger_than_the_limit_is_refused(write_file, tmp_path, monkeypatch):
    write_file("pyproject.toml", "[tool.coverage.run]\nomit = []\n")
    monkeypatch.setattr(coverage_policy, "MAX_TOML_BYTES", 10)

    with pytest.raises(ValueError, match = "larger than 10 bytes"):
        coverage_policy.toml_values(str(tmp_path), "run", "omit")


def test_toml_values_accept_a_list_or_a_single_string(write_file, tmp_path):
    write_file("pyproject.toml", '[tool.coverage.run]\nomit = ["a/*", "b/*"]\n[tool.coverage.report]\nexclude_also = "pass"\n')

    assert coverage_policy.toml_values(str(tmp_path), "run", "omit") == ["a/*", "b/*"]
    assert coverage_policy.toml_values(str(tmp_path), "report", "exclude_also") == ["pass"]
    assert coverage_policy.toml_values(str(tmp_path), "run", "missing") == []


def test_a_repository_without_a_pyproject_declares_nothing_there(tmp_path):
    assert coverage_policy.toml_values(str(tmp_path), "run", "omit") == []


def test_declared_exclusions_gather_omits_and_both_exclusion_options(write_file, tmp_path):
    write_file(".coveragerc", "[run]\nomit = tests/*\n[report]\nexclude_lines = pragma: no cover\n")
    write_file(
        "pyproject.toml", '[tool.coverage.run]\nomit = ["x/*"]\n[tool.coverage.report]\nexclude_also = ["raise NotImplementedError"]\n')

    omit, exclude = coverage_policy.declared_exclusions(str(tmp_path))

    assert omit == ["tests/*", "x/*"]
    assert exclude == ["pragma: no cover", "raise NotImplementedError"]


def test_only_patterns_the_repository_has_not_allowed_are_disallowed():
    assert coverage_policy.disallowed(["tests/*", "x/*", "x/*"], ["tests/*"]) == ["x/*"]
    assert coverage_policy.disallowed(["tests/*"], ["tests/*"]) == []
