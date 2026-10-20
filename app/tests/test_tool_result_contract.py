"""Tool-call outcome contract: success, failure, timeout, and empty success."""

from travel_agent.agents.utils import (
    ToolResultOutcome,
    _is_retryable_tool_error,
    classify_tool_result,
)


def test_tool_success_with_content_is_content():
    outcome, reason = classify_tool_result(
        "free_web_search",
        {"success": True, "results": [{"title": "楼外楼", "url": "https://example.com"}]},
    )
    assert outcome is ToolResultOutcome.CONTENT
    assert reason == ""


def test_tool_reported_failure_is_failed():
    outcome, reason = classify_tool_result(
        "global_route_search",
        {"success": False, "error": "upstream 502"},
    )
    assert outcome is ToolResultOutcome.FAILED
    assert "502" in reason


def test_tool_timeout_is_retryable_failure():
    assert _is_retryable_tool_error("request timeout after 60s")
    assert _is_retryable_tool_error("connection reset by peer")
    assert not _is_retryable_tool_error("quota exceeded")
    assert not _is_retryable_tool_error("invalid api key")
    outcome, reason = classify_tool_result(
        "open-meteo",
        {"success": False, "error": "request timeout"},
    )
    assert outcome is ToolResultOutcome.FAILED
    assert "timeout" in reason


def test_success_with_no_results_is_empty_success_not_failure():
    outcome, reason = classify_tool_result(
        "free_web_search",
        {"success": True, "results": []},
    )
    assert outcome is ToolResultOutcome.EMPTY_SUCCESS
    assert "结果集为空" in reason


def test_unstructured_result_is_failed():
    outcome, reason = classify_tool_result("open-meteo", "plain text")
    assert outcome is ToolResultOutcome.FAILED
    assert "结构化" in reason


def test_error_text_behind_success_flag_is_failed():
    outcome, _ = classify_tool_result(
        "free_web_search",
        {"success": True, "results": [{"title": "error: rate limited"}]},
    )
    assert outcome is ToolResultOutcome.FAILED
