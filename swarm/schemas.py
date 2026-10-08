"""Structured outputs for each agent.

Every agent answers with one of these Pydantic models (via
`with_structured_output`), so the handoff between agents always has a fixed
shape. Field descriptions are sent to the model as part of the JSON schema,
so they double as instructions.
"""

from typing import Literal

from pydantic import BaseModel, Field

# --- Business Analyst -------------------------------------------------------


class AcceptanceCriterion(BaseModel):
    id: str = Field(description="Stable ID, e.g. 'AC-1.2' (story 1, criterion 2).")
    description: str = Field(
        description="A testable statement, ideally Given/When/Then, with concrete values."
    )


class UserStory(BaseModel):
    id: str = Field(description="Stable ID, e.g. 'US-1'.")
    title: str
    as_a: str = Field(description="The user role.")
    i_want: str = Field(description="The capability the user wants.")
    so_that: str = Field(description="The benefit to the user.")
    acceptance_criteria: list[AcceptanceCriterion]


class Requirements(BaseModel):
    title: str = Field(description="Short project name.")
    summary: str = Field(description="One or two paragraphs describing the product.")
    user_stories: list[UserStory]
    non_functional_requirements: list[str]
    assumptions: list[str]
    out_of_scope: list[str]


class BAResponse(BaseModel):
    action: Literal["ask_questions", "write_requirements"] = Field(
        description="'ask_questions' if you still need information from the user, "
        "otherwise 'write_requirements'."
    )
    questions: list[str] = Field(
        description="Clarifying questions for the user (at most 5). "
        "Empty when action is 'write_requirements'."
    )
    requirements: Requirements | None = Field(
        description="The requirements document. Null when action is 'ask_questions'."
    )


# --- Architect --------------------------------------------------------------


class Component(BaseModel):
    name: str
    responsibility: str
    interface: str = Field(
        description="The public interface: function signatures, CLI usage, or data formats."
    )
    files: list[str] = Field(description="Files (relative to src/) that implement it.")


class TechChoice(BaseModel):
    area: str = Field(description="e.g. 'Language', 'Testing', 'CLI parsing'.")
    choice: str
    rationale: str


class DevTask(BaseModel):
    id: str = Field(description="Stable ID, e.g. 'T-1'.")
    title: str
    description: str
    files: list[str] = Field(description="Files (relative to src/) to create or change.")
    acceptance_criteria: list[str] = Field(description="IDs of the criteria this task covers.")


class Architecture(BaseModel):
    overview: str
    components: list[Component]
    tech_choices: list[TechChoice]
    tasks: list[DevTask] = Field(description="Ordered list of tasks for the developer.")


# --- Developer --------------------------------------------------------------


class CodeFile(BaseModel):
    path: str = Field(
        description="Path relative to the project's src/ directory, e.g. 'converter.py' "
        "or 'tests/test_converter.py'. No absolute paths and no '..'."
    )
    content: str = Field(description="The complete file contents.")


class DevOutput(BaseModel):
    files: list[CodeFile] = Field(
        description="Every file you created or changed this round, with full contents. "
        "Files you leave out stay as they are."
    )
    notes: str = Field(
        description="What you did this round, how each QA issue was addressed, "
        "and how to run the program and its tests."
    )


# --- QA ---------------------------------------------------------------------


class CriterionResult(BaseModel):
    criterion_id: str = Field(description="Acceptance criterion ID, e.g. 'AC-1.2'.")
    status: Literal["pass", "fail"]
    evidence: str = Field(description="Where in the code/tests this is (or isn't) satisfied.")


class QAReport(BaseModel):
    verdict: Literal["pass", "fail"]
    summary: str
    criteria_results: list[CriterionResult] = Field(
        description="One entry per acceptance criterion in the requirements."
    )
    blocking_issues: list[str] = Field(
        description="Problems that must be fixed before release. Empty if none."
    )
    refactor_suggestions: list[str] = Field(
        description="Non-blocking improvements. These never cause a fail."
    )
