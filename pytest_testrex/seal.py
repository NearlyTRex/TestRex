# Imports
import os
import shlex
import subprocess

###########################################################
# The seal
#
# Applied when the session starts, before any test module is imported, so it
# covers collection as well as the tests: a module that builds something at
# import time may start programs before any fixture runs. From then on the
# sealed programs, such as sudo, a password manager or ssh, are refused
# whether started through subprocess, os.system or os.exec*.
###########################################################

EXEC_FUNCTIONS = ["execv", "execve", "execvp", "execvpe", "execl", "execlp"]

_unsealed = {}


class SealedProgramError(RuntimeError):
    pass


def get_program_name(args, shell = False):
    if isinstance(args, (str, bytes)):
        text = args.decode() if isinstance(args, bytes) else args
        tokens = shlex.split(text) if text.strip() else []
    else:
        tokens = [os.fspath(arg) if isinstance(arg, os.PathLike) else str(arg) for arg in args]
    for token in tokens:
        # Leading VAR=value assignments in a shell string are not the program
        if shell and "=" in token and not token.startswith(("/", ".")):
            continue
        return os.path.basename(token)
    return ""


def check_sealed(programs, args, shell = False):
    program = get_program_name(args, shell = shell)
    if program in programs:
        raise SealedProgramError(
            "tests may not run %s for real; replace whatever runs it with a fake" % program)


def is_sealed():
    return bool(_unsealed)


# Whether this call applied the seal; one already in place is left as it is
def seal(programs):
    if is_sealed():
        return False
    original_popen = subprocess.Popen

    class SealedPopen(original_popen):
        def __init__(self, args, *rest, **kwargs):
            check_sealed(programs, args, shell = kwargs.get("shell", False))
            super().__init__(args, *rest, **kwargs)

    _unsealed["Popen"] = original_popen
    _unsealed["system"] = os.system
    subprocess.Popen = SealedPopen

    def sealed_system(command):
        check_sealed(programs, command, shell = True)
        return _unsealed["system"](command)
    os.system = sealed_system

    for name in EXEC_FUNCTIONS:
        original = getattr(os, name)
        _unsealed[name] = original

        def sealed_exec(path, *rest, original = original):
            check_sealed(programs, [path])
            return original(path, *rest)
        setattr(os, name, sealed_exec)
    return True


def unseal():
    if "Popen" in _unsealed:
        subprocess.Popen = _unsealed.pop("Popen")
    for name, original in list(_unsealed.items()):
        setattr(os, name, original)
    _unsealed.clear()
