# Imports
import ast
import os
import sys
import textwrap

# Third-party imports
import pytest

# Helpers at the top of Tests/ are imported by name; importlib mode puts nothing on the path
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

###########################################################
# Sample sources
#
# Each rule is run against a source that breaks it, written under tmp_path,
# so a rule that can no longer fail fails here instead.
###########################################################

@pytest.fixture
def write_file(tmp_path):
    def write(relative_path, text = ""):
        path = tmp_path / relative_path
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_text(textwrap.dedent(text), encoding = "utf-8")
        return path
    return write


@pytest.fixture
def parse_sample(write_file):
    def parse(text, name = "test_sample.py"):
        return ast.parse(write_file(name, text).read_text(encoding = "utf-8"))
    return parse
