import json
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.services import llm_service
from app.services.llm_service import (
    ABSTRACT_NOTE,
    GeminiLLMService,
    LLMError,
    LLMNotConfigured,
    LLMRateLimited,
)


def api_error(code, message):
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "message": message, "status": "X"}})


class FakeModels:
    """Each call pops the next outcome: a string (response text) or an exception to raise."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def generate_content(self, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    # Replace only llm_service's view of asyncio, so no real waiting between retries.
    monkeypatch.setattr(llm_service, "asyncio", SimpleNamespace(sleep=fake_sleep))
    return recorded


def make_service(*outcomes, max_attempts=2):
    svc = GeminiLLMService(api_key=None, model="test-model", max_attempts=max_attempts)
    models = FakeModels(outcomes)
    svc._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return svc, models


# ---------- configuration and errors ----------


async def test_no_api_key_raises_not_configured():
    svc = GeminiLLMService(api_key=None, model="m")
    with pytest.raises(LLMNotConfigured, match="not set"):
        await svc.summarize("T", "text", "full_text")


async def test_rate_limit_is_retried_then_succeeds(sleeps):
    svc, models = make_service(api_error(429, "quota"), "  A summary.  ")
    assert await svc.summarize("T", "text", "full_text") == "A summary."
    # Requirement: a rate limit is retried after waiting. How long to wait is the code's choice.
    assert len(models.calls) == 2
    assert len(sleeps) == 1 and sleeps[0] > 0


async def test_rate_limit_on_every_attempt_raises_rate_limited(sleeps):
    svc, _ = make_service(api_error(429, "quota"), api_error(429, "quota"))
    with pytest.raises(LLMRateLimited):
        await svc.summarize("T", "text", "full_text")


async def test_invalid_api_key_is_reported_as_not_configured():
    svc, _ = make_service(api_error(400, "API key not valid. Please pass a valid API key."))
    with pytest.raises(LLMNotConfigured, match="rejected"):
        await svc.summarize("T", "text", "full_text")


@pytest.mark.parametrize("error", [api_error(500, "internal"), api_error(400, "Request contains an invalid argument.")])
async def test_other_api_errors_become_llm_error(error):
    svc, _ = make_service(error)
    with pytest.raises(LLMError) as exc:
        await svc.summarize("T", "text", "full_text")
    assert not isinstance(exc.value, (LLMNotConfigured, LLMRateLimited))


# ---------- summarize / answer ----------


async def test_summarize_prompt_contains_text_and_basis_note():
    svc, models = make_service("s1", "s2")
    await svc.summarize("My Title", "FULL PAPER TEXT", "full_text")
    await svc.summarize("My Title", "JUST THE ABSTRACT", "abstract")
    full_prompt, abstract_prompt = models.calls[0]["contents"], models.calls[1]["contents"]
    assert "My Title" in full_prompt and "FULL PAPER TEXT" in full_prompt
    assert ABSTRACT_NOTE not in full_prompt
    assert ABSTRACT_NOTE in abstract_prompt
    assert models.calls[0]["model"] == "test-model"


async def test_summarize_handles_empty_response_text():
    svc, _ = make_service(None)
    assert await svc.summarize("T", "x", "full_text") == ""


async def test_answer_sends_history_with_roles_and_paper_in_system_prompt():
    svc, models = make_service(" The answer. ")
    history = [("user", "Q1"), ("assistant", "A1")]
    assert await svc.answer("T", "PAPER BODY", "full_text", history, "Q2") == "The answer."
    call = models.calls[0]
    assert [(c.role, c.parts[0].text) for c in call["contents"]] == [("user", "Q1"), ("model", "A1"), ("user", "Q2")]
    assert "PAPER BODY" in call["config"].system_instruction
    assert "only the paper text" in call["config"].system_instruction


async def test_answer_marks_abstract_only_basis():
    svc, models = make_service("a")
    await svc.answer("T", "abstract", "abstract", [], "Q")
    assert ABSTRACT_NOTE in models.calls[0]["config"].system_instruction


# ---------- extract_metadata ----------


async def test_extract_metadata_parses_json_and_requests_schema():
    payload = {"title": "Tidal Pruning", "authors": ["I. Halvorsen"], "year": None, "abstract": "We study..."}
    svc, models = make_service(json.dumps(payload))
    meta = await svc.extract_metadata("first pages " * 10)
    assert meta.title == "Tidal Pruning" and meta.authors == ["I. Halvorsen"] and meta.year is None
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    # Requirement (HW1 plan): pass a response_schema so the model must return exactly these fields.
    assert {"title", "authors", "year", "abstract"} <= set(config.response_schema.model_fields)


async def test_extract_metadata_only_sends_the_first_pages():
    # Requirement (HW1 plan): Gemini extraction runs over "the first ~2 pages". Two pages of a
    # paper are roughly 8-10k characters, so text 30,000 characters in must not be sent.
    svc, models = make_service(json.dumps({"title": "T", "authors": ["A"]}))
    text = "Title and authors on page one. " + "x" * 30_000 + " PAGE-EIGHT-MARKER"
    await svc.extract_metadata(text)
    prompt = models.calls[0]["contents"]
    assert "Title and authors on page one." in prompt
    assert "PAGE-EIGHT-MARKER" not in prompt


@pytest.mark.parametrize(
    "outcome",
    ["not json at all", json.dumps({"authors": ["A"]}), json.dumps({"title": "   ", "authors": ["A"]}),
     api_error(500, "boom")],
    ids=["invalid-json", "missing-title", "blank-title", "api-error"],
)
async def test_extract_metadata_returns_none_on_bad_output(outcome):
    svc, _ = make_service(outcome)
    assert await svc.extract_metadata("text") is None


async def test_extract_metadata_without_key_returns_none():
    assert await GeminiLLMService(api_key=None, model="m").extract_metadata("text") is None
