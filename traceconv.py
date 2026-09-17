#!/usr/bin/env python3
"""
traceconv — convert common AI-agent trace export formats into the
ai-agent-trace-schema event format (see schema.json in this repo).

Supported inputs:
  otel        OpenTelemetry trace exports. Two shapes are accepted:
                (a) standard OTLP/JSON: {"resourceSpans": [...]}
                (b) a flattened span list: {"spans": [...]} or a bare
                    JSON array of span objects with plain-dict attributes
  langsmith   A LangSmith run export: a JSON array of run objects
                (the shape returned by the LangSmith SDK's run.dict()
                 / list_runs export, or a manual export with the same
                 field names: id, run_type, name, start_time, end_time,
                 error, extra, feedback)

Usage:
    python traceconv.py otel otel-export.json -o trace-events.json
    python traceconv.py langsmith langsmith-runs.json -o trace-events.json

This is a best-effort heuristic converter, not an exhaustive parser for
every possible exporter configuration. Unrecognized spans/runs are
skipped with a warning on stderr rather than causing a crash — check
the warnings and extend the mapping functions below for your own
setup if you hit gaps. PRs adding support for other shapes welcome.
"""
import argparse
import datetime
import json
import sys
import uuid


def _nanos_to_rfc3339(nanos):
    dt = datetime.datetime.fromtimestamp(nanos / 1_000_000_000, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_timestamp(raw):
    """Convert a raw timestamp value to an RFC 3339 UTC string.

    OTLP/JSON serializes uint64 fields (like startTimeUnixNano) as decimal
    strings representing nanoseconds since the Unix epoch, per the protobuf
    JSON mapping — not ISO 8601. Detect that shape (an int, or a string of
    only digits) and convert it; anything else is assumed to already be an
    RFC 3339 string and is passed through unchanged.
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return _nanos_to_rfc3339(raw)
    if isinstance(raw, str) and raw.isdigit():
        return _nanos_to_rfc3339(int(raw))
    return str(raw)


def _otel_attr_value(value):
    """Extract a plain Python value from an OTLP attribute value object,
    e.g. {"stringValue": "foo"} -> "foo". Falls back to the value as-is
    if it's already a plain scalar (flattened-attributes shape)."""
    if isinstance(value, dict):
        for key in ("stringValue", "intValue", "boolValue", "doubleValue"):
            if key in value:
                return value[key]
        return value
    return value


def _otel_attrs_to_dict(attributes):
    """Normalize OTLP attribute lists ([{"key":..,"value":{...}}]) or
    already-flat dicts into a plain {key: value} dict."""
    if isinstance(attributes, dict):
        return attributes
    out = {}
    if isinstance(attributes, list):
        for attr in attributes:
            if isinstance(attr, dict) and "key" in attr:
                out[attr["key"]] = _otel_attr_value(attr.get("value"))
    return out


def _iter_otel_spans(data):
    """Yield individual span dicts (with attributes normalized to a
    flat dict) from either OTLP/JSON or a flattened span list."""
    if isinstance(data, list):
        spans = data
    elif isinstance(data, dict) and "spans" in data:
        spans = data["spans"]
    elif isinstance(data, dict) and "resourceSpans" in data:
        spans = []
        for rs in data.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                spans.extend(ss.get("spans", []))
    else:
        spans = []

    for span in spans:
        span = dict(span)
        span["attributes"] = _otel_attrs_to_dict(span.get("attributes", {}))
        yield span


def convert_otel(data):
    """Map OpenTelemetry spans to trace-event-schema events.

    Heuristics used (based on common GenAI/tool semantic-convention
    attribute names — adjust for your own instrumentation if it uses
    different attribute keys):
      - a span whose name or attributes suggest a tool invocation
        (attributes containing "tool.name" / "gen_ai.tool.name", or a
        span name starting with "tool.") -> tool_call
      - a span with attributes containing "gen_ai.request.model" or a
        name starting with "llm." / "chat." -> model_call
      - a span with status "ERROR" (or attributes.error) -> also emits
        a separate error event
    """
    events = []
    for span in _iter_otel_spans(data):
        attrs = span.get("attributes", {})
        name = span.get("name", "")
        span_id = span.get("spanId") or span.get("span_id") or str(uuid.uuid4())
        timestamp = _normalize_timestamp(
            span.get("startTimeUnixNano")
            or span.get("start_time")
            or span.get("timestamp")
        )

        tool_name = attrs.get("tool.name") or attrs.get("gen_ai.tool.name")
        model_name = attrs.get("gen_ai.request.model") or attrs.get("llm.model")

        status = span.get("status", {})
        is_error = (
            (isinstance(status, dict) and status.get("code") in ("ERROR", 2))
            or attrs.get("error") is True
        )

        if tool_name or name.startswith("tool."):
            events.append({
                "event": "tool_call",
                "id": f"otel-{span_id}",
                "timestamp": timestamp,
                "tool": tool_name or name,
                "status": "failure" if is_error else "success",
            })
        elif model_name or name.startswith(("llm.", "chat.")):
            events.append({
                "event": "model_call",
                "id": f"otel-{span_id}",
                "timestamp": timestamp,
                "metadata": {"model": model_name} if model_name else {},
            })
        else:
            print(f"warning: skipping unrecognized span '{name}' ({span_id})", file=sys.stderr)
            continue

        if is_error:
            events.append({
                "event": "error",
                "id": f"otel-{span_id}-error",
                "timestamp": timestamp,
                "message": (status.get("message") if isinstance(status, dict) else None)
                or attrs.get("error.message")
                or "error",
            })

    return events


def convert_langsmith(data):
    """Map a LangSmith run export (list of run dicts) to trace-event-schema
    events.

    Heuristics used:
      - run_type == "tool" -> tool_call (status from whether `error` is set)
      - run_type == "llm" or "chat" -> model_call
      - a non-null `error` field on any run -> also emits an error event
      - a `feedback` entry with a user id and a comment/score -> emits a
        human_intervention event (LangSmith feedback is the closest
        native concept to a human review action)
    """
    if isinstance(data, dict) and "runs" in data:
        runs = data["runs"]
    else:
        runs = data

    events = []
    for run in runs:
        run_id = run.get("id") or str(uuid.uuid4())
        timestamp = run.get("start_time") or run.get("startTime")
        run_type = (run.get("run_type") or "").lower()
        has_error = bool(run.get("error"))

        if run_type == "tool":
            events.append({
                "event": "tool_call",
                "id": f"langsmith-{run_id}",
                "timestamp": timestamp,
                "tool": run.get("name", "unknown_tool"),
                "status": "failure" if has_error else "success",
            })
        elif run_type in ("llm", "chat"):
            events.append({
                "event": "model_call",
                "id": f"langsmith-{run_id}",
                "timestamp": timestamp,
                "metadata": {"name": run.get("name")},
            })
        else:
            print(f"warning: skipping unrecognized run_type '{run_type}' ({run_id})", file=sys.stderr)

        if has_error:
            events.append({
                "event": "error",
                "id": f"langsmith-{run_id}-error",
                "timestamp": timestamp,
                "message": str(run.get("error")),
            })

        for fb in run.get("feedback", []) or []:
            if fb.get("user_id"):
                events.append({
                    "event": "human_intervention",
                    "id": f"langsmith-{run_id}-feedback-{fb.get('id', uuid.uuid4())}",
                    "timestamp": fb.get("created_at", timestamp),
                    "actor": fb.get("user_id"),
                    "action": fb.get("comment") or (
                        "approved" if (fb.get("score") or 0) > 0 else "rejected"
                    ),
                })

    return events


CONVERTERS = {
    "otel": convert_otel,
    "langsmith": convert_langsmith,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("format", choices=CONVERTERS.keys(), help="Source format to convert from")
    parser.add_argument("input", help="Path to the source export JSON file")
    parser.add_argument("-o", "--output", default="-", help="Output path (default: stdout)")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    events = CONVERTERS[args.format](data)

    output = json.dumps(events, indent=2, default=str)
    if args.output == "-":
        print(output)
    else:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Wrote {len(events)} event(s) to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
