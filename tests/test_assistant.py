from types import SimpleNamespace
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import httpx
import pytest

from app.api import assistant as assistant_api
from app.assistant.context import ContextBuilder
from app.assistant.limits import AssistantRequestLimiter
from app.assistant.providers import AssistantProviderError, OpenAIResponsesProvider, ProviderResult
from app.assistant.service import AssistantService
from app.db.session import get_session_factory
from app.main import app
from app.schemas import AssistantChatRequest
from app.operational_intelligence.engine import AnalysisItem


class FakeProvider:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content or '{"answer":"Observed data only.","observed_facts":["System is healthy."],"interpretations":[],"recommendations":[],"insufficient_information":[],"references":["invented:reference"]}'
        self.error = error
        self.calls = []

    def respond(self, instructions: str, input_text: str, max_output_tokens: int) -> ProviderResult:
        self.calls.append((instructions, input_text, max_output_tokens))
        if self.error:
            raise self.error
        return ProviderResult(content=self.content, input_tokens=10, output_tokens=5)


def settings(**overrides):
    values = {
        "ai_enabled": True,
        "ai_provider": "openai",
        "ai_openai_api_key": "test-key",
        "ai_model": "test-model",
        "ai_timeout_seconds": 1,
        "ai_max_output_tokens": 200,
        "ai_max_context_characters": 1000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_assistant_disabled_and_unconfigured_statuses() -> None:
    assert AssistantService(settings(ai_enabled=False)).status().status == "disabled"
    assert AssistantService(settings(ai_openai_api_key=None)).status().status == "not_configured"


def test_assistant_returns_valid_structured_response_without_writes() -> None:
    provider = FakeProvider()
    service = AssistantService(settings(), provider)
    with get_session_factory()() as session:
        response = service.chat(session, AssistantChatRequest(question="What is the infrastructure state?"))
        assert not session.new
    assert response.answer == "Observed data only."
    assert "invented:reference" not in response.references
    assert provider.calls
    assert "test-key" not in provider.calls[0][1]


def test_assistant_rejects_provider_failures_and_invalid_responses() -> None:
    with get_session_factory()() as session:
        for provider in (FakeProvider(error=AssistantProviderError("timeout")), FakeProvider(content="not json")):
            try:
                AssistantService(settings(), provider).chat(session, AssistantChatRequest(question="Status?"))
            except AssistantProviderError:
                pass
            else:
                raise AssertionError("Provider failure should be controlled")


def test_openai_provider_uses_store_false_and_hides_authentication_error(monkeypatch) -> None:
    captured = {}
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")

    def response(*_args, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, request=request, json={"output_text": FakeProvider().content, "usage": {"input_tokens": 1, "output_tokens": 2}})

    monkeypatch.setattr("app.assistant.providers.httpx.post", response)
    result = OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)
    assert result.input_tokens == 1
    assert captured["json"]["store"] is False
    assert captured["timeout"] == 1

    monkeypatch.setattr("app.assistant.providers.httpx.post", lambda *_args, **_kwargs: httpx.Response(401, request=request))
    try:
        OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)
    except AssistantProviderError as error:
        assert error.code == "authentication_failed"
        assert "secret-key" not in str(error)
    else:
        raise AssertionError("Authentication failure should be controlled")


@pytest.mark.parametrize(("status_code", "expected_code"), [(403, "authentication_failed"), (429, "rate_limited")])
def test_openai_provider_classifies_provider_http_errors(monkeypatch, status_code: int, expected_code: str) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    monkeypatch.setattr("app.assistant.providers.httpx.post", lambda *_args, **_kwargs: httpx.Response(status_code, request=request))
    with pytest.raises(AssistantProviderError, match=expected_code) as error:
        OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)
    assert error.value.code == expected_code


@pytest.mark.parametrize(("failure", "expected_code"), [(httpx.TimeoutException("timeout"), "timeout"), (httpx.ConnectError("offline"), "connection_failed")])
def test_openai_provider_classifies_transport_errors(monkeypatch, failure: Exception, expected_code: str) -> None:
    def raise_error(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("app.assistant.providers.httpx.post", raise_error)
    with pytest.raises(AssistantProviderError, match=expected_code) as error:
        OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)
    assert error.value.code == expected_code


