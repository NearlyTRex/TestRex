# The function behind a pytest fixture, to call it outside a test session
def unwrap(fixture):
    return getattr(fixture, "__wrapped__", None) or fixture.__pytest_wrapped__.obj
