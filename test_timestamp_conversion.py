#!/usr/bin/env python3
"""
Regression test for the OpenTelemetry timestamp conversion bug flagged in
agentrust-io/awesome-ai-governance PR #99: startTimeUnixNano is serialized
by OTLP/JSON as a decimal string of nanoseconds-since-epoch, not ISO 8601,
and the converter previously passed it through unconverted.

Run: python test_timestamp_conversion.py
Exits non-zero if any check fails.
"""
import sys

from jsonschema import Draft202012Validator, FormatChecker

from traceconv import _normalize_timestamp

SCHEMA = {"type": "string", "format": "date-time"}


def is_valid_date_time(value):
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    return not list(validator.iter_errors(value))


def main():
    failures = []

    # The exact case from the bug report: a numeric-nanosecond string must
    # convert to RFC 3339, not pass through unchanged.
    converted = _normalize_timestamp("1700000000000000000")
    if converted != "2023-11-14T22:13:20Z":
        failures.append(f"expected '2023-11-14T22:13:20Z', got {converted!r}")
    if not is_valid_date_time(converted):
        failures.append(f"converted value {converted!r} does not pass date-time format validation")

    # An already-ISO value must still pass through unchanged.
    passthrough = _normalize_timestamp("2026-08-14T09:12:03Z")
    if passthrough != "2026-08-14T09:12:03Z":
        failures.append(f"expected passthrough of ISO string, got {passthrough!r}")

    # A raw int (not just a digit string) must also convert correctly.
    from_int = _normalize_timestamp(1700000000000000000)
    if from_int != "2023-11-14T22:13:20Z":
        failures.append(f"expected int input to convert to '2023-11-14T22:13:20Z', got {from_int!r}")

    # The unconverted numeric string must be rejected by an enabled
    # date-time format checker — this is what should have caught the bug
    # originally, and validate.py now enables it.
    if is_valid_date_time("1700000000000000000"):
        failures.append("raw nanosecond string incorrectly passed date-time format validation")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        sys.exit(1)

    print("OK — timestamp conversion regression test passed.")


if __name__ == "__main__":
    main()
