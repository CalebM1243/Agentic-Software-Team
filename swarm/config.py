"""Runtime settings, read from environment variables (and a .env file).

Values are read when the functions are called, not at import time, so tests
and the CLI can change them without re-importing anything.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
OUTPUT_DIR = PROJECT_ROOT / "output"

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_DEV_ROUNDS = 3

# The Business Analyst may ask at most this many questions per round.
MAX_QUESTIONS = 5

load_dotenv(PROJECT_ROOT / ".env")


def model_name() -> str:
    return os.getenv("SWARM_MODEL") or DEFAULT_MODEL


def effort() -> str | None:
    """Reasoning effort (low|medium|high|xhigh|max), or None to use the model default.

    Set SWARM_EFFORT to an empty string for models that don't support effort
    (e.g. claude-haiku-4-5).
    """
    value = os.getenv("SWARM_EFFORT", DEFAULT_EFFORT).strip().lower()
    return value or None


def max_dev_rounds() -> int:
    return int(os.getenv("MAX_DEV_ROUNDS", DEFAULT_MAX_DEV_ROUNDS))
