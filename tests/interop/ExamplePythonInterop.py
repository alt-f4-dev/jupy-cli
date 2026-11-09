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
