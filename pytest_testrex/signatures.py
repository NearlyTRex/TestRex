# Imports
import importlib
import inspect
import pkgutil
import warnings

###########################################################
# Override signatures
#
# A method that overrides a base class method is called through the base
# type: callers hold the base and don't know which subclass they got. An
# override that renames, drops or reorders a parameter, or changes a default,
# makes a call that works on one subclass raise TypeError, or quietly mean
# something else, on another. An override keeps every parameter of the method
# it overrides, unchanged and in order, and may add optional ones after them.
###########################################################

OPTIONAL_KINDS = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)


# Every class defined in the named packages and their modules, by full name
def library_classes(packages):
    found = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for package_name in packages:
            package = importlib.import_module(package_name)
            modules = [package] + [
                importlib.import_module(info.name)
                for info in pkgutil.walk_packages(getattr(package, "__path__", []), package_name + ".")]
            for module in modules:
                for value in vars(module).values():
                    if inspect.isclass(value) and value.__module__ == module.__name__:
                        found["%s.%s" % (value.__module__, value.__qualname__)] = value
    return found


# Whether member cannot stand in for base_member
def breaks_the_contract(base_member, member):
    base_parameters = list(inspect.signature(inspect.unwrap(base_member)).parameters.values())
    own_parameters = list(inspect.signature(inspect.unwrap(member)).parameters.values())
    if len(own_parameters) < len(base_parameters):
        return True
    for base, own in zip(base_parameters, own_parameters[:len(base_parameters)], strict = True):
        if (base.name, base.kind, base.default) != (own.name, own.kind, own.default):
            return True
    return any(
        extra.default is inspect.Parameter.empty and extra.kind not in OPTIONAL_KINDS
        for extra in own_parameters[len(base_parameters):])


# module.Class.method for each override that breaks its base's contract.
# Dunders are skipped: __init__ legitimately differs per subclass.
def mismatched_overrides(classes):
    found = []
    for cls in classes:
        for name, member in vars(cls).items():
            if (name.startswith("__") and name.endswith("__")) or not inspect.isfunction(member):
                continue
            base_member = next(
                (vars(base)[name] for base in cls.__mro__[1:] if inspect.isfunction(vars(base).get(name))), None)
            if base_member is not None and breaks_the_contract(base_member, member):
                found.append("%s.%s.%s" % (cls.__module__, cls.__qualname__, name))
    return sorted(found)
