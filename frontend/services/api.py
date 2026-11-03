import os
from collections.abc import Callable
from threading import Lock
from typing import Any

import httpx


class ApiError(Exception):
    def __init__(self, status_code: int | None, detail: str, payload: object | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.payload = payload


class ApiClient:
    """HTTP client whose credentials are supplied by one Streamlit session."""

    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        get_access_token: Callable[[], str | None] | None = None,
        get_refresh_token: Callable[[], str | None] | None = None,
        save_tokens: Callable[[dict[str, Any]], None] | None = None,
        clear_auth: Callable[[], None] | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.client = client or httpx.Client(timeout=timeout or float(os.getenv("API_TIMEOUT_SECONDS", "10")))
        self.get_access_token = get_access_token or (lambda: None)
        self.get_refresh_token = get_refresh_token or (lambda: None)
        self.save_tokens = save_tokens or (lambda _tokens: None)
        self.clear_auth = clear_auth or (lambda: None)
        self._refresh_lock = Lock()

    def _error(self, response: httpx.Response) -> ApiError:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        detail = payload.get("detail", "The API request failed.") if isinstance(payload, dict) else "The API request failed."
        return ApiError(response.status_code, str(detail), payload)

    def _send(self, method: str, path: str, include_auth: bool, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if include_auth and (token := self.get_access_token()):
            headers["Authorization"] = f"Bearer {token}"
        try:
            return self.client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise ApiError(None, "The API is unavailable.") from error

    def _refresh(self, expired_access_token: str | None) -> bool:
        with self._refresh_lock:
            # Another request may already have rotated this session's tokens.
            if self.get_access_token() and self.get_access_token() != expired_access_token:
                return True
            refresh_token = self.get_refresh_token()
            if not refresh_token:
                return False
            response = self._send("POST", "/auth/refresh", False, json={"refresh_token": refresh_token})
            if response.is_success:
                self.save_tokens(response.json())
                return True
            return False

    def request(self, method: str, path: str, *, allow_refresh: bool = True, **kwargs: Any) -> object | None:
        auth_path = path in {"/auth/login", "/auth/refresh"}
        access_token = self.get_access_token()
        response = self._send(method, path, not auth_path, **kwargs)
        if response.status_code == 401 and allow_refresh and not auth_path and self._refresh(access_token):
            response = self._send(method, path, True, **kwargs)
        if not response.is_success:
            if response.status_code == 401:
                self.clear_auth()
            raise self._error(response)
        return response.json() if response.content else None

    def get(self, path: str, **kwargs: Any) -> object | None:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, payload: dict[str, Any], **kwargs: Any) -> object | None:
        return self.request("POST", path, json=payload, **kwargs)

    def patch(self, path: str, payload: dict[str, Any], **kwargs: Any) -> object | None:
        return self.request("PATCH", path, json=payload, **kwargs)

    def login(self, email: str, password: str) -> dict[str, Any]:
        result = self.post("/auth/login", {"email": email, "password": password}, allow_refresh=False)
        if not isinstance(result, dict):
            raise ApiError(None, "The API returned an invalid authentication response.")
        return result

    def me(self) -> dict[str, Any]:
        result = self.get("/auth/me")
        if not isinstance(result, dict):
            raise ApiError(None, "The API returned an invalid identity response.")
        return result

    def logout(self) -> None:
        try:
            self.post("/auth/logout", {}, allow_refresh=False)
        finally:
            self.clear_auth()
