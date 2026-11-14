# Local imports
from pytest_testrex import practices


def test_every_change_to_the_process_is_found_with_its_line(parse_sample):
    tree = parse_sample("""
        import os
        import sys
        os.chdir("/")
        os.umask(0)
        os.putenv("A", "1")
        os.unsetenv("A")
        sys.path.insert(0, "x")
        sys.path.append("y")
        sys.path = []
        sys.path += ["z"]
        sys.modules["m"] = object()
        del sys.modules["m"]
        sys.argv = ["x"]
        sys.stdout = None
        os.environ["B"] = "1"
        del os.environ["B"]
        os.environ.pop("C")
        os.environ.update({"D": "1"})
        os.environ = {}
        """)

    assert practices.process_mutations(tree) == [
        "line 4: os.chdir(...)", "line 5: os.umask(...)", "line 6: os.putenv(...)", "line 7: os.unsetenv(...)",
        "line 8: sys.path.insert(...)", "line 9: sys.path.append(...)", "line 10: sys.path", "line 11: sys.path",
        "line 12: sys.modules[...]", "line 13: sys.modules[...]", "line 14: sys.argv", "line 15: sys.stdout",
        "line 16: os.environ[...]", "line 17: os.environ[...]", "line 18: os.environ.pop(...)",
        "line 19: os.environ.update(...)", "line 20: os.environ"]


def test_a_call_through_an_import_alias_is_still_the_call(parse_sample):
    tree = parse_sample("""
        import sys as system
        from os import chdir, environ
        chdir("/")
        system.path.insert(0, "x")
        environ["A"] = "1"
        """)

    assert practices.process_mutations(tree) == [
        "line 4: os.chdir(...)", "line 5: sys.path.insert(...)", "line 6: os.environ[...]"]


def test_monkeypatch_reads_and_other_objects_are_not_process_changes(parse_sample):
    tree = parse_sample("""
        import os
        import sys
        def test_x(monkeypatch, tmp_path):
            monkeypatch.chdir(tmp_path)
            monkeypatch.syspath_prepend("x")
            monkeypatch.setitem(sys.modules, "m", object())
            monkeypatch.setenv("A", "1")
        here = os.getcwd()
        first = sys.path[0]
        paths = list(sys.path)
        home = os.environ["HOME"]
        copied = dict(os.environ)
        copied["A"] = "1"
        other.path.insert(0, "x")
        modules = {}
        modules["m"] = 1
        thing.argv = []
        """)

    assert practices.process_mutations(tree) == []


def test_pytest_raises_of_any_error_without_a_match_is_found(parse_sample):
    tree = parse_sample("""
        import pytest
        from pytest import raises
        def test_x():
            with pytest.raises(Exception):
                pass
            with pytest.raises(BaseException):
                pass
            with raises(Exception):
                pass
            with pytest.raises(Exception, match = "boom"):
                pass
            with pytest.raises(ValueError):
                pass
            with pytest.raises((KeyError, IndexError)):
                pass
            with pytest.raises():
                pass
        """)

    assert practices.broad_raises(tree) == ["line 5", "line 7", "line 9"]


def test_a_raises_block_with_more_than_one_statement_is_found(parse_sample):
    tree = parse_sample("""
        import pytest
        def test_x():
            with pytest.raises(ValueError):
                value = "x"
                int(value)
            with pytest.raises(ValueError):
                int("x")
            with pytest.raises(ValueError) as info:
                int("x")
            with open("f") as handle:
                handle.read()
                handle.read()
            assert info
        """)

    assert practices.crowded_raises(tree) == ["line 4"]


def test_a_skip_or_xfail_without_a_reason_is_found_as_a_call_or_a_bare_marker(parse_sample):
    tree = parse_sample("""
        import pytest
        @pytest.mark.skip
        def test_a(): pass
        @pytest.mark.skip()
        def test_b(): pass
        @pytest.mark.xfail
        def test_c(): pass
        @pytest.mark.xfail(strict = True)
        def test_d(): pass
        @pytest.mark.skipif(True)
        def test_e(): pass
        def test_f():
            pytest.skip()
        def test_g():
            pytest.xfail()
        pytestmark = pytest.mark.skip
        """)

    assert practices.unexplained_skips(tree) == [
        "line 3", "line 5", "line 7", "line 9", "line 11", "line 14", "line 16", "line 17"]


def test_a_skip_or_xfail_with_a_reason_is_not_found(parse_sample):
    tree = parse_sample("""
        import pytest
        @pytest.mark.skip("not ready")
        def test_a(): pass
        @pytest.mark.skip(reason = "not ready")
        def test_b(): pass
        @pytest.mark.xfail(reason = "bug 12")
        def test_c(): pass
        @pytest.mark.skipif(True, reason = "no network")
        def test_d(): pass
        def test_e():
            pytest.skip("not here")
        def test_f():
            pytest.xfail(reason = "bug 13")
        with pytest.raises(pytest.skip.Exception):
            pytest.skip.Exception
        """)

    assert practices.unexplained_skips(tree) == []


def test_the_line_of_a_finding_is_the_number_after_line():
    assert practices.line_of("line 12: sys.path") == 12
    assert practices.line_of("line 3") == 3


def test_findings_are_in_line_order_past_line_nine(parse_sample):
    padding = ["x = 1"] * 8
    block = ["with pytest.raises(Exception):", "    pass"]
    tree = parse_sample("\n".join(["import pytest", *padding, *block, *padding, *block]))

    assert practices.broad_raises(tree) == ["line 10", "line 20"]
