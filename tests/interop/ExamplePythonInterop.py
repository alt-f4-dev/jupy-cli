"""Stateful Python fixture for validating Julia -> Python loading."""

calls = 0


def increment(value):
    global calls
    calls += 1
    return value + 1


def number_of_calls():
    return calls


def fail():
    raise ValueError("interop Python fixture failure")


def annotated_increment(value: int) -> int:
    """Type annotations are discoverable without a separate contract file."""
    return value + 1


def unknown_interface(value):
    """Unannotated values remain explicitly unknown rather than trusted."""
    return value
