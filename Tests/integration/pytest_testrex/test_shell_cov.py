"""The shell coverage plugin end to end: pytest runs that trace real bash."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_binary("bash")

# --- end to end ---------------------------------------------------------

def run_pytest(project, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "SHELL_COV_TRACE_DIR", "PYTEST_ADDOPTS")}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *args],
        cwd=project, env=env, capture_output=True, text=True, check=False)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "greet.sh").write_text(textwrap.dedent("""\
        #!/bin/bash
        set -eu
        greet() {
            echo "hello $1"
        }
        if [ "${1:-}" = "loud" ]; then
            greet WORLD
        else
            greet world
        fi
        cat <<EOF
        done
        EOF
        """))
    (tmp_path / "test_greet.py").write_text(textwrap.dedent("""\
        import subprocess

        def test_quiet():
            out = subprocess.run(["bash", "scripts/greet.sh"], capture_output=True, text=True, check=True)
            assert "hello world" in out.stdout

        def test_traced_env(shell_traced_env):
            env = shell_traced_env()
            out = subprocess.run(["bash", "scripts/greet.sh", "loud"], env=env, capture_output=True, text=True,
                                 check=True)
            assert "hello WORLD" in out.stdout
        """))
    return tmp_path


def test_end_to_end_full_coverage(project):
    result = run_pytest(project, "--shell-cov-source", "scripts", "--shell-cov-fail-under", "100")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Total: 100.0%" in result.stdout
    assert "Floor: 100.0% (met)" in result.stdout


def test_end_to_end_missed_branch_fails_the_floor(project):
    (project / "test_greet.py").write_text(textwrap.dedent("""\
        import subprocess

        def test_quiet():
            subprocess.run(["bash", "scripts/greet.sh"], check=True, capture_output=True)
        """))
    result = run_pytest(project, "--shell-cov-source", "scripts", "--shell-cov-fail-under", "100")
    assert result.returncode == 1, result.stdout + result.stderr
    assert os.path.join("scripts", "greet.sh") in result.stdout
    assert "NOT MET" in result.stdout
    assert "passed" in result.stdout


def test_disabled_by_default(project):
    result = run_pytest(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "shell coverage" not in result.stdout


# --- real-world idioms ----------------------------------------------------
#
# The parser is hand-written, so each regression below was a construct it read
# differently from bash. A statement it reports that bash never traces can
# never be marked as run, so it silently caps a script's coverage below 100%.


# The corpus: scripts of real-world shell idioms, each written so that every
# statement runs. They must reach 100% -- anything less means the parser expects
# a statement bash never reports -- and the parser must find as many statements
# as were written: a regression that merges statements would otherwise *raise*
# coverage. When a corpus script changes on purpose, update its count here.
CORPUS_STATEMENTS = {"idioms": 97, "idioms2": 73}
CORPUS_DIR = Path(__file__).resolve().parent / "shell_corpus"


@pytest.mark.parametrize("name", sorted(CORPUS_STATEMENTS))
def test_corpus_script_reaches_full_coverage(tmp_path, name):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / f"{name}.sh").write_text((CORPUS_DIR / f"{name}.corpus").read_text())
    (tmp_path / "test_corpus.py").write_text(textwrap.dedent(f"""\
        import subprocess

        def test_corpus():
            subprocess.run(["bash", "scripts/{name}.sh"], capture_output=True, text=True, check=True)
        """))
    result = run_pytest(tmp_path, "--shell-cov-source", "scripts", "--shell-cov-fail-under", "100")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Total: 100.0%" in result.stdout
    assert f"{CORPUS_STATEMENTS[name]:>5}      0  100.0%" in result.stdout, result.stdout


BRANCH_STATEMENTS = 50 + 14   # statements and branches in shell_corpus/branches.corpus


def test_branch_corpus_reaches_full_branch_coverage(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "branches.sh").write_text((CORPUS_DIR / "branches.corpus").read_text())
    (tmp_path / "test_branches.py").write_text(textwrap.dedent("""\
        import subprocess

        def test_branches():
            subprocess.run(["bash", "scripts/branches.sh"], capture_output=True, text=True, check=True)
        """))
    result = run_pytest(tmp_path, "--shell-cov-source", "scripts", "--shell-cov-branch", "--shell-cov-fail-under", "100")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{BRANCH_STATEMENTS:>5}      0  100.0%" in result.stdout, result.stdout


def test_branch_mode_catches_a_handler_that_statement_mode_cannot(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.sh").write_text(textwrap.dedent("""\
        #!/bin/bash
        build() { true; }
        build || { echo "build failed"; exit 1; }
        """))
    (tmp_path / "test_deploy.py").write_text(textwrap.dedent("""\
        import subprocess

        def test_deploy():
            subprocess.run(["bash", "scripts/deploy.sh"], check=True, capture_output=True)
        """))
    statements = run_pytest(tmp_path, "--shell-cov-source", "scripts", "--shell-cov-fail-under", "100")
    assert statements.returncode == 0, statements.stdout + statements.stderr
    branches = run_pytest(tmp_path, "--shell-cov-source", "scripts", "--shell-cov-branch", "--shell-cov-fail-under", "100")
    assert branches.returncode == 1, branches.stdout + branches.stderr
    assert 'deploy.sh:3  || { echo "build failed"; exit 1; }' in branches.stdout
    assert "NOT MET" in branches.stdout


# The Gradle wrapper (gradlew), vendored into many repos, runs a case as the condition of an if
GRADLEW_CONSTRUCT = """\
for arg do
    if
        case $arg in
          -*) false ;;
          /?*) t=${arg#/} t=/${t%%/*}
               [ -e "$t" ] ;;
          *) false ;;
        esac
    then
        arg=$( cygpath --mixed "$arg" )
    fi