def test_openai_provider_rejects_malformed_response(monkeypatch) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    monkeypatch.setattr("app.assistant.providers.httpx.post", lambda *_args, **_kwargs: httpx.Response(200, request=request, json=["unexpected"]))
    with pytest.raises(AssistantProviderError, match="invalid_response"):
        OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)


def test_assistant_limiter_enforces_rate_and_concurrency() -> None:
    limiter = AssistantRequestLimiter(limit=1, window_seconds=60, max_concurrent=1)
    assert limiter.acquire("client").allowed
    assert not limiter.acquire("other-client").allowed
    limiter.release()
    limited = limiter.acquire("client")
    assert not limited.allowed
    assert limited.retry_after


def test_assistant_errors_do_not_log_secret(caplog) -> None:
    provider = FakeProvider(error=AssistantProviderError("authentication_failed"))
    with get_session_factory()() as session:
        try:
            AssistantService(settings(ai_openai_api_key="secret-key"), provider).chat(session, AssistantChatRequest(question="Status?"))
        except AssistantProviderError:
            pass
    assert "secret-key" not in caplog.text


def test_context_is_bounded_and_does_not_include_link_destinations() -> None:
    with get_session_factory()() as session:
        context, _ = ContextBuilder(200).build(session, "tracking metrics")
    assert len(context) <= 200
    assert "destination_url" not in context


def test_assistant_endpoints_validate_and_use_fake_provider() -> None:
    service = AssistantService(settings(), FakeProvider())
    app.dependency_overrides[assistant_api.get_assistant_service] = lambda: service
    try:
        with TestClient(app) as client:
            assert client.get("/assistant/status").json()["status"] == "available"
            assert client.post("/assistant/chat", json={"question": ""}).status_code == 422
            response = client.post("/assistant/chat", json={"question": "Give a summary."})
            assert response.status_code == 200
            assert response.json()["answer"] == "Observed data only."
    finally:
        app.dependency_overrides.clear()


def test_assistant_endpoint_returns_429_when_local_limit_is_reached(monkeypatch) -> None:
    service = AssistantService(settings(), FakeProvider())
    limiter = AssistantRequestLimiter(limit=1, window_seconds=60, max_concurrent=1)
    monkeypatch.setattr(assistant_api, "get_assistant_limiter", lambda: limiter)
    app.dependency_overrides[assistant_api.get_assistant_service] = lambda: service
    try:
        with TestClient(app) as client:
            assert client.post("/assistant/chat", json={"question": "First"}).status_code == 200
            response = client.post("/assistant/chat", json={"question": "Second"})
            assert response.status_code == 429
            assert response.headers["Retry-After"]
    finally:
        app.dependency_overrides.clear()


def test_operational_questions_load_only_calculated_intelligence_context(monkeypatch) -> None:
    item = AnalysisItem("recurrent-events:postgresql", "recurrent_infrastructure_event", "warning", "Historical recurrence.", "3", "3", datetime.now(timezone.utc), ("event:valid",), ("Historical only.",))
    calls = []

    class AnalysisService:
        def __init__(self, _settings):
            pass

        def analyze(self, _session):
            calls.append(True)
            return [item]

    monkeypatch.setattr("app.assistant.context.OperationalIntelligenceService", AnalysisService)
    with get_session_factory()() as session:
        context, references = ContextBuilder(5000).build(session, "Explain the anomaly priority")
        ordinary_context, _ = ContextBuilder(5000).build(session, "List campaigns")
    assert "operational_intelligence" in context
    assert "recurrent-events:postgresql" in references
    assert "operational_intelligence" not in ordinary_context
    assert len(calls) == 1


def test_assistant_keeps_only_valid_anomaly_references(monkeypatch) -> None:
    class FixedContextBuilder:
        def __init__(self, _max_characters):
            pass

        def build(self, _session, _question):
            return "{}", ["recurrent-events:postgresql"]

    provider = FakeProvider(content='{"answer":"Observed.","observed_facts":[],"interpretations":[],"recommendations":[],"insufficient_information":[],"references":["recurrent-events:postgresql","recurrent-events:invented","event:arbitrary"]}')
    monkeypatch.setattr("app.assistant.service.ContextBuilder", FixedContextBuilder)
    response = AssistantService(settings(), provider).chat(None, AssistantChatRequest(question="Explain anomalies"))
    assert response.references == ["recurrent-events:postgresql"]
