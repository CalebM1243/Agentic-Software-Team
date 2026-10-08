"""Terminal CLI for the simulated software team.

    python main.py            # start a new run
    python main.py --diagram  # print the graph as Mermaid
"""

import argparse
import os
import sys

from langgraph.types import Command

from swarm import config
from swarm.graph import AGENT_NODES, build_graph
from swarm.output import create_run_dir, new_run_id

RULE = "-" * 72


def read_multiline(prompt: str, commands: tuple[str, ...] = ()) -> str:
    """Read lines until an empty line.

    If the first line is exactly one of `commands` (e.g. "approve"), return it
    right away. Returns "" on end-of-input with nothing typed.
    """
    print(f"\n{prompt}\n(finish with an empty line)")
    lines: list[str] = []
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            continue  # ignore blank lines before the answer starts
        if not lines and line.strip().lower() in commands:
            return line.strip().lower()
        lines.append(line)
    return "\n".join(lines).strip()


def ask_human(request: dict, run_dir: str) -> str:
    """Show an interrupt payload to the user and return their reply."""
    kind = request["kind"]
    print(f"\n{RULE}")
    if kind == "questions":
        print(f"[{request['agent']}] has some questions:\n")
        for i, question in enumerate(request["questions"], 1):
            print(f"  {i}. {question}")
        reply = read_multiline("Your answers:")
    elif kind == "review":
        print(f"[{request['agent']}] {request['title']} draft "
              f"(saved to {os.path.join(run_dir, request['path'])}):\n")
        print(request["document"])
        print(RULE)
        reply = read_multiline(
            f'Type "approve" to approve, or write feedback for the {request["agent"]}:',
            commands=("approve",),
        )
    elif kind == "escalation":
        rounds = request["rounds"]
        print(f"[{request['agent']}] The code has failed QA {rounds} "
              f"round{'s' if rounds != 1 else ''} in a row. Latest report:\n")
        print(request["document"])
        print(RULE)
        reply = read_multiline(
            'Type "stop" to end the run, or write guidance for the Developer:',
            commands=("stop",),
        )
    else:
        raise ValueError(f"Unknown interrupt kind: {kind}")

    if not reply:
        sys.exit("\nNo input received. Exiting.")
    return reply


def show_progress(event: dict) -> None:
    """Print a line when an agent starts or finishes (from stream_mode="tasks")."""
    name = event["name"]
    if name not in AGENT_NODES:
        return
    agent = AGENT_NODES[name]
    if "input" in event:  # task started
        if name == "developer":
            round_no = event["input"].get("total_dev_rounds", 0) + 1
            print(f"\n[{agent}] working (round {round_no})...", flush=True)
        else:
            print(f"\n[{agent}] working...", flush=True)
    elif not event.get("error"):  # task finished
        update = dict(event.get("result") or {})
        if name == "developer":
            for path in sorted(update.get("code_files", {})):
                print(f"  wrote src/{path}")
            for problem in update.get("rejected_paths", []):
                print(f"  REJECTED unsafe path {problem}")
        elif name == "qa":
            blocking = len(update.get("qa_report", {}).get("blocking_issues", []))
            result = "PASS" if update.get("qa_passed") else "FAIL"
            print(f"  QA result: {result} ({blocking} blocking "
                  f"issue{'s' if blocking != 1 else ''})")


def run(graph) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    print("Simulated software team")
    print(f"model={config.model_name()} effort={config.effort() or 'default'} "
          f"max_dev_rounds={config.max_dev_rounds()}")
    idea = read_multiline("What do you want built?")
    if not idea:
        sys.exit("Nothing to build. Exiting.")

    run_id = new_run_id()
    run_dir = str(create_run_dir(run_id))
    print(f"\nRun {run_id}: writing to {run_dir}")

    # The thread_id tells the checkpointer which run's state to load on resume.
    thread = {"configurable": {"thread_id": run_id}}
    next_input: dict | Command | None = {"run_id": run_id, "output_dir": run_dir, "idea": idea}

    while True:
        try:
            for event in graph.stream(next_input, thread, stream_mode="tasks"):
                show_progress(event)
        except Exception as exc:  # noqa: BLE001 - offer a retry for any agent failure
            print(f"\n[error] {type(exc).__name__}: {exc}")
            try:
                choice = input('Type "retry" to run that step again, or press Enter to quit: ')
            except EOFError:
                choice = ""
            if choice.strip().lower() != "retry":
                sys.exit(f"Stopped. Partial output is in {run_dir}")
            next_input = None  # None = continue from the last checkpoint
            continue

        snapshot = graph.get_state(thread)
        if not snapshot.interrupts:
            break
        reply = ask_human(snapshot.interrupts[0].value, run_dir)
        next_input = Command(resume=reply)

    state = graph.get_state(thread).values
    outcome = state.get("outcome", "finished")
    print(f"\n{RULE}\nRun {outcome} after {state.get('total_dev_rounds', 0)} developer round(s).")
    print(f"Docs: {run_dir}/docs/")
    print(f"Code: {run_dir}/src/")
    for path in sorted(state.get("code_files", {})):
        print(f"  {path}")
    if state.get("dev_notes"):
        print(f"\nDeveloper notes:\n{state['dev_notes']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the simulated software team.")
    parser.add_argument("--diagram", action="store_true", help="print the graph as Mermaid")
    args = parser.parse_args()

    graph = build_graph()
    if args.diagram:
        print(graph.get_graph().draw_mermaid())
        return
    try:
        run(graph)
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")


if __name__ == "__main__":
    main()
