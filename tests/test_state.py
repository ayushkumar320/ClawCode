"""Tests for agent.state — JSON round-trip + defaults."""

from __future__ import annotations

from agent.state import AgentState


def test_defaults() -> None:
    s = AgentState(task_id="t1", repo_slug="o/r", user_prompt="do thing")
    assert s.messages == []
    assert s.retries == 0
    assert s.tests_passed is False
    assert s.version == 2


def test_round_trip() -> None:
    s = AgentState(
        task_id="t1",
        repo_slug="o/r",
        user_prompt="do thing",
        messages=[{"role": "user", "content": "x"}],
        retries=2,
        tests_passed=True,
    )
    js = s.model_dump_json()
    back = AgentState.model_validate_json(js)
    assert back == s
