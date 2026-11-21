import json

from jewelai_observability import MAX_CAUSE_CHAIN, MAX_ORIGIN_FRAMES, exception_diagnostics

SECRET = "sk-live-secret customer prompt https://signed.example/object?sig=abc"


class ProviderBoundaryError(RuntimeError):
    pass


def _raise_secret():
    raise ValueError(SECRET)


def _sanitized_boundary():
    try:
        _raise_secret()
    except ValueError:
        raise ProviderBoundaryError("safe detail") from None


def _capture(function):
    try:
        function()
    except BaseException as exc:
        return exc
    raise AssertionError("expected an exception")


def test_reports_qualified_type_and_innermost_location():
    diagnostics = exception_diagnostics(_capture(_raise_secret))
    assert diagnostics["error_type"] == "builtins.ValueError"
    assert diagnostics["error_chain"] == ["builtins.ValueError"]
    assert diagnostics["error_origin"][-1].startswith("test_exception_diagnostics.py:")
    assert diagnostics["error_origin"][-1].endswith(":_raise_secret")


def test_follows_context_suppressed_by_from_none_to_the_real_origin():
    diagnostics = exception_diagnostics(_capture(_sanitized_boundary))
    assert diagnostics["error_type"].endswith(".ProviderBoundaryError")
    assert diagnostics["error_chain"] == [
        "test_exception_diagnostics.ProviderBoundaryError",
        "builtins.ValueError",
    ]
    assert diagnostics["error_origin"][-1].endswith(":_raise_secret")


def test_never_contains_messages_arguments_or_source_text():
    serialized = json.dumps(exception_diagnostics(_capture(_sanitized_boundary)))
    assert "sk-live" not in serialized
    assert "signed.example" not in serialized
    assert "safe detail" not in serialized
    assert "raise ValueError" not in serialized


def test_explicit_cause_wins_over_context():
    def chained():
        try:
            raise KeyError("context")
        except KeyError:
            raise RuntimeError("outer") from TypeError("cause")

    assert exception_diagnostics(_capture(chained))["error_chain"] == [
        "builtins.RuntimeError",
        "builtins.TypeError",
    ]


def test_cycles_and_long_chains_are_bounded():
    first, second = ValueError("a"), TypeError("b")
    first.__cause__, second.__cause__ = second, first
    assert exception_diagnostics(first)["error_chain"] == [
        "builtins.ValueError",
        "builtins.TypeError",
    ]

    errors = [LookupError(str(index)) for index in range(10)]
    for outer, inner in zip(errors, errors[1:], strict=False):
        outer.__cause__ = inner
    bounded = exception_diagnostics(errors[0])
    assert len(bounded["error_chain"]) == MAX_CAUSE_CHAIN
    assert bounded["error_origin"] == []  # never raised, so no traceback exists


def test_origin_frames_are_bounded():
    def recurse(depth):
        if depth == 0:
            raise RuntimeError("deep")
        recurse(depth - 1)

    origin = exception_diagnostics(_capture(lambda: recurse(20)))["error_origin"]
    assert len(origin) == MAX_ORIGIN_FRAMES
    assert origin[-1].endswith(":recurse")
