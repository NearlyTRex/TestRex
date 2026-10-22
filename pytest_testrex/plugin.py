# Imports
import shutil
import socket

# Third-party imports
import pytest

# Local imports
from pytest_testrex import hookspecs, seal, settings as settings_module, suite

###########################################################
# The plugin
#
# Loaded by pytest from the pytest11 entry point. It does nothing until the
# repository has a [tool.testrex] table; then it registers the markers, seals
# the programs tests may not start, closes outbound network, skips tests whose
# required programs are missing, and parametrizes the meta suite.
###########################################################

SETTINGS_KEY = pytest.StashKey()
SURVEY_KEY = pytest.StashKey()
SEALED_KEY = pytest.StashKey()


def pytest_addhooks(pluginmanager):
    pluginmanager.add_hookspecs(hookspecs)


# The settings this run loaded, or None when the repository has no [tool.testrex]
def get_settings(config):
    return config.stash.get(SETTINGS_KEY, None)


def pytest_configure(config):
    try:
        loaded = settings_module.load(str(config.rootpath))
    except settings_module.SettingsError as error:
        raise pytest.UsageError(str(error)) from error
    config.stash[SETTINGS_KEY] = loaded
    if loaded is None:
        return
    config.addinivalue_line(
        "markers", 'requires_binary(*names): skips, before its fixtures run, unless every named program is on PATH ("a|b" takes either)')
    for marker in loaded.requirement_markers[1:]:
        config.addinivalue_line("markers", "%s(*names): skips, before its fixtures run, unless every name is available" % marker)
    config.addinivalue_line("markers", "allow_network: may open outbound connections")
    # A pytest run inside a test, such as pytester's, finds the seal in place
    # and must leave it for the session that applied it to remove
    config.stash[SEALED_KEY] = bool(loaded.sealed_programs) and seal.seal(loaded.sealed_programs)


def pytest_unconfigure(config):
    if config.stash.get(SEALED_KEY, False):
        seal.unseal()

###########################################################
# Required programs
###########################################################

# The required programs not on PATH; "a|b" is missing only when neither is there
def missing_binaries(names):
    return [name for name in names if not any(shutil.which(option) for option in name.split("|"))]


# {marker: check} for requires_binary and every marker a conftest hook adds
def requirement_checkers(config):
    checkers = {"requires_binary": missing_binaries}
    for result in config.hook.pytest_testrex_requirement_checkers(config = config):
        checkers.update(result)
    return checkers


def pytest_collection_modifyitems(config, items):
    loaded = get_settings(config)
    if loaded is None:
        return
    checkers = requirement_checkers(config)
    unchecked = [marker for marker in loaded.requirement_markers if marker not in checkers]
    if unchecked:
        raise pytest.UsageError(
            "requirement markers with no pytest_testrex_requirement_checkers hook to enforce them: %s" % unchecked)
    for item in items:
        missing = []
        for marker in loaded.requirement_markers:
            names = [name for mark in item.iter_markers(marker) for name in mark.args]
            if names:
                missing.extend(checkers[marker](names))
        if missing:
            item.add_marker(pytest.mark.skip(reason = "%s not installed" % ", ".join(missing)))

###########################################################
# Network
#
# A test that quietly reaches the internet passes on a connected machine and
# fails in CI, and its result depends on a third party. Subprocess based tests
# are unaffected; this only closes the in-process path.
###########################################################

# Stands in for every socket connect while the network is closed
def refuse_connection(*args, **kwargs):
    raise RuntimeError(
        "outbound network access is not available to tests; "
        "mark the test with @pytest.mark.allow_network if it truly needs it")


# Closes outbound connections for each test unless it is marked allow_network
@pytest.fixture(autouse = True)
def no_outbound_network(request):
    loaded = get_settings(request.config)
    if loaded is None or not loaded.block_network or request.node.get_closest_marker("allow_network"):
        return
    monkeypatch = request.getfixturevalue("monkeypatch")
    monkeypatch.setattr(socket.socket, "connect", refuse_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_connection)
    monkeypatch.setattr(socket, "create_connection", refuse_connection)

###########################################################
# The meta suite
###########################################################

# The files the meta suite reads, found once per run
def get_survey(config):
    if SURVEY_KEY not in config.stash:
        loaded = get_settings(config)
        if loaded is None:
            raise pytest.UsageError("the TestRex suite needs a [tool.testrex] table in pyproject.toml")
        config.stash[SURVEY_KEY] = suite.survey(loaded)
    return config.stash[SURVEY_KEY]


def pytest_generate_tests(metafunc):
    if metafunc.cls is None or not issubclass(metafunc.cls, suite.TestRex):
        return
    for argument, (values, ids) in get_survey(metafunc.config).parameters().items():
        if argument in metafunc.fixturenames:
            metafunc.parametrize(argument, values, ids = ids)


# The survey, for the meta suite's checks
@pytest.fixture(scope = "session")
def testrex_survey(request):
    return get_survey(request.config)
