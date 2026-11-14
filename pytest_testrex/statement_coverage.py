"""What every statement coverage plugin shares: finding the sources to measure,
reading them, the report, and the options and session hooks around them.

Each language plugin (shell, JavaScript, Lua) names itself with a prefix, such
as "js-cov", that its options and config attributes are derived from, and
supplies how to measure its sources against what its tests left behind.
"""

import fnmatch
import os

import pytest

SKIPPED_DIRS = {".git", ".hg", ".venv", "venv", "node_modules", "__pycache__"}

# A source bigger than this is not one a person wrote; refuse rather than scan it
MAX_SOURCE_BYTES = 4 * 1024 * 1024

# Most missed statements listed per source, so one badly covered file can't flood the log
MISSED_LISTED = 20


class SourceError(Exception):
    """A source that can't be measured: unreadable, too big or not parsable."""


###########################################################
# Sources
###########################################################


def find_sources(sources, extensions):
    """Files named by sources: files as given, directories searched for the extensions."""
    found = set()
    for source in sources:
        if os.path.isfile(source):
            found.add(source)
            continue
        for root, dirs, files in os.walk(source):
            dirs[:] = [name for name in dirs if name not in SKIPPED_DIRS]
            found.update(os.path.join(root, name) for name in files if name.endswith(tuple(extensions)))
    return sorted(found)


def is_excluded(name, patterns):
    """Whether a path (relative to the rootdir) matches any exclude glob.
    A * matches across directories, so `vendor/*` excludes everything under vendor/."""
    name = name.replace(os.sep, "/")
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def read_source(path, error=SourceError):
    """The text of a source, refusing one too big to be one a person wrote."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        source = handle.read(MAX_SOURCE_BYTES + 1)
    if len(source) > MAX_SOURCE_BYTES:
        raise error(f"larger than {MAX_SOURCE_BYTES} bytes; not a source to measure")
    return source


def describe_statement(lines, statement, width=72):
    """A statement's first line, squeezed to one line, for the report."""
    first, last = statement
    text = " ".join(lines[first - 1].split())
    if len(text) > width:
        text = text[:width - 3] + "..."
    return text + " ..." if last > first and not text.endswith("...") else text


###########################################################
# Report
###########################################################


def get_percent(result):
    """The percent of a source's statements that ran; 100 when it has none."""
    if result["statements"] == 0:
        return 100.0
    return 100.0 * result["covered"] / result["statements"]


def get_total_percent(results):
    """The percent of every source's statements that ran; 100 when there are none."""
    statements = sum(result["statements"] for result in results.values())
    if statements == 0:
        return 100.0
    return 100.0 * sum(result["covered"] for result in results.values()) / statements


def meets_floor(results, floor):
    """Whether the total reaches the floor; always, with no floor."""
    return floor is None or get_total_percent(results) >= floor


def format_missed(missed, limit=8):
    """Missed (first, last) spans as "3, 5-7", cut to limit spans."""
    spans = [f"{first}" if first == last else f"{first}-{last}" for first, last in missed]
    if len(spans) > limit:
        spans = spans[:limit] + ["..."]
    return ", ".join(spans)


def render_missed(ordered):
    """The statements no test ran, with their source, files least covered first."""
    lines = []
    for name, result in ordered:
        missed = list(zip(result["missed"], result["missed_source"], strict = True))
        for (first, _), text in missed[:MISSED_LISTED]:
            lines.append(f"  {name}:{first}  {text}")
        if len(missed) > MISSED_LISTED:
            lines.append(f"  {name}: ... and {len(missed) - MISSED_LISTED} more")
    return lines


