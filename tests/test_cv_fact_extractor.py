import os
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-real-923nf")

import cv_fact_extractor


def _tool_response(facts):
    return SimpleNamespace(
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        content=[
            SimpleNamespace(
                type="tool_use",
                input={"facts": facts},
            )
        ],
    )


def test_extract_facts_success(monkeypatch):
    calls = []
    sample_facts = [
        {
            "fact_type": "work_experience",
            "value": "Senior Backend Engineer at Acme Corp, 2020-2023.",
            "source_quote": "Acme Corp - Senior Backend Engineer (2020-2023)",
        },
        {
            "fact_type": "skill",
            "value": "Proficient in Python and PostgreSQL.",
            "source_quote": "Skills: Python, PostgreSQL",
        },
        {
            "fact_type": "education",
            "value": "B.S. in Computer Science from State University, 2016-2020.",
            "source_quote": "State University - B.S. Computer Science 2016-2020",
        },
    ]

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return _tool_response(sample_facts)

    monkeypatch.setattr(
        cv_fact_extractor,
        "_get_client",
        lambda: SimpleNamespace(messages=Messages()),
    )

    cv_text = (
        "Acme Corp - Senior Backend Engineer (2020-2023)\n"
        "Skills: Python, PostgreSQL\n"
        "State University - B.S. Computer Science 2016-2020"
    )
    result = cv_fact_extractor.extract_facts_from_cv(cv_text)

    assert result == sample_facts
    assert len(calls) == 1
    assert calls[0]["tool_choice"] == {
        "type": "tool",
        "name": "submit_candidate_facts",
    }
    assert cv_text in calls[0]["messages"][0]["content"]
    assert calls[0]["model"] == cv_fact_extractor.CLAUDE_FACT_EXTRACT_MODEL
    for fact in result:
        assert "source" not in fact
        assert "source_ref" not in fact


def test_fail_open_on_exception(monkeypatch):
    class Messages:
        def create(self, **kwargs):
            raise RuntimeError("API timeout or rate limit exceeded")

    monkeypatch.setattr(
        cv_fact_extractor,
        "_get_client",
        lambda: SimpleNamespace(messages=Messages()),
    )

    result = cv_fact_extractor.extract_facts_from_cv("Some CV content")
    assert result == []


def test_fail_open_on_non_tool_use_stop_reason(monkeypatch):
    class Messages:
        def create(self, **kwargs):
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Sorry, cannot process")],
            )

    monkeypatch.setattr(
        cv_fact_extractor,
        "_get_client",
        lambda: SimpleNamespace(messages=Messages()),
    )

    result = cv_fact_extractor.extract_facts_from_cv("Some CV content")
    assert result == []
