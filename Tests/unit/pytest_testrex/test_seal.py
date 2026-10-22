# Imports
import os
import pathlib
import subprocess

# Third-party imports
import pytest

# Local imports
from pytest_testrex import seal

PROGRAMS = frozenset({"sudo", "op"})


@pytest.mark.parametrize("args, shell, program", [
    (["sudo", "ls"], False, "sudo"),
    (["/usr/bin/sudo"], False, "sudo"),
    ([pathlib.Path("/usr/bin/op"), "read"], False, "op"),
    ("sudo ls", False, "sudo"),
    (b"op read", False, "op"),
    ("FOO=1 BAR=2 sudo ls", True, "sudo"),
    ("./run=1 x", True, "run=1"),
    ("   ", True, ""),
    ([], False, ""),
])
def test_the_program_is_read_from_any_form_of_command(args, shell, program):
    assert seal.get_program_name(args, shell = shell) == program


def test_a_sealed_program_is_refused_and_others_pass():
    with pytest.raises(seal.SealedProgramError, match = "may not run sudo"):
        seal.check_sealed(PROGRAMS, ["sudo", "true"])

    assert seal.check_sealed(PROGRAMS, ["true"]) is None


@pytest.fixture
def fresh_seal():
    # The session is already sealed; lift it for this test and put it back after
    saved = dict(seal._unsealed)
    current = {name: getattr(os, name) for name in seal.EXEC_FUNCTIONS + ["system"]}
    current_popen = subprocess.Popen
    seal.unseal()
    yield
    seal.unseal()
    for name, value in current.items():
        setattr(os, name, value)
    subprocess.Popen = current_popen
    seal._unsealed.update(saved)


@pytest.mark.usefixtures("fresh_seal")
def test_sealing_patches_every_way_to_start_a_program(monkeypatch):
    started = []
    monkeypatch.setattr(seal, "EXEC_FUNCTIONS", ["execv"])
    monkeypatch.setattr(os, "execv", lambda path, args: started.append(path))
    monkeypatch.setattr(os, "system", lambda command: started.append(command) or 0)

    assert seal.seal(PROGRAMS)
    assert not seal.seal(PROGRAMS)

    refused = ["sudo", "true"]
    with pytest.raises(seal.SealedProgramError):
        subprocess.Popen(refused)
    with pytest.raises(seal.SealedProgramError):
        os.system("sudo true")
    with pytest.raises(seal.SealedProgramError):
        os.execv("/usr/bin/op", ["op"])
    assert os.system("echo hi") == 0
    os.execv("/bin/true", ["true"])
    assert started == ["echo hi", "/bin/true"]


@pytest.mark.usefixtures("fresh_seal")
def test_unsealing_restores_the_originals():
    original_popen, original_system = subprocess.Popen, os.system
    seal.seal(PROGRAMS)

    seal.unseal()

    assert subprocess.Popen is original_popen
    assert os.system is original_system
    assert not seal.is_sealed()


@pytest.mark.requires_binary("true")
@pytest.mark.usefixtures("fresh_seal")
def test_a_sealed_popen_still_runs_what_is_allowed():
    seal.seal(PROGRAMS)

    result = subprocess.run(["true"], check = False)

    assert result.returncode == 0