def render_report(results, floor=None, title="Shell coverage", label="Script"):
    """The report under a title, files least covered first."""
    width = max([len(name) for name in results] + [len(label)])
    lines = [title, ""]
    lines.append(f"{label:<{width}}  {'Stmts':>5}  {'Miss':>5}  {'Cover':>6}  Missing")
    ordered = sorted(results.items(), key=lambda item: (get_percent(item[1]), item[0]))
    for name, result in ordered:
        lines.append(f"{name:<{width}}  {result['statements']:>5}  {len(result['missed']):>5}  "
                     f"{get_percent(result):>5.1f}%  {format_missed(result['missed'])}")
    missed = render_missed(ordered)
    if missed:
        lines += ["", "Missed statements"] + missed
    total = get_total_percent(results)
    lines.append("")
    lines.append(f"Total: {total:.1f}%")
    if floor is not None:
        lines.append(f"Floor: {floor:.1f}% ({'met' if total >= floor else 'NOT MET'})")
    return "\n".join(lines)


###########################################################
# Plugin plumbing
###########################################################


def add_options(parser, prefix, group_name, source_help, branch_help=None):
    """--<prefix>-source, -exclude, -report, -fail-under and, given its help, -branch, in their own group."""
    group = parser.getgroup(group_name)
    group.addoption(f"--{prefix}-source", action="append", default=[], metavar="PATH", help=source_help)
    group.addoption(f"--{prefix}-exclude", action="append", default=[], metavar="GLOB",
                    help="leave out files whose path (relative to rootdir) matches this glob, "
                         "e.g. 'vendor/*'; repeatable")
    group.addoption(f"--{prefix}-report", action="store_true",
                    help=f"report how much of the {group_name.removesuffix(' coverage')} the tests ran")
    if branch_help:
        group.addoption(f"--{prefix}-branch", action="store_true", help=branch_help)
    group.addoption(f"--{prefix}-fail-under", type=float, default=None, metavar="N",
                    help=f"fail when {group_name} is below this percentage (implies the report)")


def is_enabled(config, prefix):
    """Whether any of the prefix's options asks for coverage."""
    return bool(config.getoption(f"--{prefix}-source") or config.getoption(f"--{prefix}-report")
                or config.getoption(f"--{prefix}-fail-under") is not None)


def is_worker(config):
    """Whether this is a pytest-xdist worker rather than the controller."""
    # pytest-xdist workers inherit the controller's environment, trace
    # directory included; only the controller measures
    return hasattr(config, "workerinput")


def get_sources(config, prefix):
    """The --<prefix>-source paths made absolute, or the rootdir; a missing one is a usage error."""
    root = str(config.rootpath)
    sources = [os.path.join(root, source) for source in config.getoption(f"--{prefix}-source")] or [root]
    for source in sources:
        if not os.path.exists(source):
            raise pytest.UsageError(f"--{prefix}-source {source} does not exist")
    return sources


def is_branch(config, prefix):
    """Whether branches count too; False for a plugin without the option."""
    return bool(config.getoption(f"--{prefix}-branch", False))


def attribute(prefix, name):
    """The config attribute a plugin keeps one of its values under."""
    return prefix.replace("-", "_") + "_" + name


def finish(session, prefix, measure):
    """Measure with measure(root, sources, branch, exclude) once tests are done, failing
    the session on a source it can't measure or a total below the floor."""
    config = session.config
    try:
        results = measure(str(config.rootpath), get_sources(config, prefix),
                          is_branch(config, prefix), config.getoption(f"--{prefix}-exclude"))
    except SourceError as error:
        setattr(config, attribute(prefix, "error"), str(error))
        if session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return
    setattr(config, attribute(prefix, "results"), results)
    if not meets_floor(results, config.getoption(f"--{prefix}-fail-under")) and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def summarize(terminalreporter, config, prefix, title, label):
    """Write the report, or why a source could not be measured, after the run."""
    error = getattr(config, attribute(prefix, "error"), None)
    section = title.lower()
    if error:
        terminalreporter.write_sep("=", section)
        terminalreporter.write_line(f"Could not measure: {error}")
        terminalreporter.write_line(f"Leave it out with --{prefix}-exclude if it should not be measured, "
                                    "e.g. a vendored file.")
        return
    results = getattr(config, attribute(prefix, "results"), None)
    if results is None:
        return
    terminalreporter.write_sep("=", section)
    branch = is_branch(config, prefix)
    terminalreporter.write_line(render_report(
        results, config.getoption(f"--{prefix}-fail-under"),
        title=title + (" (branches count as statements)" if branch else ""), label=label))
