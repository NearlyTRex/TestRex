# Third-party imports
import pytest

# Local imports
from pytest_testrex import requirements

SHELL_FIXTURES = {"shell_sandbox": {"bash", "unshare"}, "shell_traced_env": {"bash"}}
MARKERS = ("requires_binary", "requires_tool")


def test_markers_are_read_at_module_class_and_test_level(parse_sample):
    tree = parse_sample("""
        import pytest
        pytestmark = pytest.mark.requires_binary('git')
        @pytest.mark.requires_binary('docker')
        class TestA:
            @pytest.mark.requires_binary('gpg')
            def test_one(self): pass
            def test_two(self): pass
            def helper(self): pass
        def test_three(): pass
        def helper(): pass
        """)

    assert {name: declared for name, _, declared in requirements.declared_per_test(tree)} == {
        "TestA.test_one": {"git", "docker", "gpg"}, "TestA.test_two": {"git", "docker"}, "test_three": {"git"}}
    assert requirements.declared_anywhere(tree) == {"git", "docker", "gpg"}


def test_other_markers_are_read_apart_from_binaries(parse_sample):
    tree = parse_sample("import pytest\npytestmark = [pytest.mark.requires_tool('XorrISO'), pytest.mark.slow]\n")

    assert requirements.declared_anywhere(tree, "requires_tool") == {"XorrISO"}
    assert requirements.declared_anywhere(tree) == set()


def test_either_of_two_programs_satisfies_a_need():
    assert requirements.accepted({"xorriso|mkisofs", "gpg"}) == {"xorriso", "mkisofs", "gpg"}


def test_a_program_fixture_is_found_through_other_fixtures(parse_sample):
    tree = parse_sample("""
        import pytest
        @pytest.fixture
        def server(shell_sandbox, wired):
            return shell_sandbox
        @pytest.fixture
        def wired(server, tmp_path):
            return server
        """)
    fixtures = requirements.fixture_parameters([tree])

    assert requirements.binaries_needed(["wired"], fixtures, SHELL_FIXTURES) == {"bash", "unshare"}
    assert requirements.binaries_needed(["tmp_path"], fixtures, SHELL_FIXTURES) == set()


def test_a_nearer_fixture_replaces_a_conftest_one(parse_sample):
    near = parse_sample("import pytest\n@pytest.fixture\ndef server(tmp_path):\n    return tmp_path\n")
    far = parse_sample("import pytest\n@pytest.fixture\ndef server(shell_sandbox):\n    return 1\n", "conftest.py")

    assert requirements.binaries_needed(["server"], requirements.fixture_parameters([near, far]), SHELL_FIXTURES) == set()


def test_conftests_are_visible_from_the_test_up_to_the_tests_dir(write_file, tmp_path):
    write_file("conftest.py")
    top = write_file("Tests/conftest.py")
    near = write_file("Tests/unit/conftest.py")
    test = write_file("Tests/unit/sub/test_x.py")

    assert requirements.visible_conftests(str(test), str(tmp_path / "Tests")) == [str(near), str(top)]


def test_undeclared_fixture_programs_are_reported_per_test(parse_sample):
    conftest = parse_sample("import pytest\n@pytest.fixture\ndef server(shell_sandbox):\n    return 1\n", "conftest.py")
    tree = parse_sample("""
        import pytest
        def test_bare(server): pass
        @pytest.mark.requires_binary('bash', 'unshare|other')
        def test_declared(server): pass
        def test_plain(tmp_path): pass
        """)

    assert requirements.undeclared_fixture_programs(tree, [conftest], SHELL_FIXTURES) == ["test_bare needs ['bash', 'unshare']"]


@pytest.mark.parametrize("source, lines", [
    ("def test_a(requires_tool):\n    pass\n", [1]),
    ("import shutil, pytest\ndef test_a():\n    if not shutil.which('git'):\n        pytest.skip('no git')\n", [3]),
    ("from shutil import which\ndef test_a():\n    if not which('git'):\n        pytest.skip('no git')\n", [3]),
    ("import shutil\ndef test_a():\n    if shutil.which('git'):\n        pass\n", []),
    ("import shutil, pytest\nHAS = shutil.which('docker') is not None\n@pytest.mark.skipif(not HAS, reason = 'x')\ndef test_a(): pass\n", [3]),
    ("import pytest\n@pytest.mark.skipif(IS_WINDOWS, reason = 'x')\ndef test_a(): pass\n", []),
    ("import pytest\n@pytest.mark.skipif(reason = 'x')\ndef test_a(): pass\n", []),
    ("import pytest\ndef test_a(cmd):\n    if not cmd.which('unzip'):\n        pytest.skip('not here')\n", []),
    ("import pytest\ndef test_a():\n    if not lookup()('unzip'):\n        pytest.skip('not here')\n", []),
])
def test_imperative_gates_are_found(parse_sample, source, lines):
    assert requirements.imperative_gates(parse_sample(source), MARKERS) == lines


@pytest.mark.parametrize("source, lines", [
    ("import pytest\npytestmark = pytest.mark.requires_binary('git')\n", []),
    ("import pytest\npytestmark = pytest.mark.requires_binary()\n", [2]),
    ("import pytest\npytestmark = pytest.mark.requires_tool(NAME)\n", [2]),
    ("import pytest\npytestmark = pytest.mark.requires_binary('git', reason = 'x')\n", [2]),
])
def test_requirement_markers_must_name_programs_literally(parse_sample, source, lines):
    assert requirements.non_literal_markers(parse_sample(source), MARKERS) == lines


@pytest.mark.parametrize("source, runs", [
    ("import subprocess, sys\ndef test_a():\n    subprocess.run([sys.executable, '-m', 'x'])\n", True),
    ("import subprocess\ndef test_a(python):\n    subprocess.run([python, '-m', 'x'])\n", False),
    ("import subprocess\ndef test_a(args):\n    subprocess.run(args)\n", False),
    ("import sys\ndef test_a():\n    assert sys.executable\n", False),
])
def test_a_subprocess_of_this_interpreter_is_recognised(parse_sample, source, runs):
    assert requirements.runs_the_interpreter(parse_sample(source)) is runs


def test_only_literal_subprocess_programs_are_collected(parse_sample):
    tree = parse_sample("""
        import subprocess
        def test_a(args):
            subprocess.run(['git', 'init'])
            subprocess.check_output(['docker', *args])
            subprocess.run([])
            subprocess.run([args[0]])
            subprocess.run(args)
            subprocess.getoutput(['ls'])
            other.run(['tilt'])
            run(['make'])
        """)

    assert requirements.subprocess_binaries(tree) == {"git", "docker"}


@pytest.mark.parametrize("source, declares", [
    ("import pytest\npytestmark = pytest.mark.requires_binary('git')\n", True),
    ("import pytest\npytestmark = pytest.mark.requires_tool('XorrISO')\n", True),
    ("import subprocess, sys\ndef test_a():\n    subprocess.run([sys.executable])\n", True),
    ("def test_a():\n    assert True\n", False),
])
def test_a_file_declares_a_program_through_any_marker_or_the_interpreter(parse_sample, source, declares):
    assert requirements.declares_a_program(parse_sample(source), MARKERS) is declares
