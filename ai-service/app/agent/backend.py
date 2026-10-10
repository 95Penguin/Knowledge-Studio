import uuid
from typing import Any

import httpx


class BackendToolError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class JavaBackendClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def query_device(self, token: str, device_id: str, request_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/devices/{device_id}", token, request_id)

    def current_user(self, token: str) -> dict[str, Any]:
        return self._request("GET", "/api/auth/me", token, request_id())

    def login(self, email: str, password: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/auth/login",
            None,
            request_id(),
            {"email": email, "password": password},
        )

    def create_ticket(self, token: str, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/tickets", token, request_id, payload)

    def transfer_to_human(
        self, token: str, request_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request("POST", "/api/transfers", token, request_id, payload)

    def _request(
        self,
        method: str,
        path: str,
        token: str | None,
        request_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if token is not None and not token:
            raise BackendToolError(401, "执行敏感工具前必须登录。")
        headers = {"X-Request-Id": request_id}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        response = None
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.request(
                        method, f"{self.base_url}{path}", headers=headers, json=payload
                    )
                break
            except (httpx.TimeoutException, httpx.TransportError) as error:
                if attempt == 1:
                    status = 504 if isinstance(error, httpx.TimeoutException) else 503
                    raise BackendToolError(
                        status, "Java 业务服务调用失败，有限重试已用尽。"
                    ) from error
        if response is None:
            raise BackendToolError(503, "Java 业务服务暂时不可用。")
        if response.is_error:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            raise BackendToolError(response.status_code, str(message)[:500])
        data = response.json()
        if not isinstance(data, dict):
            raise BackendToolError(502, "Java 业务服务返回格式错误。")
        return data


def request_id() -> str:
    return str(uuid.uuid4())
