import httpx
import pytest
from pathlib import Path

from services.api import ApiClient, ApiError


def test_api_client_consumes_json() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"campaigns": 0}))
    client = ApiClient("http://api.test", httpx.Client(transport=transport))
    assert client.get("/dashboard/summary") == {"campaigns": 0}


def test_api_client_surfaces_errors() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    client = ApiClient("http://api.test", httpx.Client(transport=transport))
    with pytest.raises(ApiError):
        client.get("/dashboard/summary")


def test_dashboard_includes_the_ai_assistant_section() -> None:
    source = Path("frontend/app.py").read_text(encoding="utf-8")
    assert "Asistente IA" in source
    assert '"/assistant/status"' in source
    assert '"/assistant/chat"' in source
    assert "Inteligencia Operativa" in source
    assert '"/operational-intelligence/summary"' in source
