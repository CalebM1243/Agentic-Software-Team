"""End-to-end runs of the graph with a scripted LLM and scripted human replies."""

import pytest

from swarm import nodes
from swarm.graph import build_graph
from swarm.llm import AgentError
from swarm.output import create_run_dir
from tests.fakes import (
    ScriptedAgents,
    architecture,
    ba_questions,
    ba_requirements,
    dev_output,
    drive,
    qa_report,
)


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_DEV_ROUNDS", "3")
    run_dir = create_run_dir("test-run", base=tmp_path)
    thread = {"configurable": {"thread_id": "test-run"}}
    first_input = {"run_id": "test-run", "output_dir": str(run_dir), "idea": "C to F converter"}
    return run_dir, thread, first_input


def install(monkeypatch, script) -> ScriptedAgents:
    agents = ScriptedAgents(script)
    monkeypatch.setattr(nodes, "ask_agent", agents)
    return agents


def test_full_loop_with_feedback_failures_and_escalation(run, monkeypatch):
    run_dir, thread, first_input = run
    bad = {"converter.py": "def c_to_f(c): return c\n"}
    agents = install(
        monkeypatch,
        {
            "business_analyst": [
                ba_questions("Decimals?", "Negative numbers?"),
                ba_requirements("Draft 1"),
                ba_requirements("Draft 2"),
            ],
            "architect": [architecture("Arch v1"), architecture("Arch v2")],
            "developer": [
                dev_output({**bad, "../escape.py": "boom"}),
                dev_output(bad),
                dev_output(bad),
                dev_output({"converter.py": "def c_to_f(c): return c * 9 / 5 + 32\n"}),
            ],
            "qa": [qa_report(False), qa_report(False), qa_report(False), qa_report(True)],
        },
    )
    graph = build_graph()

    shown = drive(
        graph,
        thread,
        first_input,
        [
            "Yes, one decimal. Negatives allowed.",
            "Please add a story for invalid input.",
            "approve",
            "Use a single module.",
            "APPROVE",
            "The formula is c * 9 / 5 + 32.",
        ],
    )

    # The human saw each interrupt in the expected order.
    assert [(s["kind"], s.get("title")) for s in shown] == [
        ("questions", None),
        ("review", "Requirements"),
        ("review", "Requirements"),
        ("review", "Architecture"),
        ("review", "Architecture"),
        ("escalation", None),
    ]
    assert shown[0]["questions"] == ["Decimals?", "Negative numbers?"]
    assert shown[5]["rounds"] == 3

    # Each agent ran exactly as often as the flow requires: resuming an
    # interrupt never re-ran an LLM call.
    assert [len(agents.tasks(r)) for r in ("business_analyst", "architect", "developer", "qa")] == [
        3, 2, 4, 4,
    ]

    # Context flowed to the right agents.
    ba = agents.tasks("business_analyst")
    assert "Yes, one decimal." in ba[1]
    assert "add a story for invalid input" in ba[2] and "Draft 1" in ba[2]
    arch = agents.tasks("architect")
    assert "Use a single module." in arch[1] and "Arch v1" in arch[1]
    dev = agents.tasks("developer")
    assert "Latest QA report" not in dev[0]
    assert "c_to_f returns the wrong value" in dev[1]
    assert "../escape.py" in dev[1]  # told about the rejected path
    assert "The formula is c * 9 / 5 + 32." in dev[3]

    # Final state and files on disk.
    state = graph.get_state(thread).values
    assert state["outcome"] == "passed"
    assert state["total_dev_rounds"] == 4
    assert state["code_files"] == {"converter.py": "def c_to_f(c): return c * 9 / 5 + 32\n"}
    assert "Draft 2" in (run_dir / "docs" / "requirements.md").read_text()
    assert "Arch v2" in (run_dir / "docs" / "architecture.md").read_text()
    assert "**Result: PASS**" in (run_dir / "docs" / "qa_report.md").read_text()
    assert (run_dir / "src" / "converter.py").exists()
    assert not (run_dir / "escape.py").exists()


def test_stop_at_escalation(run, monkeypatch):
    _, thread, first_input = run
    monkeypatch.setenv("MAX_DEV_ROUNDS", "1")
    install(
        monkeypatch,
        {
            "business_analyst": [ba_requirements()],
            "architect": [architecture()],
            "developer": [dev_output({"converter.py": "x = 1\n"})],
            "qa": [qa_report(False)],
        },
    )
    graph = build_graph()

    shown = drive(graph, thread, first_input, ["approve", "approve", "stop"])

    assert [s["kind"] for s in shown] == ["review", "review", "escalation"]
    assert graph.get_state(thread).values["outcome"] == "stopped"


def test_pass_verdict_with_blocking_issues_still_fails(run, monkeypatch):
    _, thread, first_input = run
    monkeypatch.setenv("MAX_DEV_ROUNDS", "1")
    install(
        monkeypatch,
        {
            "business_analyst": [ba_requirements()],
            "architect": [architecture()],
            "developer": [dev_output({"converter.py": "x = 1\n"})],
            "qa": [qa_report(True, blocking=["crashes on empty input"])],
        },
    )
    graph = build_graph()

    shown = drive(graph, thread, first_input, ["approve", "approve", "stop"])

    assert shown[-1]["kind"] == "escalation"
    assert graph.get_state(thread).values["qa_passed"] is False


def test_failed_agent_call_can_be_retried_from_checkpoint(run, monkeypatch):
    _, thread, first_input = run
    agents = install(
        monkeypatch,
        {
            "business_analyst": [ba_requirements()],
            "architect": [AgentError("transient"), architecture()],
            "developer": [dev_output({"converter.py": "x = 1\n"})],
            "qa": [qa_report(True)],
        },
    )
    graph = build_graph()

    with pytest.raises(AgentError):
        drive(graph, thread, first_input, ["approve"])

    # Streaming None continues from the last checkpoint, re-running the
    # failed node. This is what the CLI's "retry" does.
    shown = drive(graph, thread, None, ["approve"])

    assert [s["title"] for s in shown] == ["Architecture"]
    assert graph.get_state(thread).values["outcome"] == "passed"
    assert len(agents.tasks("business_analyst")) == 1
    assert len(agents.tasks("architect")) == 2


def test_ba_questions_are_capped_at_five(run, monkeypatch):
    _, thread, first_input = run
    install(
        monkeypatch,
        {"business_analyst": [ba_questions(*[f"Q{i}?" for i in range(1, 9)])]},
    )
    graph = build_graph()

    for _ in graph.stream(first_input, thread, stream_mode="tasks"):
        pass

    assert graph.get_state(thread).interrupts[0].value["questions"] == [
        "Q1?", "Q2?", "Q3?", "Q4?", "Q5?",
    ]


def test_diagram_shows_every_node():
    mermaid = build_graph().get_graph().draw_mermaid()
    for node in (
        "business_analyst",
        "human_answers",
        "human_review_requirements",
        "architect",
        "human_review_architecture",
        "developer",
        "qa",
        "human_escalation",
    ):
        assert node in mermaid
