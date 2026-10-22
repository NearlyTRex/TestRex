# Imports
import dataclasses
import os

# Third-party imports
import pytest

# Local imports
from pytest_testrex import hygiene, layout, library, lint, quality, requirements, signatures, standards
from pytest_testrex.discovery import (
    checker_names, defines_tests, discover_python_files, parsed)
from pytest_testrex.settings import LIBRARY_RULES

###########################################################
# The meta suite
#
# A repository runs it by subclassing TestRex in a test module under one of
# its meta_dirs:
#
#     from pytest_testrex import suite
#
#     class TestRex(suite.TestRex):
#         """The suite's own rules, from pytest-testrex."""
#
# The plugin parametrizes each check over the files it reads, from the
# repository's [tool.testrex] settings. Nothing here imports a test.
###########################################################

# What the meta suite reads, found once from the settings
@dataclasses.dataclass(frozen = True)
class Survey:
    settings: object
    test_files: list
    all_files: list
    integration_files: list
    split_packages: list
    mirror_directories: list
    library_files: list

    # A path relative to the tests directory, as it appears in test ids
    def relative(self, path):
        return os.path.relpath(path, self.settings.tests_dir)

    # {argument: (values, ids)} for the checks parametrized over files
    def parameters(self):
        found = {}
        for argument, values in [
                ("test_file", self.test_files), ("python_file", self.all_files),
                ("integration_file", self.integration_files), ("split_package", self.split_packages),
                ("mirror_directory", self.mirror_directories)]:
            found[argument] = (values, [self.relative(path) for path in values])
        found["library_rule"] = (list(LIBRARY_RULES), list(LIBRARY_RULES))
        return found


# Find every file and directory the rules are parametrized over
def survey(settings):
    ignored = settings.ignored_dirs
    test_files = discover_python_files(settings.suite_dirs, True, ignored)
    return Survey(
        settings = settings,
        test_files = test_files,
        all_files = discover_python_files(settings.suite_dirs, False, ignored),
        integration_files = discover_python_files(settings.integration_dirs, True, ignored),
        split_packages = layout.discover_split_packages(settings.suite_dirs, ignored),
        mirror_directories = layout.discover_mirror_directories(settings.suite_dirs, ignored),
        library_files = library.discover_library_files(settings.library_targets))


