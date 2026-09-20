# AI Agent Trace Event Schema

An open [JSON Schema](https://json-schema.org/) for normalized AI-agent runtime trace events — tool calls, human interventions, errors, and deployment changes.

## Why this exists

If you're shipping an autonomous AI agent into the EU, [Annex IV of the EU AI Act](https://artificialintelligenceact.eu/annex/4/) requires technical documentation covering how the system is monitored, how humans oversee it, and what changed across its lifecycle. That evidence lives in your agent's *runtime traces* — not in its source code. A static code scan can tell you an SDK is imported; it can't tell you what the agent actually did.

Most agent frameworks already emit this data in some form (OpenTelemetry spans, LangSmith runs, AgentOps sessions, MCP tool-call logs) — but every framework's raw format is different. This repo defines a small, common target shape that any of those can be mapped down to, so tooling built against this schema works regardless of which framework produced the trace.

## The schema

Five event types, each with the minimum required fields to be useful as compliance evidence:

| Event | Required fields | Use case |
|---|---|---|
| `tool_call` | `tool`, `status` | An agent invoked a tool/API |
| `model_call` | — | An agent called an LLM |
| `human_intervention` | `actor`, `action` | A human approved, rejected, or overrode something |
| `error` | — | Something failed |
| `deployment_change` | `from`, `to` | The system's version changed |

Every event carries a stable `id` so it can be cited as evidence in generated documentation (e.g. `[evidence: trace #a91f02c1]`).

See [`schema.json`](./schema.json) for the full definition and [`example-trace.json`](./example-trace.json) for a worked example.

## Validating your own traces

```bash
pip install jsonschema rfc3339-validator
python validate.py your-trace-events.json
```

`rfc3339-validator` is required, not optional — without it, `jsonschema`'s date-time format check silently accepts any string regardless of validity, and `validate.py` will refuse to run rather than give you a false sense of correctness.

## `traceconv` — convert your existing traces to this schema

If you already have OpenTelemetry or LangSmith trace exports, `traceconv.py` converts them into this schema so you don't have to hand-map the fields yourself.

```bash
python traceconv.py otel your-otel-export.json -o trace-events.json
python traceconv.py langsmith your-langsmith-runs.json -o trace-events.json

# then check the result is valid:
python validate.py trace-events.json
```

It's a heuristic, best-effort converter covering common export shapes (OTLP/JSON spans, LangSmith run exports with feedback), not an exhaustive parser for every possible instrumentation setup — unrecognized spans/runs are skipped with a warning rather than causing a crash. If your setup uses different attribute names, the mapping functions in `traceconv.py` are short and meant to be adapted; PRs adding support for other export shapes (AgentOps, MCP logs, other OTel semantic conventions) are welcome.

## Who maintains this

This schema is maintained by [Attestly](https://attestly.online), which reads traces in this shape (or maps OpenTelemetry/LangSmith/AgentOps/MCP logs into it) and drafts EU AI Act Annex IV technical documentation with evidence links back to the specific trace events that justify each section. Using this schema doesn't require using Attestly — it's published openly so any tool in this space can adopt a shared format instead of everyone inventing their own.

Related reading: [why runtime evidence beats static code scans for Annex IV](https://attestly.online/why-traces-over-scans), and a [free EU AI Act risk checker](https://attestly.online/eu-ai-act-risk-checker) if you're not sure whether your system needs this kind of documentation at all.

## License

MIT — see [LICENSE](./LICENSE). Use it, fork it, extend it.

## Contributing

Issues and PRs welcome, especially proposals for additional event types (e.g. `retrieval_call`, `guardrail_triggered`) that come up in real agent architectures.
