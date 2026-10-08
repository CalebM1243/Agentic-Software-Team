# CLAUDE.md

A learning project: a simulated software team (Business Analyst, Architect, Developer, QA/Refactor) as a LangGraph graph using Claude via `langchain-anthropic`. The user drives it from a terminal CLI. Keep it simple: v1 deliberately has no tool-calling loops and no code-execution sandbox.

## Layout

```
main.py            CLI: reads the idea, streams the graph (stream_mode="tasks") to print progress,
                   shows interrupt payloads, resumes with Command(resume=...). --diagram prints Mermaid.
swarm/config.py    Env settings (SWARM_MODEL, SWARM_EFFORT, MAX_DEV_ROUNDS), read at call time; loads .env.
swarm/state.py     TeamState TypedDict and reducers (operator.add lists, merge_files for code_files).
swarm/schemas.py   Pydantic structured outputs: BAResponse/Requirements, Architecture, DevOutput, QAReport.
swarm/llm.py       make_model() + ask_agent(role, schema, task) -> validated model; raises AgentError.
swarm/nodes.py     4 agent nodes (one LLM call each) + 4 human_* nodes (interrupt() only).
swarm/graph.py     build_graph(): nodes, edges, routing functions; AGENT_NODES display names.
swarm/output.py    output/<run-id>/ layout, markdown renderers, safe_src_path() / write_code_files().
prompts/<role>.md  System prompts (business_analyst, architect, developer, qa). Read on every call.
tests/             Offline tests: fakes.py (ScriptedAgents + drive()), graph flow, path safety, llm mock API.
output/            Generated runs (git-ignored).
```

## Invariants to keep

- **Never call an LLM in a node that calls `interrupt()`.** Resuming re-runs the interrupted node from the top. Agent nodes and human nodes stay separate.
- Agent nodes go through `ask_agent` only (tests monkeypatch `swarm.nodes.ask_agent`). Each agent returns a Pydantic model from `schemas.py`.
- State holds plain dicts (`model.model_dump()`) plus rendered markdown, not Pydantic objects, so the checkpointer serializes them without extra config.
- Human nodes interpret replies (`approve`, `stop`) via `nodes.is_command`; the CLI just passes text through. The graph is UI-agnostic.
- Every Developer file path goes through `output.safe_src_path`. Nothing may be written outside `output/<run-id>/src/`.
- QA pass/fail is derived in `nodes.qa` (verdict "pass" and no blocking issues and every criterion passes), not trusted blindly.
- `dev_round` counts rounds since the last escalation (reset by human guidance); `total_dev_rounds` never resets.

## Claude API gotchas (current models)

- Structured output uses `method="json_schema"` (native `output_config.format`). The default `function_calling` method forces `tool_choice`, which Claude Opus 5.5 / Sonnet 5.5 / Fable 5.1 reject with a 400.
- `ChatAnthropic` defaults `max_tokens` to the model maximum (128K for Opus 5.5), and the SDK refuses non-streaming requests that large, so `make_model()` sets `streaming=True` and `max_tokens=64_000`.
- Effort is passed as `effort=` and merged into `output_config` with the format. Opus 5.5 can't disable thinking and doesn't accept `temperature`.
- `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) is added only for models in `llm._FALLBACK_MODELS`. Don't add it for Haiku models.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest          # offline; pytest.ini limits collection to tests/
.venv/bin/python main.py --diagram
.venv/bin/python main.py            # needs ANTHROPIC_API_KEY in .env
```

## Adding an agent

1. Add a schema to `schemas.py` and a prompt to `prompts/<role>.md`.
2. Add an agent node (LLM call) and, if a human checkpoint is needed, a separate `human_*` node in `nodes.py`.
3. Wire both in `graph.py`, add the agent to `AGENT_NODES`, and extend the `interrupt` payload handling in `main.ask_human` if you add a new `kind`.
4. Extend `tests/test_graph_flow.py` with a scripted run through the new path.
