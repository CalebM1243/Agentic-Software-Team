"""The shared state that flows through the graph.

Every node receives the whole state and returns a partial dict of updates.
By default an update replaces the old value; fields annotated with a reducer
(e.g. `operator.add`) are combined with the old value instead.

Agent outputs are stored as plain dicts (`model.model_dump()`) rather than
Pydantic objects so the checkpointer can serialize them without extra setup.
"""

import operator
from typing import Annotated, TypedDict


def merge_files(old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Reducer for code files: new or changed files overwrite, the rest are kept."""
    return {**old, **new}


class TeamState(TypedDict, total=False):
    # Set by the CLI when the run starts.
    run_id: str
    output_dir: str
    idea: str

    # Business Analyst <-> user. A transcript of questions, answers, and
    # feedback on drafts: [{"speaker": ..., "text": ...}, ...]
    ba_conversation: Annotated[list[dict], operator.add]
    pending_questions: list[str]
    requirements: dict | None
    requirements_md: str
    requirements_approved: bool

    # Architect
    architecture: dict
    architecture_md: str
    architecture_feedback: Annotated[list[str], operator.add]
    architecture_approved: bool

    # Developer
    code_files: Annotated[dict[str, str], merge_files]
    dev_notes: str
    dev_round: int  # rounds since the last escalation; reset by human guidance
    total_dev_rounds: int
    human_guidance: Annotated[list[str], operator.add]
    rejected_paths: list[str]  # unsafe paths from the latest dev round

    # QA
    qa_report: dict
    qa_report_md: str
    qa_passed: bool

    # "passed" or "stopped" once the run ends.
    outcome: str
