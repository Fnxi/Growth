from pathlib import Path
from threading import Barrier, Thread

import httpx
import pytest

from services.api import ApiClient, ApiError


def client(handler, state=None):
    state = state if state is not None else {"access": "access-1", "refresh": "refresh-1"}
    cleared = []
    api = ApiClient(
        "http://api.test",
        httpx.Client(transport=httpx.MockTransport(handler)),
        get_access_token=lambda: state.get("access"),
        get_refresh_token=lambda: state.get("refresh"),
        save_tokens=lambda tokens: state.update(access=tokens["access_token"], refresh=tokens["refresh_token"]),
        clear_auth=lambda: cleared.append(True),
    )
    return api, state, cleared


def test_login_and_me_use_real_auth_contract() -> None:
    def handler(request):
        if request.url.path == "/auth/login":
            assert request.headers.get("Authorization") is None
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh", "token_type": "bearer", "expires_in": 600})
        assert request.headers["Authorization"] == "Bearer access-1"
        return httpx.Response(200, json={"id": "user", "email": "user@example.test", "memberships": []})

    api, _, _ = client(handler)
    assert api.login("user@example.test", "secret")["access_token"] == "access"
    assert api.me()["email"] == "user@example.test"


def test_authorization_header_and_refresh_rotation() -> None:
    calls = []

    def handler(request):
        calls.append((request.url.path, request.headers.get("Authorization")))
        if request.url.path == "/resource" and len([item for item in calls if item[0] == "/resource"]) == 1:
            return httpx.Response(401, json={"detail": "expired"})
        if request.url.path == "/auth/refresh":
            assert request.headers.get("Authorization") is None
            return httpx.Response(200, json={"access_token": "access-2", "refresh_token": "refresh-2", "token_type": "bearer", "expires_in": 600})
        return httpx.Response(200, json={"ok": True})

    api, state, cleared = client(handler)
    assert api.get("/resource") == {"ok": True}
    assert state == {"access": "access-2", "refresh": "refresh-2"}
    assert not cleared
    assert calls == [("/resource", "Bearer access-1"), ("/auth/refresh", None), ("/resource", "Bearer access-2")]


def test_refresh_failure_clears_auth_and_does_not_loop() -> None:
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(401, json={"detail": "invalid"})

    api, _, cleared = client(handler)
    with pytest.raises(ApiError) as error:
        api.get("/resource")
    assert error.value.status_code == 401
    assert calls == ["/resource", "/auth/refresh"]
    assert cleared == [True]


@pytest.mark.parametrize("status_code", [403, 404, 409, 422, 500])
def test_http_errors_preserve_status_and_detail(status_code) -> None:
    api, _, _ = client(lambda _request: httpx.Response(status_code, json={"detail": "controlled"}))
    with pytest.raises(ApiError) as error:
        api.get("/resource", allow_refresh=False)
    assert error.value.status_code == status_code
    assert error.value.detail == "controlled"


def test_logout_clears_local_auth_when_backend_is_available_or_unavailable() -> None:
    for status_code in (204, 503):
        api, _, cleared = client(lambda _request, code=status_code: httpx.Response(code, json={"detail": "down"} if code != 204 else None))
        if status_code == 204:
            api.logout()
        else:
            with pytest.raises(ApiError):
                api.logout()
        assert cleared


def test_two_clients_keep_authentication_state_isolated() -> None:
    requests = []

    def handler(request):
        requests.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"ok": True})

    state_a, state_b = {"access": "access-a", "refresh": "refresh-a", "user": "a"}, {"access": "access-b", "refresh": "refresh-b", "user": "b"}
    transport = httpx.Client(transport=httpx.MockTransport(handler))
    api_a = ApiClient("http://api.test", transport, lambda: state_a.get("access"), lambda: state_a.get("refresh"), lambda _tokens: None, state_a.clear)
    api_b = ApiClient("http://api.test", transport, lambda: state_b.get("access"), lambda: state_b.get("refresh"), lambda _tokens: None, state_b.clear)
    assert api_a.get("/resource") == {"ok": True}
    api_a.logout()
    assert state_a == {}
    assert state_b == {"access": "access-b", "refresh": "refresh-b", "user": "b"}
    assert api_b.get("/resource") == {"ok": True}
    assert requests == ["Bearer access-a", "Bearer access-a", "Bearer access-b"]


def test_concurrent_401_responses_rotate_refresh_once() -> None:
    barrier = Barrier(2)
    refreshes = []
    state = {"access": "expired", "refresh": "refresh-1"}

    def handler(request):
        if request.url.path == "/resource" and request.headers.get("Authorization") == "Bearer expired":
            barrier.wait(timeout=2)
            return httpx.Response(401, json={"detail": "expired"})
        if request.url.path == "/auth/refresh":
            refreshes.append(True)
            return httpx.Response(200, json={"access_token": "fresh", "refresh_token": "refresh-2", "token_type": "bearer", "expires_in": 600})
        return httpx.Response(200, json={"ok": True})

    api = ApiClient("http://api.test", httpx.Client(transport=httpx.MockTransport(handler)), lambda: state.get("access"), lambda: state.get("refresh"), lambda tokens: state.update(access=tokens["access_token"], refresh=tokens["refresh_token"]), state.clear)
    results = []
    workers = [Thread(target=lambda: results.append(api.get("/resource"))) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)
    assert results == [{"ok": True}, {"ok": True}]
    assert len(refreshes) == 1
    assert state == {"access": "fresh", "refresh": "refresh-2"}


def test_dashboard_includes_the_ai_assistant_section() -> None:
    source = Path("frontend/app.py").read_text(encoding="utf-8")
    assert "Asistente IA" in source
    assert '"/assistant/status"' in source
    assert '"/assistant/chat"' in source
    assert "Inteligencia Operativa" in source
    assert '"/operational-intelligence/summary"' in source
