# Imports
import ast
import os

# Local imports
from pytest_testrex.discovery import FUNCTION_DEFS, parsed

###########################################################
# Import cycles
#
# The import-cycles standard finds modules that import each other, directly or
# around a loop, as Python runs the imports rather than as they are written.
# Importing a.b.c runs a/__init__.py and a/b/__init__.py first, so a module that
# imports one submodule of a package also imports everything that package's
# __init__ imports. A cycle through a package __init__ is the one that works or
# crashes depending on which module a process happens to import first.
#
# Imports inside functions and under `if TYPE_CHECKING:` run later or never, so
# they make no edge. A module's own parent packages are already importing when
# it runs, so reaching one only to get to a submodule is no edge either; taking
# a name the package itself defines is, since that name may not be set yet.
###########################################################

# The name a library file is imported by: its path below the first folder up that is not a package
def module_name(path):
    parts = [os.path.splitext(os.path.basename(path))[0]]
    folder = os.path.dirname(path)
    while os.path.isfile(os.path.join(folder, "__init__.py")):
        parts.insert(0, os.path.basename(folder))
        folder = os.path.dirname(folder)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


# Whether an if-test is TYPE_CHECKING, bare or as typing.TYPE_CHECKING
def is_type_checking(test):
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


# The import statements that run when the module is imported
def executed_imports(tree):
    found = []
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, FUNCTION_DEFS):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
            continue
        if isinstance(node, ast.If) and is_type_checking(node.test):
            pending.extend(node.orelse)
            continue
        pending.extend(child for child in ast.iter_child_nodes(node)
                       if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case)))
    return found


# The dotted names leading to a module: a, a.b and a.b.c for a.b.c
def prefixes(name):
    parts = name.split(".")
    return [".".join(parts[:index]) for index in range(1, len(parts) + 1)]


# The absolute module a from-import names, resolving its leading dots against the importer's package
def from_module(node, package):
    if not node.level:
        return node.module
    base = package.split(".")[:len(package.split(".")) - node.level + 1] if package else []
    return ".".join(base + ([node.module] if node.module else []))


# Each module an import statement loads, with whether the importer takes something from
# it (True) or only passes through it on the way to a submodule (False)
def loaded_modules(node, package, known):
    loaded = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            loaded += [(name, name == alias.name) for name in prefixes(alias.name)]
        return loaded
    module = from_module(node, package)
    loaded += [(name, False) for name in prefixes(module)[:-1]]
    submodules = ["%s.%s" % (module, alias.name) for alias in node.names if "%s.%s" % (module, alias.name) in known]
    loaded.append((module, len(submodules) < len(node.names)))
    return loaded + [(name, True) for name in submodules]


# The library modules a module imports when it runs
def module_edges(name, is_package, tree, known):
    package = name if is_package else name.rpartition(".")[0]
    importing = set(prefixes(name)) if name else set()
    edges = set()
    for node in executed_imports(tree):
        for target, taken in loaded_modules(node, package, known):
            if target in known and target != name and (taken or target not in importing):
                edges.add(target)
    return edges


# The import graph of the library files, module name to the modules it imports, and each module's file
def import_graph(files):
    paths = {module_name(path): path for path in files}
    graph = {name: module_edges(name, os.path.basename(path) == "__init__.py", parsed(path), paths)
             for name, path in paths.items()}
    return graph, paths


# The strongly connected groups of an import graph, found with Tarjan's algorithm on an explicit
# stack so a long import chain cannot run past the recursion limit
class StrongGroups:

    # Ready to search the graph, module name to the modules it imports
    def __init__(self, graph):
        self.graph = graph
        self.index = {}
        self.low = {}
        self.stack = []
        self.on_stack = set()
        self.groups = []

    # Number a module, put it on the stack and queue its imports for a visit
    def enter(self, node, work):
        self.index[node] = self.low[node] = len(self.index)
        self.stack.append(node)
        self.on_stack.add(node)
        work.append((node, iter(sorted(self.graph[node]))))

    # Finish a module whose imports are all visited, closing its group when it is the group's root
    def leave(self, node, work):
        work.pop()
        if work:
            parent = work[-1][0]
            self.low[parent] = min(self.low[parent], self.low[node])
        if self.low[node] == self.index[node]:
            self.close_group(node)

    # Pop the modules of the group rooted at node, keeping the group when it holds a cycle
    def close_group(self, node):
        group = []
        while not group or group[-1] != node:
            group.append(self.stack.pop())
            self.on_stack.discard(group[-1])
        if len(group) > 1:
            self.groups.append(sorted(group))

    # Take one step: visit the next import of the module on top of the work stack, or leave it
    def step(self, work):
        node, children = work[-1]
        child = next(children, None)
        if child is None:
            self.leave(node, work)
        elif child not in self.index:
            self.enter(child, work)
        elif child in self.on_stack:
            self.low[node] = min(self.low[node], self.index[child])

    # The groups with more than one module, each sorted, in order
    def find(self):
        for root in sorted(self.graph):
            if root in self.index:
                continue
            work = []
            self.enter(root, work)
            while work:
                self.step(work)
        return sorted(self.groups)


# The strongly connected groups of the graph with more than one module, each sorted
def cyclic_groups(graph):
    return StrongGroups(graph).find()


# One breadth-first round inside the group: the next frontier, and the module that imports
# the start back when this round closes the loop
def search_round(graph, members, frontier, came_from, start):
    following = []
    for node in frontier:
        for child in sorted(graph[node] & members):
            if child == start:
                return following, node
            if child not in came_from:
                came_from[child] = node
                following.append(child)
    return following, None


# The shortest loop from the first module of a group back to itself, staying inside the group
def shortest_loop(graph, group):
    start, members = group[0], set(group)
    came_from = {start: None}
    frontier = [start]
    while frontier:
        frontier, closing = search_round(graph, members, frontier, came_from, start)
        if closing is not None:
            return path_from_start(came_from, closing) + [start]
    return group


# The path a breadth-first search took from its start to a node
def path_from_start(came_from, node):
    path = []
    while node is not None:
        path.insert(0, node)
        node = came_from[node]
    return path


# Each import cycle in the library files, as (file of its first module, "a -> b -> a" with the group's size)
def cycles(files):
    graph, paths = import_graph(files)
    found = []
    for group in cyclic_groups(graph):
        loop = shortest_loop(graph, group)
        found.append((paths[group[0]], "import cycle among %d modules: %s" % (len(group), " -> ".join(loop))))
    return found
