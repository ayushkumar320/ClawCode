"""Tests for agent.llm — ChatGroq factory; LangChain is mocked."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent import llm


def _fake_chatgroq_factory():
    """Return a MagicMock standing in for ChatGroq, recording each instance."""
    instances = []

    def factory(**kwargs):
        bound = MagicMock(name=f"bound-{kwargs['model']}")
        bound.model = kwargs["model"]
        bound.with_fallbacks = MagicMock(
            side_effect=lambda fbs: ("with_fallbacks", bound, tuple(fbs))
        )
        inst = MagicMock(name=f"inst-{kwargs['model']}")
        inst.bind_tools = MagicMock(return_value=bound)
        instances.append((kwargs, inst, bound))
        return inst

    return factory, instances


def test_build_chat_model_single_when_no_fallbacks(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))

    out = llm.build_chat_model(
        api_key="k", model="m", reasoning_effort="none", timeout_s=5, fallback_models=()
    )
    assert out is instances[0][2]
    assert len(instances) == 1
    assert instances[0][0]["max_retries"] == 0
    instances[0][1].bind_tools.assert_called_once()


def test_build_chat_model_wraps_with_fallbacks(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))

    out = llm.build_chat_model(
        api_key="k",
        model="primary",
        fallback_models=("fb1", "fb2"),
    )
    # Three ChatGroq builds: primary + two fallbacks
    models_built = [kw["model"] for kw, _, _ in instances]
    assert models_built == ["primary", "fb1", "fb2"]
    tag, primary_bound, fbs = out
    assert tag == "with_fallbacks"
    assert primary_bound.model == "primary"
    assert tuple(b.model for b in fbs) == ("fb1", "fb2")


def test_build_chat_model_dedupes_primary_from_fallbacks(monkeypatch) -> None:
    factory, instances = _fake_chatgroq_factory()
    monkeypatch.setattr(llm, "ChatGroq", MagicMock(side_effect=factory))

    out = llm.build_chat_model(api_key="k", model="primary", fallback_models=("primary", "fb1"))
    models_built = [kw["model"] for kw, _, _ in instances]
    assert models_built == ["primary", "fb1"]  # duplicate "primary" skipped
    _, _, fbs = out
    assert tuple(b.model for b in fbs) == ("fb1",)
