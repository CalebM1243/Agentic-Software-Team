"""Scripted stand-ins for the LLM and the human, so the graph runs offline."""

from langgraph.types import Command

from swarm.schemas import (
    AcceptanceCriterion,
    Architecture,
    BAResponse,
    CodeFile,
    Component,
    CriterionResult,
    DevOutput,
    DevTask,
    QAReport,
    Requirements,
    TechChoice,
    UserStory,
)


class ScriptedAgents:
    """Replaces `ask_agent`: returns the next scripted response for each role."""

    def __init__(self, script: dict[str, list]):
        self.script = {role: list(responses) for role, responses in script.items()}
        self.calls: list[tuple[str, str]] = []  # (role, task text)

    def __call__(self, role, schema, task):
        self.calls.append((role, task))
        response = self.script[role].pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, schema), f"{role} script returned {type(response)}"
        return response

    def tasks(self, role: str) -> list[str]:
        return [task for r, task in self.calls if r == role]


def drive(graph, thread: dict, first_input: dict, replies: list[str]) -> list[dict]:
    """Run the graph, answering each interrupt with the next reply.

    Returns the interrupt payloads in the order they were shown.
    """
    shown = []
    next_input = first_input
    while True:
        for _ in graph.stream(next_input, thread, stream_mode="tasks"):
            pass
        interrupts = graph.get_state(thread).interrupts
        if not interrupts:
            return shown
        shown.append(interrupts[0].value)
        next_input = Command(resume=replies.pop(0))


# --- Canned agent outputs ---------------------------------------------------


def ba_questions(*questions: str) -> BAResponse:
    return BAResponse(action="ask_questions", questions=list(questions), requirements=None)


def ba_requirements(title: str = "Temp converter") -> BAResponse:
    story = UserStory(
        id="US-1",
        title="Convert",
        as_a="user",
        i_want="to convert Celsius to Fahrenheit",
        so_that="I can read US weather",
        acceptance_criteria=[
            AcceptanceCriterion(id="AC-1.1", description="Given 100, then 212.0"),
        ],
    )
    return BAResponse(
        action="write_requirements",
        questions=[],
        requirements=Requirements(
            title=title,
            summary="Converts temperatures.",
            user_stories=[story],
            non_functional_requirements=["Python 3.11+"],
            assumptions=["Input is a number"],
            out_of_scope=["Kelvin"],
        ),
    )


def architecture(overview: str = "One module and a test.") -> Architecture:
    return Architecture(
        overview=overview,
        components=[
            Component(
                name="converter",
                responsibility="Math",
                interface="def c_to_f(c: float) -> float",
                files=["converter.py"],
            )
        ],
        tech_choices=[TechChoice(area="Language", choice="Python", rationale="Simple | quick")],
        tasks=[
            DevTask(
                id="T-1",
                title="Converter",
                description="Write it",
                files=["converter.py", "tests/test_converter.py"],
                acceptance_criteria=["AC-1.1"],
            )
        ],
    )


def dev_output(files: dict[str, str], notes: str = "Done.") -> DevOutput:
    return DevOutput(files=[CodeFile(path=p, content=c) for p, c in files.items()], notes=notes)


def qa_report(passed: bool, blocking: list[str] | None = None) -> QAReport:
    if blocking is None:
        blocking = [] if passed else ["c_to_f returns the wrong value"]
    return QAReport(
        verdict="pass" if passed else "fail",
        summary="Reviewed.",
        criteria_results=[
            CriterionResult(
                criterion_id="AC-1.1",
                status="pass" if passed else "fail",
                evidence="test_ac_1_1",
            )
        ],
        blocking_issues=blocking,
        refactor_suggestions=["Add a docstring"],
    )
