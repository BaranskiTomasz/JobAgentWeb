import os
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-real-923nf")

import grounding_check


def _tool_response(unsupported_sentences):
    return SimpleNamespace(
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        content=[SimpleNamespace(
            type="tool_use",
            input={"unsupported_sentences": unsupported_sentences},
        )],
    )


def test_fully_grounded_uses_anthropic_tool_schema(monkeypatch):
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return _tool_response([])

    monkeypatch.setattr(
        grounding_check,
        "_get_client",
        lambda: SimpleNamespace(messages=Messages()),
    )
    text = "Built APIs with Python."
    facts = [{"value": "Built backend APIs using Python."}]

    result = grounding_check.check_grounding(text, facts)

    assert result.is_fully_grounded is True
    assert result.unsupported_sentences == []
    assert result.input_tokens == 10
    assert result.output_tokens == 20
    assert calls[0]["tool_choice"] == {
        "type": "tool",
        "name": "submit_grounding_check",
    }
    message = calls[0]["messages"][0]["content"]
    assert facts[0]["value"] in message
    assert text in message


def test_partially_grounded_returns_unsupported_sentence(monkeypatch):
    unsupported = [{
        "sentence": "Led a team of 50 engineers.",
        "reason": "no fact mentions team size or a leadership role",
    }]

    class Messages:
        def create(self, **kwargs):
            return _tool_response(unsupported)

    monkeypatch.setattr(
        grounding_check,
        "_get_client",
        lambda: SimpleNamespace(messages=Messages()),
    )

    result = grounding_check.check_grounding(
        "Led a team of 50 engineers.",
        [{"value": "Worked as a software engineer."}],
    )

    assert result.is_fully_grounded is False
    assert result.unsupported_sentences == unsupported


def test_fail_closed_on_exception(monkeypatch):
    class Messages:
        def create(self, **kwargs):
            raise RuntimeError("service unavailable")

    monkeypatch.setattr(
        grounding_check,
        "_get_client",
        lambda: SimpleNamespace(messages=Messages()),
    )
    text = "Led a team of 50 engineers."

    result = grounding_check.check_grounding(text, [])

    assert result.is_fully_grounded is False
    assert result.unsupported_sentences == [{
        "sentence": text,
        "reason": "grounding check itself failed, treating as ungrounded",
    }]
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_fail_closed_on_non_tool_use_stop_reason(monkeypatch):
    class Messages:
        def create(self, **kwargs):
            return SimpleNamespace(
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=10, output_tokens=20),
                content=[],
            )

    monkeypatch.setattr(
        grounding_check,
        "_get_client",
        lambda: SimpleNamespace(messages=Messages()),
    )
    text = "Led a team of 50 engineers."

    result = grounding_check.check_grounding(text, [])

    assert result.is_fully_grounded is False
    assert result.unsupported_sentences == [{
        "sentence": text,
        "reason": "grounding check itself failed, treating as ungrounded",
    }]
    assert result.input_tokens == 0
    assert result.output_tokens == 0