class TestRex:
    """Every rule, parametrized over the repository's tests by the plugin."""

    ###########################################################
    # Discovery
    #
    # These checks only guard the files they see.
    ###########################################################

    def test_test_files_were_discovered(self, testrex_survey):
        minimum = testrex_survey.settings.min_test_files

        assert len(testrex_survey.test_files) >= minimum, (
            "found %d test files under %s, fewer than min_test_files (%d)" % (
                len(testrex_survey.test_files), testrex_survey.settings.tests_dir, minimum))

    def test_every_suite_was_discovered(self, testrex_survey):
        empty = [
            testrex_survey.relative(suite) for suite in testrex_survey.settings.suite_dirs
            if not any(path.startswith(suite + os.sep) for path in testrex_survey.test_files)]

        assert not empty, f"no tests found under {empty}"

    ###########################################################
    # File hygiene
    ###########################################################

    def test_no_test_is_defined_twice(self, test_file):
        # The second definition wins and the first never runs.
        duplicates = hygiene.duplicate_tests(parsed(test_file))

        assert not duplicates, f"defined more than once: {duplicates}"

    def test_no_test_method_is_defined_twice_within_a_class(self, test_file):
        duplicates = hygiene.duplicate_test_methods(parsed(test_file))

        assert not duplicates, f"defined more than once: {duplicates}"

    def test_no_helper_is_defined_twice(self, test_file):
        # The same hazard, and harder to notice because nothing stops collecting.
        duplicates = hygiene.duplicate_definitions(parsed(test_file))

        assert not duplicates, f"defined more than once: {duplicates}"

    def test_no_constant_is_assigned_twice(self, test_file):
        # A second module level assignment quietly replaces the first, so tests
        # above it and below it run against different values.
        duplicates = hygiene.duplicate_constants(parsed(test_file))

        assert not duplicates, f"assigned more than once: {duplicates}"

    def test_module_imports_stay_at_the_top(self, test_file):
        # An import buried between sections reads as belonging to that section,
        # and the next file to be split moves the section without it.
        late = hygiene.late_imports(parsed(test_file))

        assert not late, f"imported below the header at line(s) {late}"

    def test_a_test_file_stays_a_readable_size(self, test_file, testrex_survey):
        # Past this, split it into a directory of the same name with one file
        # per area and shared helpers beside them.
        length = hygiene.line_count(test_file)

        assert length <= testrex_survey.settings.max_lines, f"{length} lines; split it into a package of the same name"

    def test_every_test_file_holds_at_least_one_test(self, test_file):
        assert defines_tests(parsed(test_file)), "no tests in a file named like one"

    ###########################################################
    # Test quality
    ###########################################################

    def test_no_exception_is_silently_swallowed(self, python_file):
        # except X: pass around a test's steps hides the failure the test
        # exists to catch; expect it with pytest.raises, or assert on what
        # handling it did.
        lines = quality.swallowed_handlers(parsed(python_file))

        assert not lines, f"except handler that does nothing, line(s) {lines}"

    def test_every_test_checks_something(self, test_file, testrex_survey):
        # A test that only calls the code passes unless the code raises,
        # whatever it returns or does.
        unchecked = quality.unchecked_tests(parsed(test_file), checker_names(test_file, testrex_survey.settings.tests_dir))

        assert not unchecked, f"asserts nothing: {unchecked}"

    def test_every_test_has_a_check_that_always_runs(self, test_file, testrex_survey):
        # Checks only inside an if, a loop or a try may never execute (an
        # empty list, a branch not taken, an exception raised first) and the
        # test passes.
        conditional = quality.conditional_tests(
            parsed(test_file), checker_names(test_file, testrex_survey.settings.tests_dir))

        assert not conditional, f"every check is conditional: {conditional}"

    def test_no_assertion_is_true_by_construction(self, test_file):
        found = quality.tautologies(parsed(test_file))

        assert not found, f"cannot fail: {found}"

    def test_no_test_only_checks_that_a_value_exists_or_has_a_type(self, test_file, testrex_survey):
        # is not None and isinstance pass for nearly any value; assert what it is.
        weak = quality.weak_only_tests(parsed(test_file), checker_names(test_file, testrex_survey.settings.tests_dir))

        assert not weak, f"only checks existence or type: {weak}"

    def test_no_raising_callable_is_built_from_a_generator(self, python_file):
        lines = quality.generator_throws(parsed(python_file))

        assert not lines, f"define a function that raises instead, line(s) {lines}"

    def test_no_helper_is_copied_between_files(self, testrex_survey):
        # A helper pasted into several files is fixed in one and left broken
        # in the rest. Share it from the nearest conftest.py or a *_helpers.py.
        copied = quality.copied_helpers({
            testrex_survey.relative(path): quality.module_helpers(parsed(path)) for path in testrex_survey.all_files})

        assert not copied, f"identical helper defined in several files: {copied}"

    ###########################################################
    # Layout
    ###########################################################

    def test_a_split_package_holds_test_modules(self, split_package):
        assert any(layout.is_test_module_name(name) for name in layout.python_files(split_package)), (
            "no test_<area>.py files inside")

    def test_a_split_package_has_no_uncollected_tests(self, split_package):
        uncollected = layout.uncollected_test_files(split_package)

        assert not uncollected, f"tests outside a test_*.py file are never collected: {uncollected}"

    def test_a_split_package_covers_a_real_module(self, split_package, testrex_survey):
        settings = testrex_survey.settings
        candidates = layout.source_candidates(
            split_package, layout.suite_of(split_package, settings.suite_dirs), settings.repo_root,
            settings.source_extensions)

        assert any(os.path.exists(path) for path in candidates), (
            "no source to mirror; expected one of " + ", ".join(os.path.relpath(path, settings.repo_root) for path in candidates))

    def test_a_split_package_has_no_single_file_twin(self, split_package):
        twin = layout.single_file_twin(split_package)

        assert twin is None, f"{os.path.basename(twin)} and {os.path.basename(split_package)}/ both exist"

    def test_a_test_directory_is_a_split_package_or_mirrors_the_repo(self, mirror_directory, testrex_survey):
        settings = testrex_survey.settings
        targets = layout.mirror_targets(mirror_directory, layout.suite_of(mirror_directory, settings.suite_dirs), settings.repo_root)
        mirrors = layout.is_meta(mirror_directory, settings.tests_dir, settings.meta_dirs) or any(
            os.path.isdir(path) for path in targets)
        name = os.path.basename(mirror_directory)

        assert mirrors, (
            f"'{testrex_survey.relative(mirror_directory)}' mirrors nothing in the repository; "
            f"if it is a split of test_{name}.py, name it test_{name}/")

    ###########################################################
    # Required programs
    ###########################################################

    def test_no_program_is_required_imperatively(self, test_file, testrex_survey):
        # A requirement checked inside a test or fixture runs after the test's
        # other fixtures have already started; the marker skips before any do.
        markers = testrex_survey.settings.requirement_markers
        lines = requirements.imperative_gates(parsed(test_file), markers)

        assert not lines, (
            f"checks for a program at run time (line(s) {lines}); declare it with a marker instead: {list(markers)}")

    def test_requirement_markers_name_programs_literally(self, test_file, testrex_survey):
        # A computed name can't be checked here or named in the skip reason.
        markers = testrex_survey.settings.requirement_markers
        lines = requirements.non_literal_markers(parsed(test_file), markers)

        assert not lines, f"requirement markers take string literals (line(s) {lines}): {list(markers)}"

    def test_tests_using_a_program_fixture_declare_its_programs(self, test_file, testrex_survey):
        settings = testrex_survey.settings
        conftests = [parsed(path) for path in requirements.visible_conftests(test_file, settings.tests_dir)]
        missing = requirements.undeclared_fixture_programs(parsed(test_file), conftests, settings.fixture_programs)

        assert not missing, "; ".join(missing)

    def test_programs_run_through_subprocess_are_declared(self, test_file):
        tree = parsed(test_file)
        undeclared = requirements.subprocess_binaries(tree) - requirements.accepted(requirements.declared_anywhere(tree))

        assert not undeclared, f"runs {sorted(undeclared)} but never declares it with pytest.mark.requires_binary(...)"

    def test_an_integration_file_declares_the_programs_it_needs(self, integration_file, testrex_survey):
        # Integration tests are the ones that need a program outside the
        # process; one that needs none belongs in a unit suite.
        markers = testrex_survey.settings.requirement_markers

        assert requirements.declares_a_program(parsed(integration_file), markers), (
            "declares no program; mark what it runs, or move it to a unit suite if it runs none")

    ###########################################################
    # Override signatures
    ###########################################################

    def test_an_override_keeps_the_signature_of_the_method_it_overrides(self, testrex_survey):
        packages = testrex_survey.settings.signature_packages
        if not packages:
            pytest.skip("no signature_packages in [tool.testrex]")
        found = signatures.mismatched_overrides(signatures.library_classes(packages).values())

        assert found == [], "overrides that break the contract of their base method: " + ", ".join(found)

    ###########################################################
    # Library code
    #
    # Documentation and coding standards, each held to its baseline count.
    ###########################################################

    def test_the_library_holds_to_the_rule(self, library_rule, testrex_survey):
        settings = testrex_survey.settings
        off = library.why_off(settings, library_rule)
        if off:
            pytest.skip(off)
        files = testrex_survey.library_files + (
            testrex_survey.all_files if library_rule in standards.TEST_STANDARDS else [])
        found = library.findings(settings, library_rule, files)
        problem = library.ratchet(library_rule, found, settings.baseline.get(library_rule, 0))

        assert problem is None, problem

    ###########################################################
    # Pylint
    ###########################################################

    def test_pylint_is_clean_over_all_tests(self, testrex_survey):
        settings = testrex_survey.settings
        roots = lint.import_roots(settings.tests_dir, testrex_survey.all_files)
        result = lint.run_pylint(
            settings.rcfile, settings.repo_root, roots, *lint.pylint_targets(settings.tests_dir, testrex_survey.all_files))

        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_library_holds_to_the_library_rules(self, testrex_survey):
        settings = testrex_survey.settings
        if not settings.library_targets:
            pytest.skip("no library_targets in [tool.testrex]")
        result = lint.run_pylint(
            settings.rcfile, settings.repo_root, [settings.tests_dir],
            *lint.only_rules(settings.library_rules), *settings.library_targets)

        assert result.returncode == 0, result.stdout + result.stderr

