"""The graph's nodes.

There are two kinds of node, and they are kept strictly apart:

* Agent nodes (business_analyst, architect, developer, qa) call Claude once
  and return state updates. They never call `interrupt()`.
* Human nodes (human_*) only call `interrupt()` and turn the reply into state
  updates. When the graph is resumed with `Command(resume=...)`, LangGraph
  re-runs the interrupted node from the top. Keeping LLM calls out of these
  nodes means resuming never repeats (or pays for) an LLM call.

Each node takes the full TeamState and returns only the keys it changes.
"""

from langgraph.types import interrupt

from swarm import config
from swarm.llm import AgentError, ask_agent
from swarm.output import (
    architecture_to_md,
    qa_report_to_md,
    requirements_to_md,
    write_code_files,
    write_doc,
)
from swarm.schemas import Architecture, BAResponse, DevOutput, QAReport
from swarm.state import TeamState

APPROVE = "approve"
STOP = "stop"


def is_command(reply: str, word: str) -> bool:
    return reply.strip().lower().rstrip(".!") == word


# --- Helpers that build the task text each agent receives -------------------


def _section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip()}\n"


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))


def _conversation(turns: list[dict]) -> str:
    return "\n\n".join(f"**{turn['speaker']}:**\n{turn['text']}" for turn in turns)


def _files(files: dict[str, str]) -> str:
    return "\n\n".join(
        f'<file path="{path}">\n{content}\n</file>' for path, content in sorted(files.items())
    )


def _join(*sections: str) -> str:
    return "\n".join(s for s in sections if s)


# --- Business Analyst -------------------------------------------------------


def business_analyst(state: TeamState) -> dict:
    task = _join(
        _section("The user's idea", state["idea"]),
        state.get("ba_conversation")
        and _section("Conversation so far (oldest first)", _conversation(state["ba_conversation"])),
        state.get("requirements_md")
        and _section("Your current requirements draft", state["requirements_md"]),
    )
    response = ask_agent("business_analyst", BAResponse, task)

    if response.action == "ask_questions":
        questions = [q.strip() for q in response.questions if q.strip()][: config.MAX_QUESTIONS]
        if not questions:
            raise AgentError("The Business Analyst chose to ask questions but returned none.")
        return {
            "pending_questions": questions,
            "ba_conversation": [{"speaker": "Business Analyst", "text": _numbered(questions)}],
        }

    if response.requirements is None:
        raise AgentError("The Business Analyst chose to write requirements but returned none.")
    markdown = requirements_to_md(response.requirements)
    write_doc(state["output_dir"], "requirements.md", markdown)
    return {
        "pending_questions": [],
        "requirements": response.requirements.model_dump(),
        "requirements_md": markdown,
    }


def human_answers(state: TeamState) -> dict:
    answer = interrupt(
        {
            "kind": "questions",
            "agent": "Business Analyst",
            "questions": state["pending_questions"],
        }
    )
    return {"pending_questions": [], "ba_conversation": [{"speaker": "User", "text": answer}]}


def human_review_requirements(state: TeamState) -> dict:
    reply = interrupt(
        {
            "kind": "review",
            "agent": "Business Analyst",
            "title": "Requirements",
            "document": state["requirements_md"],
            "path": "docs/requirements.md",
        }
    )
    if is_command(reply, APPROVE):
        return {"requirements_approved": True}
    return {
        "requirements_approved": False,
        "ba_conversation": [
            {"speaker": "User (feedback on your requirements draft)", "text": reply}
        ],
    }


# --- Architect --------------------------------------------------------------


def architect(state: TeamState) -> dict:
    feedback = state.get("architecture_feedback")
    task = _join(
        _section("Approved requirements", state["requirements_md"]),
        feedback and _section("Your current architecture draft", state["architecture_md"]),
        feedback and _section("User feedback on your drafts (oldest first)", _numbered(feedback)),
    )
    arch = ask_agent("architect", Architecture, task)
    markdown = architecture_to_md(arch)
    write_doc(state["output_dir"], "architecture.md", markdown)
    return {"architecture": arch.model_dump(), "architecture_md": markdown}


def human_review_architecture(state: TeamState) -> dict:
    reply = interrupt(
        {
            "kind": "review",
            "agent": "Architect",
            "title": "Architecture",
            "document": state["architecture_md"],
            "path": "docs/architecture.md",
        }
    )
    if is_command(reply, APPROVE):
        return {"architecture_approved": True}
    return {"architecture_approved": False, "architecture_feedback": [reply]}


# --- Developer --------------------------------------------------------------


def developer(state: TeamState) -> dict:
    total_rounds = state.get("total_dev_rounds", 0) + 1
    code_files = state.get("code_files") or {}
    previously_rejected = state.get("rejected_paths")
    guidance = state.get("human_guidance")
    task = _join(
        _section("Approved requirements", state["requirements_md"]),
        _section("Approved architecture and task list", state["architecture_md"]),
        code_files and _section("Current code in src/", _files(code_files)),
        state.get("qa_report_md")
        and _section("Latest QA report: fix every blocking issue", state["qa_report_md"]),
        previously_rejected
        and _section(
            "Files from your last round that were rejected", _numbered(previously_rejected)
        ),
        guidance and _section("Guidance from the user (oldest first)", _numbered(guidance)),
        f"This is developer round {total_rounds}.",
    )
    out = ask_agent("developer", DevOutput, task)

    written, rejected = write_code_files(
        state["output_dir"], {f.path: f.content for f in out.files}
    )
    if not written and not code_files:
        raise AgentError(f"The Developer produced no usable files. Rejected: {rejected}")
    return {
        "code_files": written,
        "dev_notes": out.notes,
        "dev_round": state.get("dev_round", 0) + 1,
        "total_dev_rounds": total_rounds,
        "rejected_paths": rejected,
    }


# --- QA / Refactor ----------------------------------------------------------


def qa(state: TeamState) -> dict:
    task = _join(
        _section("Approved requirements", state["requirements_md"]),
        _section("Approved architecture", state["architecture_md"]),
        _section("Developer notes for this round", state.get("dev_notes", "")),
        _section("Code in src/", _files(state.get("code_files") or {})),
    )
    report = ask_agent("qa", QAReport, task)

    # Pass/fail is decided here, not just taken from the verdict, so a report
    # that says "pass" but lists blocking issues still fails.
    passed = (
        report.verdict == "pass"
        and not report.blocking_issues
        and all(c.status == "pass" for c in report.criteria_results)
    )
    markdown = qa_report_to_md(report, passed, state.get("total_dev_rounds", 0))
    write_doc(state["output_dir"], "qa_report.md", markdown)
    update = {"qa_report": report.model_dump(), "qa_report_md": markdown, "qa_passed": passed}
    if passed:
        update["outcome"] = "passed"
    return update


def human_escalation(state: TeamState) -> dict:
    reply = interrupt(
        {
            "kind": "escalation",
            "agent": "QA/Refactor",
            "rounds": state.get("dev_round", 0),
            "document": state["qa_report_md"],
            "path": "docs/qa_report.md",
        }
    )
    if is_command(reply, STOP):
        return {"outcome": "stopped"}
    # Guidance gives the Developer a fresh budget of MAX_DEV_ROUNDS rounds.
    return {"human_guidance": [reply], "dev_round": 0}
