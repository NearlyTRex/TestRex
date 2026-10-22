# Imports
import os

# Local imports
from pytest_testrex import documentation, standards
from pytest_testrex.discovery import parsed

###########################################################
# Library rules
#
# The documentation and coding-standard rules run over library_targets, the
# repository's own code rather than its tests. A rule counts its findings
# across the whole library and holds that count to the rule's baseline, zero
# when it has none, so a repository adopts a rule today and fixes what it
# finds over time. A count above the baseline fails; so does one below it,
# until the baseline is lowered to match, so a fix can never be quietly undone.
###########################################################

# Most findings listed in a failure; the count says how many more there are
MAX_LISTED = 50


# Every .py file a target names: the file itself, or every one under a directory
def discover_library_files(targets):
    found = []
    for target in targets:
        if os.path.isfile(target):
            found.append(target)
            continue
        for root, dirs, files in os.walk(target):
            dirs[:] = [name for name in dirs if name != "__pycache__" and not name.startswith(".")]
            found.extend(os.path.join(root, name) for name in files if name.endswith(".py"))
    return sorted(set(found))


# Whether path is one of the roots or inside one
def is_under(path, roots):
    return any(path == root or path.startswith(root + os.sep) for root in roots)


# The text of a file
def read_source(path):
    with open(path, "r", encoding = "utf-8") as handle:
        return handle.read()


# Why a rule is off for these settings, or None when it runs
def why_off(settings, rule):
    if not settings.library_targets:
        return "no library_targets in [tool.testrex]"
    if rule in ("documented", "doc-sections", "doc-paraphrase") and not settings.doc_style:
        return "no doc_style in [tool.testrex]"
    if rule == "doc-length" and not settings.doc_max_lines:
        return "no doc_max_lines in [tool.testrex]"
    if rule == "wrappers" and not settings.wrappers:
        return "no wrappers in [tool.testrex]"
    if rule in standards.STANDARDS and rule not in settings.standards:
        return "%s is not in [tool.testrex] standards" % rule
    return None


# What one rule finds in one file
def file_findings(settings, rule, path):
    tree = parsed(path)
    if rule == "documented":
        found = documentation.undocumented(tree, read_source(path), settings.doc_style)
        if settings.doc_style == "docstring" and not documentation.has_module_docstring(tree):
            found.insert(0, "no module docstring")
        return found
    if rule == "doc-sections":
        return documentation.section_mismatches(tree)
    if rule == "doc-length":
        return documentation.overlong(tree, read_source(path), settings.doc_max_lines)
    if rule == "doc-paraphrase":
        return documentation.paraphrases(tree, read_source(path))
    if rule == "wrappers":
        return [] if is_under(path, settings.wrapper_modules) else standards.unwrapped_calls(tree, settings.wrappers)
    if rule in standards.COMMAND_ALLOWED and is_under(path, settings.command_paths):
        return []
    if rule == "long-functions":
        return standards.long_functions(tree, settings.max_function_lines, settings.max_nesting)
    if rule == "long-modules":
        return standards.long_module(read_source(path), settings.max_module_lines)
    if rule in standards.SOURCE_CHECKS:
        return standards.SOURCE_CHECKS[rule](tree, read_source(path))
    return standards.CHECKS[rule](tree)


# "path: finding" for everything a rule finds across the library
def findings(settings, rule, files):
    return ["%s: %s" % (os.path.relpath(path, settings.repo_root), finding)
            for path in files for finding in file_findings(settings, rule, path)]


# What is wrong with a rule's findings against its baseline, or None
def ratchet(rule, found, allowed):
    if len(found) > allowed:
        listed = found[:MAX_LISTED] + (["... and %d more" % (len(found) - MAX_LISTED)] if len(found) > MAX_LISTED else [])
        return "%s: %d finding(s), %d allowed by the baseline\n%s" % (rule, len(found), allowed, "\n".join(listed))
    if len(found) < allowed:
        return ("%s: %d finding(s), fewer than the baseline of %d; lower [tool.testrex.baseline] %s to %d "
                "so they stay fixed" % (rule, len(found), allowed, rule, len(found)))
    return None
