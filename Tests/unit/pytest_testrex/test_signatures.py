# Imports
import sys

# Local imports
from pytest_testrex import signatures

###########################################################
# The classes are assembled with type() because their overrides are broken
# on purpose, which a class statement would have linters flag.
###########################################################

def one_parameter(self, a): ...
def renamed_parameter(self, x): ...
def optional_second(self, a, b = 1): ...
def required_second(self, a, b): ...
def extra_optional(self, a, b = None, **options): ...
def swapped(self, b, a): ...
def default_changed(self, a, b = 2): ...
def no_parameters(self): ...


Base = type("Base", (), {
    "same": optional_second,
    "renamed": one_parameter,
    "dropped_default": optional_second,
    "added_optional": one_parameter,
    "added_required": one_parameter,
    "dropped": optional_second,
    "reordered": required_second,
    "_private": one_parameter,
    "value": 1,
})

Child = type("Child", (Base,), {
    "same": optional_second,
    "renamed": renamed_parameter,
    "dropped_default": required_second,
    "added_optional": extra_optional,
    "added_required": required_second,
    "dropped": one_parameter,
    "reordered": swapped,
    "_private": renamed_parameter,
    "new_method": no_parameters,
    "__init__": no_parameters,
    "value": 2,
})

GrandChild = type("GrandChild", (Child,), {"same": default_changed})


def method_names(found):
    return [name.split(".")[-1] for name in found]


def test_renamed_dropped_reordered_and_changed_default_parameters_are_flagged():
    assert method_names(signatures.mismatched_overrides([Child])) == [
        "_private", "added_required", "dropped", "dropped_default", "renamed", "reordered"]


def test_optional_parameters_after_the_base_ones_and_new_methods_are_allowed():
    found = method_names(signatures.mismatched_overrides([Child]))

    assert "added_optional" not in found
    assert "new_method" not in found


def test_an_override_is_compared_with_the_nearest_base_that_defines_it():
    assert method_names(signatures.mismatched_overrides([GrandChild])) == ["same"]


def test_classes_are_found_in_a_package_and_its_modules_but_not_imported_ones(write_file, tmp_path, monkeypatch):
    write_file("sample_pkg/__init__.py", "from collections import OrderedDict\nclass Top:\n    pass\n")
    write_file("sample_pkg/inner.py", "import warnings\nwarnings.warn('loud')\nclass Inner:\n    pass\n")
    write_file("sample_module.py", "class Alone:\n    pass\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "modules", dict(sys.modules))

    found = signatures.library_classes(["sample_pkg", "sample_module"])

    assert sorted(found) == ["sample_module.Alone", "sample_pkg.Top", "sample_pkg.inner.Inner"]
