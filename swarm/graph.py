"""Wires the nodes into a LangGraph StateGraph.

Routing functions read the state and return a label; the dict passed to
`add_conditional_edges` maps each label to the next node. The labels also
show up on the edges in the --diagram output.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from swarm import config, nodes
from swarm.state import TeamState

# Nodes that call an LLM, with the name the CLI shows while they work.
AGENT_NODES = {
    "business_analyst": "Business Analyst",
    "architect": "Architect",
    "developer": "Developer",
    "qa": "QA/Refactor",
}


def after_business_analyst(state: TeamState) -> str:
    return "questions" if state.get("pending_questions") else "draft ready"


def after_requirements_review(state: TeamState) -> str:
    return "approve" if state.get("requirements_approved") else "feedback"


def after_architecture_review(state: TeamState) -> str:
    return "approve" if state.get("architecture_approved") else "feedback"


def after_qa(state: TeamState) -> str:
    if state.get("qa_passed"):
        return "pass"
    if state.get("dev_round", 0) < config.max_dev_rounds():
        return "fail"
    return "escalate"


def after_escalation(state: TeamState) -> str:
    return "stop" if state.get("outcome") == "stopped" else "guidance"


def build_graph(checkpointer=None):
    """Build and compile the team graph.

    A checkpointer is required for interrupt()/resume. The default
    InMemorySaver keeps state for the life of the process; each run uses its
    own thread_id.
    """
    graph = StateGraph(TeamState)

    graph.add_node("business_analyst", nodes.business_analyst)
    graph.add_node("human_answers", nodes.human_answers)
    graph.add_node("human_review_requirements", nodes.human_review_requirements)
    graph.add_node("architect", nodes.architect)
    graph.add_node("human_review_architecture", nodes.human_review_architecture)
    graph.add_node("developer", nodes.developer)
    graph.add_node("qa", nodes.qa)
    graph.add_node("human_escalation", nodes.human_escalation)

    graph.add_edge(START, "business_analyst")
    graph.add_conditional_edges(
        "business_analyst",
        after_business_analyst,
        {"questions": "human_answers", "draft ready": "human_review_requirements"},
    )
    graph.add_edge("human_answers", "business_analyst")
    graph.add_conditional_edges(
        "human_review_requirements",
        after_requirements_review,
        {"feedback": "business_analyst", "approve": "architect"},
    )

    graph.add_edge("architect", "human_review_architecture")
    graph.add_conditional_edges(
        "human_review_architecture",
        after_architecture_review,
        {"feedback": "architect", "approve": "developer"},
    )

    graph.add_edge("developer", "qa")
    graph.add_conditional_edges(
        "qa",
        after_qa,
        {"pass": END, "fail": "developer", "escalate": "human_escalation"},
    )
    graph.add_conditional_edges(
        "human_escalation",
        after_escalation,
        {"guidance": "developer", "stop": END},
    )

    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
