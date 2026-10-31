import httpx
import pytest

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
