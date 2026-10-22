# Imports
import os

# Local imports
from pytest_testrex import lint, settings


def shipped_rcfile(tmp_path):
    return settings.from_table({}, str(tmp_path)).rcfile


def test_every_conftest_directory_is_an_import_root(tmp_path):
    files = [str(tmp_path / "unit" / "conftest.py"), str(tmp_path / "unit" / "test_a.py"), str(tmp_path / "unit" / "sub" / "conftest.py")]

    assert lint.import_roots(str(tmp_path), files) == sorted(
        [str(tmp_path), str(tmp_path / "unit"), str(tmp_path / "unit" / "sub")])


def test_the_targets_are_the_suites_and_the_shared_files_at_the_top(write_file, tmp_path):
    write_file("conftest.py")
    write_file("fakes.py")
    write_file("README.md")

    assert lint.pylint_targets(str(tmp_path), ["unit/test_a.py"]) == [
        "unit/test_a.py", os.path.join(str(tmp_path), "conftest.py"), os.path.join(str(tmp_path), "fakes.py")]


def test_pylint_reports_a_finding_it_is_given(write_file, tmp_path):
    sample = write_file("sample.py", "import os\n")

    result = lint.run_pylint(shipped_rcfile(tmp_path), str(tmp_path), [str(tmp_path)], str(sample))

    assert result.returncode != 0
    assert "unused-import" in result.stdout


def test_the_shipped_rcfile_allows_pytest_idioms(write_file, tmp_path):
    sample = write_file("test_sample.py", """
        import pytest


        @pytest.fixture
        def server(tmp_path):
            return tmp_path


        def test_x(server, monkeypatch):
            assert server
        """)

    result = lint.run_pylint(shipped_rcfile(tmp_path), str(tmp_path), [str(tmp_path)], str(sample))

    assert result.returncode == 0, result.stdout


def test_only_the_named_rules_run(write_file, tmp_path):
    sample = write_file("sample.py", "import os\nwith open('x') as handle:\n    handle.read()\n")

    result = lint.run_pylint(shipped_rcfile(tmp_path), str(tmp_path), [], *lint.only_rules(["unspecified-encoding"]), str(sample))

    assert result.returncode != 0
    assert "unspecified-encoding" in result.stdout
    assert "unused-import" not in result.stdout
