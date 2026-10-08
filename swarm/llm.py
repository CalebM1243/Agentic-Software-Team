"""The one place that talks to Claude.

`ask_agent(role, schema, task)` sends the role's system prompt (from
prompts/<role>.md) plus a task description, and returns a validated instance
of `schema`.
"""

from typing import TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from swarm import config

T = TypeVar("T", bound=BaseModel)

# Generous room for the Developer, who returns whole files. Streaming is on
# because the Anthropic SDK refuses non-streaming requests this large.
MAX_TOKENS = 64_000

# These models run safety classifiers that can decline a request
# (stop_reason "refusal"). With `fallbacks: "default"` the API retries a
# declined request on the model Anthropic recommends for that refusal
# category, instead of returning the refusal.
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AgentError(RuntimeError):
    """An agent call finished but didn't produce usable output."""


def load_prompt(role: str) -> str:
    # Read on every call, so edits to prompts/*.md apply to the next agent turn.
    return (config.PROMPTS_DIR / f"{role}.md").read_text(encoding="utf-8")


def make_model() -> ChatAnthropic:
    name = config.model_name()
    kwargs = {}
    if effort := config.effort():
        kwargs["effort"] = effort
    if name.startswith(_FALLBACK_MODELS):
        kwargs["betas"] = [_FALLBACK_BETA]
        kwargs["model_kwargs"] = {"fallbacks": "default"}
    return ChatAnthropic(
        model=name,
        max_tokens=MAX_TOKENS,
        streaming=True,
        max_retries=3,
        **kwargs,
    )


def ask_agent(role: str, schema: type[T], task: str) -> T:
    # method="json_schema" uses Claude's native structured outputs. The default
    # ("function_calling") forces a tool call, which newer models reject.
    model = make_model().with_structured_output(schema, method="json_schema", include_raw=True)
    result = model.invoke([SystemMessage(load_prompt(role)), HumanMessage(task)])

    stop_reason = result["raw"].response_metadata.get("stop_reason")
    if stop_reason == "refusal":
        raise AgentError(f"The model declined the {role} request (stop_reason=refusal).")
    if stop_reason == "max_tokens":
        raise AgentError(f"The {role} response hit max_tokens ({MAX_TOKENS}) and was cut off.")
    if result["parsing_error"] is not None:
        raise AgentError(
            f"The {role} response didn't match {schema.__name__}: {result['parsing_error']}"
        )
    return result["parsed"]
