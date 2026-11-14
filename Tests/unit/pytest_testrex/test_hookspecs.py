# Imports
import inspect

# Third-party imports
import pluggy
import pytest

# Local imports
from pytest_testrex import hookspecs


def test_the_requirement_checker_hook_is_a_pytest_hookspec_taking_the_config():
    manager = pluggy.PluginManager("pytest")
    manager.add_hookspecs(hookspecs)

    assert list(inspect.signature(hookspecs.pytest_testrex_requirement_checkers).parameters) == ["config"]
    assert manager.hook.pytest_testrex_requirement_checkers.spec.argnames == ("config",)


def test_the_spec_is_never_an_implementation():
    with pytest.raises(NotImplementedError):
        hookspecs.pytest_testrex_requirement_checkers(None)