done
"""


def test_end_to_end_an_unparsable_script_is_named_not_a_traceback(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "bad.sh").write_text("cat <<A > f; cat <<B > f\nx\nA\ny\nB\n")
    (tmp_path / "test_nothing.py").write_text("def test_nothing():\n    pass\n")
    result = run_pytest(tmp_path, "--shell-cov-source", "scripts")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Could not measure: scripts/bad.sh: tree-sitter-bash cannot parse it" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def vendored_project(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "vendor").mkdir()
    (tmp_path / "scripts" / "greet.sh").write_text("echo hello\n")
    (tmp_path / "vendor" / "gradlew.sh").write_text(GRADLEW_CONSTRUCT)
    (tmp_path / "test_greet.py").write_text(textwrap.dedent("""\
        import subprocess

        def test_greet():
            subprocess.run(["bash", "scripts/greet.sh"], check=True, capture_output=True)
        """))
    return tmp_path


def test_end_to_end_a_vendored_script_the_parser_cannot_read_is_named_and_can_be_excluded(tmp_path):
    project = vendored_project(tmp_path)
    refused = run_pytest(project, "--shell-cov-source", ".")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "Could not measure: vendor/gradlew.sh: tree-sitter-bash cannot parse it" in refused.stdout
    assert "--shell-cov-exclude" in refused.stdout
    assert "Traceback" not in refused.stdout + refused.stderr

    excluded = run_pytest(project, "--shell-cov-source", ".", "--shell-cov-exclude", "vendor/*",
                          "--shell-cov-fail-under", "100")
    assert excluded.returncode == 0, excluded.stdout + excluded.stderr
    assert "scripts/greet.sh" in excluded.stdout and "gradlew" not in excluded.stdout


def test_end_to_end_missing_tree_sitter_says_how_to_install_it(tmp_path):
    # Shadow the real package with one that cannot be imported, so the plugin sees what
    # a repo that never installed it sees
    blocker = tmp_path / "blocker" / "tree_sitter_bash"
    blocker.mkdir(parents=True)
    (blocker / "__init__.py").write_text("raise ImportError('blocked for this test')\n")
    project = tmp_path / "project"
    project.mkdir()
    (project / "s.sh").write_text("echo a\n")
    (project / "test_nothing.py").write_text("def test_nothing():\n    pass\n")
    env = dict(os.environ, PYTHONPATH=str(tmp_path / "blocker"))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--shell-cov-source", "s.sh"],
        cwd=project, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert "shell coverage needs tree-sitter-bash" in result.stderr
    assert 'pip install "pytest-testrex[shell]"' in result.stderr
    assert "Traceback" not in result.stdout + result.stderr
