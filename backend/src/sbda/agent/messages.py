"""Pure Anthropic-request assembly logic for the agentic loop.

No Anthropic SDK client, no I/O, no Temporal — this module builds plain dicts
and is exercised directly by `tests/unit/test_message_builder.py` (SPEC.md
§14.1). `sbda.temporal.activities.llm.call_claude` is the only caller that
actually sends these dicts over the network.

Model-specific rules baked in here (§9.1), because Sonnet 5 400s on any of
these being wrong:
  - no `budget_tokens`, `temperature`, `top_p`, `top_k`
  - no `{"role": "system"}` message — `system` is a top-level field
  - no assistant-turn prefill — the last message before a request is never
    role "assistant"
  - `cache_control` goes on the last tool definition and on the system
    prompt's (only) block, never on per-file content
"""

from __future__ import annotations

from dataclasses import dataclass

from sbda.agent.prompts import SYSTEM_PROMPT
from sbda.agent.tools import TOOLS
from sbda.config import settings


def build_system_blocks() -> list[dict]:
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_request(messages: list[dict], force_report: bool) -> dict:
    """Assemble the full Anthropic Messages API request body.

    `messages` must not itself contain a `{"role": "system"}` entry and must
    not end on an `"assistant"` turn — both are the caller's (the workflow's)
    responsibility to uphold, and are what `test_message_builder.py` pins.
    """
    if messages and messages[-1].get("role") == "assistant":
        raise ValueError("request must not end on an assistant turn (no prefill)")

    request: dict = {
        "model": settings.anthropic_model,
        "max_tokens": settings.anthropic_max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": settings.anthropic_effort},
        "system": build_system_blocks(),
        "tools": TOOLS,
        "messages": messages,
    }
    if force_report:
        request["tool_choice"] = {"type": "tool", "name": "write_report"}
    return request


def build_tool_result_block(tool_use_id: str, content: str, is_error: bool) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def build_tool_results_message(results: list[dict]) -> dict:
    """Batch every tool_result for one assistant turn into a single user
    message (§7.2's step 23) — splitting them across messages silently
    degrades Claude's parallel tool use.
    """
    return {"role": "user", "content": list(results)}


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, input_tokens, output_tokens, cache_read_tokens) -> "UsageTotals":
        return UsageTotals(
            input_tokens=self.input_tokens + (input_tokens or 0),
            output_tokens=self.output_tokens + (output_tokens or 0),
            cache_read_tokens=self.cache_read_tokens + (cache_read_tokens or 0),
        )


def accumulate_usage(totals: UsageTotals, usage: dict) -> UsageTotals:
    return totals.add(
        usage.get("input_tokens"),
        usage.get("output_tokens"),
        usage.get("cache_read_input_tokens"),
    )
