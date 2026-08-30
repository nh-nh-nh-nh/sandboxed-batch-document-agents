"""Tests for `sbda.agent.messages` — Anthropic request assembly. SPEC.md §14.1."""

from __future__ import annotations

import pytest

from sbda.agent.messages import (
    UsageTotals,
    accumulate_usage,
    build_request,
    build_tool_result_block,
    build_tool_results_message,
)
from sbda.agent.tools import TOOLS


def _user_message(text="hi"):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def test_model_is_claude_sonnet_5():
    req = build_request([_user_message()], force_report=False)
    assert req["model"] == "claude-sonnet-5"


def test_thinking_is_adaptive():
    req = build_request([_user_message()], force_report=False)
    assert req["thinking"] == {"type": "adaptive"}


def test_no_budget_tokens_anywhere():
    req = build_request([_user_message()], force_report=False)
    assert "budget_tokens" not in req
    assert "budget_tokens" not in req["thinking"]


def test_no_temperature_top_p_top_k():
    req = build_request([_user_message()], force_report=False)
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in req


def test_output_config_effort_medium():
    req = build_request([_user_message()], force_report=False)
    assert req["output_config"] == {"effort": "medium"}


def test_last_message_never_assistant():
    with pytest.raises(ValueError):
        build_request([{"role": "assistant", "content": []}], force_report=False)


def test_no_system_role_message():
    req = build_request([_user_message()], force_report=False)
    for m in req["messages"]:
        assert m.get("role") != "system"


def test_top_level_system_is_list_with_cache_control_on_final_block():
    req = build_request([_user_message()], force_report=False)
    assert isinstance(req["system"], list)
    assert req["system"][-1]["cache_control"] == {"type": "ephemeral"}


def test_cache_control_on_last_tool_definition_only():
    req = build_request([_user_message()], force_report=False)
    tools = req["tools"]
    for t in tools[:-1]:
        assert "cache_control" not in t
    assert tools[-1].get("cache_control") == {"type": "ephemeral"}


def test_tool_list_byte_identical_across_turns():
    req1 = build_request([_user_message("turn 1")], force_report=False)
    req2 = build_request([_user_message("turn 1"), {"role": "assistant", "content": []}, _user_message("turn 2")], force_report=False)
    assert req1["tools"] == req2["tools"]
    assert req1["tools"] is TOOLS
    assert req2["tools"] is TOOLS


def test_system_prompt_has_no_per_file_substitution():
    req = build_request([_user_message("Analyze /work/input/foo.csv")], force_report=False)
    system_text = req["system"][0]["text"]
    assert "foo.csv" not in system_text
    assert "/work/input/" in system_text  # generic mention is fine
    # the filename only appears in the first user message
    assert "foo.csv" in req["messages"][0]["content"][0]["text"]


def test_n_tool_use_blocks_produce_one_user_message_with_n_tool_results():
    blocks = [
        {"type": "tool_use", "id": "toolu_1", "name": "run_python", "input": {}},
        {"type": "tool_use", "id": "toolu_2", "name": "read_file", "input": {}},
    ]
    results = [
        build_tool_result_block(blocks[0]["id"], "<stdout>ok</stdout>", is_error=False),
        build_tool_result_block(blocks[1]["id"], "<stdout>ok2</stdout>", is_error=False),
    ]
    msg = build_tool_results_message(results)
    assert msg["role"] == "user"
    assert len(msg["content"]) == 2
    assert all(b["type"] == "tool_result" for b in msg["content"])


def test_failed_tool_produces_is_error_true_not_dropped():
    result = build_tool_result_block("toolu_1", "<stdout></stdout><stderr>boom</stderr>exit_code: 1", is_error=True)
    msg = build_tool_results_message([result])
    assert msg["content"][0]["is_error"] is True


def test_tool_use_id_matches_originating_block():
    block_id = "toolu_abc123"
    result = build_tool_result_block(block_id, "content", is_error=False)
    assert result["tool_use_id"] == block_id


def test_force_report_sets_tool_choice():
    req = build_request([_user_message()], force_report=True)
    assert req["tool_choice"] == {"type": "tool", "name": "write_report"}


def test_force_report_false_omits_tool_choice():
    req = build_request([_user_message()], force_report=False)
    assert "tool_choice" not in req


def test_forcing_report_does_not_alter_tools_or_system():
    req_normal = build_request([_user_message()], force_report=False)
    req_forced = build_request([_user_message()], force_report=True)
    assert req_normal["tools"] == req_forced["tools"]
    assert req_normal["system"] == req_forced["system"]


def test_usage_accumulation_across_turns():
    totals = UsageTotals()
    totals = accumulate_usage(totals, {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50})
    totals = accumulate_usage(totals, {"input_tokens": 30, "output_tokens": 10, "cache_read_input_tokens": None})
    assert totals.input_tokens == 130
    assert totals.output_tokens == 30
    assert totals.cache_read_tokens == 50


def test_usage_none_cache_field_treated_as_zero():
    totals = accumulate_usage(UsageTotals(), {"input_tokens": 5, "output_tokens": 5, "cache_read_input_tokens": None})
    assert totals.cache_read_tokens == 0
