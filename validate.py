#!/usr/bin/env python3
"""
Validate a file of AI agent trace events against schema.json.

Usage:
    python validate.py path/to/trace-events.json

Exits 0 and prints "OK" if every event is valid, otherwise prints
each validation error and exits 1.

Requires: pip install jsonschema
"""
import json
import sys

try:
    from jsonschema import Draft202012Validator
except ImportError:
    print("Missing dependency. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(2)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} path/to/trace-events.json", file=sys.stderr)
        sys.exit(2)

    schema_path = "schema.json"
    events_path = sys.argv[1]

    with open(schema_path) as f:
        schema = json.load(f)
    with open(events_path) as f:
        events = json.load(f)

    if isinstance(events, dict):
        events = [events]

    validator = Draft202012Validator(schema)
    had_error = False

    for i, event in enumerate(events):
        errors = sorted(validator.iter_errors(event), key=lambda e: e.path)
        for error in errors:
            had_error = True
            print(f"[event {i}] {error.message}", file=sys.stderr)

    if had_error:
        sys.exit(1)

    print(f"OK — {len(events)} event(s) valid.")


if __name__ == "__main__":
    main()
