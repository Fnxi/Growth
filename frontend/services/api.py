import os

import httpx


class ApiError(Exception):
    pass


class ApiClient:
    def __init__(self, base_url: str | None = None, client: httpx.Client | None = None):
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.client = client or httpx.Client(timeout=10)

    def request(self, method: str, path: str, **kwargs):
        try:
            response = self.client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        except httpx.HTTPError as error:
            raise ApiError(str(error)) from error

    def get(self, path: str, **kwargs): return self.request("GET", path, **kwargs)
    def post(self, path: str, payload: dict): return self.request("POST", path, json=payload)
    def patch(self, path: str, payload: dict): return self.request("PATCH", path, json=payload)
