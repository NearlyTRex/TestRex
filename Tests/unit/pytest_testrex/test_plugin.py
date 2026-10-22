# Third-party imports
import pytest

# Local imports
from pytest_testrex import plugin, seal

CONFIGURED = "[tool.testrex]\nsuites = ['unit']\nintegration_suites = []\n"


def test_without_a_table_the_plugin_registers_nothing(pytester):
    pytester.makepyfile(test_a="import pytest\n@pytest.mark.requires_binary('x')\ndef test_a():\n    pass\n")

    # In a process of its own: pytest.mark remembers markers this session
    # already registered, so an in-process run would accept it regardless
    result = pytester.runpytest_subprocess("--strict-markers")

    result.assert_outcomes(errors = 1)
    result.stdout.fnmatch_lines(["*'requires_binary' not found in `markers`*"])


def test_a_bad_setting_stops_the_run(pytester):
    pytester.makepyprojecttoml("[tool.testrex]\nmax_line = 3\n")

    result = pytester.runpytest()

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*has no setting 'max_line'*"])


def test_a_missing_program_skips_its_test_and_a_present_one_runs(pytester):
    pytester.makepyprojecttoml(CONFIGURED)
    pytester.makepyfile(test_a="""
        import pytest

        @pytest.mark.requires_binary("no-such-program-anywhere")
        def test_missing():
            assert False

        @pytest.mark.requires_binary("no-such-program|python3")
        def test_either():
            assert True

        def test_plain():
            assert True
        """)

    result = pytester.runpytest("-rs", "--strict-markers")

    result.assert_outcomes(passed = 2, skipped = 1)
    result.stdout.fnmatch_lines(["*no-such-program-anywhere not installed*"])


def test_a_repository_marker_is_enforced_by_its_hook(pytester):
    pytester.makepyprojecttoml(CONFIGURED + "requirement_markers = ['requires_tool']\n")
    pytester.makeconftest("""
        def pytest_testrex_requirement_checkers(config):
            return {"requires_tool": lambda names: [name + " (tool)" for name in names if name != "Have"]}
        """)
    pytester.makepyfile(test_a="""
        import pytest

        @pytest.mark.requires_tool("Have")
        def test_have():
            assert True

        @pytest.mark.requires_tool("Lack")
        def test_lack():
            assert False
        """)

    result = pytester.runpytest("-rs", "--strict-markers")

    result.assert_outcomes(passed = 1, skipped = 1)
    result.stdout.fnmatch_lines(["*Lack (tool) not installed*"])


def test_a_repository_marker_without_a_hook_stops_the_run(pytester):
    pytester.makepyprojecttoml(CONFIGURED + "requirement_markers = ['requires_tool']\n")
    pytester.makepyfile(test_a="def test_a():\n    assert True\n")

    result = pytester.runpytest()

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*no pytest_testrex_requirement_checkers hook*requires_tool*"])


NETWORK_TESTS = """
    import socket
    import pytest

    def test_blocked():
        with pytest.raises(RuntimeError, match = "allow_network"):
            socket.create_connection(("192.0.2.1", 9))

    @pytest.mark.allow_network
    def test_allowed():
        assert socket.create_connection is not None
        assert "refuse" not in socket.create_connection.__name__
    """


# The outer test is allowed the network only so the inner run starts from an
# unpatched socket, as a real session does
@pytest.mark.allow_network
def test_outbound_network_is_closed_unless_a_test_allows_it(pytester):
    pytester.makepyprojecttoml(CONFIGURED)
    pytester.makepyfile(test_a=NETWORK_TESTS)

    result = pytester.runpytest("--strict-markers")

    result.assert_outcomes(passed = 2)


@pytest.mark.allow_network
def test_the_network_stays_open_when_the_repository_turns_the_block_off(pytester):
    pytester.makepyprojecttoml(CONFIGURED + "block_network = false\n")
    pytester.makepyfile(test_a="import socket\ndef test_open():\n    assert socket.create_connection.__name__ == 'create_connection'\n")

    result = pytester.runpytest()

    result.assert_outcomes(passed = 1)


def test_a_run_inside_a_sealed_session_leaves_the_seal_in_place(pytester):
    pytester.makepyprojecttoml(CONFIGURED + "sealed_programs = ['op']\n")
    pytester.makepyfile(test_a="def test_a():\n    assert True\n")

    result = pytester.runpytest()

    result.assert_outcomes(passed = 1)
    assert seal.is_sealed()


def test_the_settings_are_read_from_the_rootdir(pytester):
    pytester.makepyprojecttoml(CONFIGURED + "max_lines = 7\n")
    config = pytester.parseconfigure()

    assert plugin.get_settings(config).max_lines == 7


def test_the_suite_without_a_table_stops_the_run(pytester):
    pytester.makepyfile(test_rex="from pytest_testrex import suite\nclass TestRex(suite.TestRex):\n    pass\n")

    result = pytester.runpytest()

    result.stdout.fnmatch_lines(["*needs a [[]tool.testrex[]] table*"])
    assert result.ret != pytest.ExitCode.OK


def test_other_test_classes_are_left_alone(pytester):
    pytester.makepyprojecttoml(CONFIGURED)
    pytester.makepyfile(test_a="class TestOther:\n    def test_a(self, request):\n        assert request\n")

    result = pytester.runpytest()

    result.assert_outcomes(passed = 1)
