import json
from dataclasses import dataclass
from typing import Protocol

import httpx


class AssistantProviderError(Exception):
    def __init__(self, code: str = "request_failed") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProviderResult:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIProvider(Protocol):
    def respond(self, instructions: str, input_text: str, max_output_tokens: int) -> ProviderResult: ...


class OpenAIResponsesProvider:
    def __init__(self, api_key: str, model: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def respond(self, instructions: str, input_text: str, max_output_tokens: int) -> ProviderResult:
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": input_text,
            "store": False,
            "max_output_tokens": max_output_tokens,
            "text": {"format": {"type": "json_object"}},
        }
        try:
            response = httpx.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as error:
            raise AssistantProviderError("timeout") from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {401, 403}:
                raise AssistantProviderError("authentication_failed") from error
            if error.response.status_code == 429:
                raise AssistantProviderError("rate_limited") from error
            raise AssistantProviderError("request_failed") from error
        except httpx.RequestError as error:
            raise AssistantProviderError("connection_failed") from error
        except ValueError as error:
            raise AssistantProviderError("invalid_response") from error
        if not isinstance(data, dict):
            raise AssistantProviderError("invalid_response")
        content = data.get("output_text")
        if not isinstance(content, str):
            raise AssistantProviderError("invalid_response")
        usage = data.get("usage") or {}
        return ProviderResult(content=content, input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"))
