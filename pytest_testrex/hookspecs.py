# Third-party imports
import pytest

# Hooks a repository's conftest.py can implement


@pytest.hookspec
def pytest_testrex_requirement_checkers(config):
    """Return {marker name: check} for requirement markers beyond requires_binary.

    Each check takes the names a test's markers list and returns a label for
    each one that is unavailable, such as "XorrISO (JoyBox tool)". A test with
    any unavailable name is skipped while collecting, before its fixtures run.
    Every marker in [tool.testrex] requirement_markers needs a check.
    """
