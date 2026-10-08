"""Everything that writes to output/<run-id>/.

    output/<run-id>/
      docs/requirements.md
      docs/architecture.md
      docs/qa_report.md
      src/...              <- generated code, and nothing outside it
"""

import re
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

from swarm import config
from swarm.schemas import Architecture, QAReport, Requirements

# --- Run directories --------------------------------------------------------


def new_run_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def create_run_dir(run_id: str, base: Path | None = None) -> Path:
    run_dir = (base or config.OUTPUT_DIR) / run_id
    (run_dir / "docs").mkdir(parents=True, exist_ok=True)
    (run_dir / "src").mkdir(exist_ok=True)
    return run_dir


def write_doc(output_dir: str, name: str, markdown: str) -> Path:
    path = Path(output_dir) / "docs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


# --- Generated code ---------------------------------------------------------


class UnsafePathError(ValueError):
    pass


def safe_src_path(src_root: Path, raw_path: str) -> Path:
    """Map a path suggested by the Developer to a file inside `src_root`.

    Raises UnsafePathError for anything that could land outside it: absolute
    paths, drive letters, '..' segments, or symlinks that point elsewhere.
    """
    if not raw_path or not raw_path.strip() or "\x00" in raw_path:
        raise UnsafePathError("empty or invalid path")

    normalized = raw_path.strip().replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise UnsafePathError("absolute paths are not allowed")

    parts = PurePosixPath(normalized).parts  # drops '.' and empty segments
    if ".." in parts:
        raise UnsafePathError("'..' is not allowed")
    if parts and parts[0] == "src":  # models often include the src/ prefix
        parts = parts[1:]
    if not parts:
        raise UnsafePathError("path has no file name")

    root = src_root.resolve()
    target = root.joinpath(*parts).resolve()  # resolve() follows symlinks
    if target == root or not target.is_relative_to(root):
        raise UnsafePathError("path escapes src/")
    return target


def write_code_files(output_dir: str, files: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Write files under <output_dir>/src.

    Returns ({clean relative path: content} for files written,
             ["<raw path>: <reason>"] for files rejected).
    """
    src_root = Path(output_dir) / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    rejected: list[str] = []
    for raw_path, content in files.items():
        try:
            target = safe_src_path(src_root, raw_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except (UnsafePathError, OSError) as exc:
            rejected.append(f"{raw_path}: {exc}")
            continue
        written[target.relative_to(src_root.resolve()).as_posix()] = content
    return written, rejected


# --- Markdown renderers -----------------------------------------------------


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def _cell(text: str) -> str:
    """Make text safe for a single markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def requirements_to_md(req: Requirements) -> str:
    lines = [f"# Requirements: {req.title}", "", req.summary, "", "## User stories", ""]
    for story in req.user_stories:
        lines += [
            f"### {story.id}: {story.title}",
            "",
            f"As a **{story.as_a}**, I want **{story.i_want}**, so that **{story.so_that}**.",
            "",
            "Acceptance criteria:",
            "",
        ]
        lines += [f"- **{ac.id}**: {ac.description}" for ac in story.acceptance_criteria]
        lines.append("")
    lines += [
        "## Non-functional requirements",
        "",
        _bullets(req.non_functional_requirements),
        "",
        "## Assumptions",
        "",
        _bullets(req.assumptions),
        "",
        "## Out of scope",
        "",
        _bullets(req.out_of_scope),
        "",
    ]
    return "\n".join(lines)


def architecture_to_md(arch: Architecture) -> str:
    lines = ["# Architecture", "", arch.overview, "", "## Components", ""]
    for comp in arch.components:
        lines += [
            f"### {comp.name}",
            "",
            comp.responsibility,
            "",
            f"Files: {', '.join(f'`{f}`' for f in comp.files) or 'none'}",
            "",
            "Interface:",
            "",
            "```",
            comp.interface,
            "```",
            "",
        ]
    lines += ["## Tech choices", "", "| Area | Choice | Rationale |", "| --- | --- | --- |"]
    lines += [
        f"| {_cell(t.area)} | {_cell(t.choice)} | {_cell(t.rationale)} |" for t in arch.tech_choices
    ]
    lines += ["", "## Tasks", ""]
    for i, task in enumerate(arch.tasks, 1):
        lines += [
            f"{i}. **{task.id}: {task.title}**: {task.description}",
            f"   - Files: {', '.join(f'`{f}`' for f in task.files) or 'none'}",
            f"   - Covers: {', '.join(task.acceptance_criteria) or 'none'}",
        ]
    lines.append("")
    return "\n".join(lines)


def qa_report_to_md(report: QAReport, passed: bool, dev_round: int) -> str:
    lines = [
        f"# QA report (developer round {dev_round})",
        "",
        f"**Result: {'PASS' if passed else 'FAIL'}**",
        "",
        report.summary,
        "",
        "## Acceptance criteria",
        "",
        "| Criterion | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {_cell(c.criterion_id)} | {c.status.upper()} | {_cell(c.evidence)} |"
        for c in report.criteria_results
    ]
    lines += [
        "",
        "## Blocking issues",
        "",
        _bullets(report.blocking_issues),
        "",
        "## Refactor suggestions (non-blocking)",
        "",
        _bullets(report.refactor_suggestions),
        "",
    ]
    return "\n".join(lines)
