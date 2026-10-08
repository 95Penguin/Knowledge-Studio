"""MCP JSON-RPC adapter for Java business tools."""

import json
from typing import Any

import httpx

from app.agent.backend import BackendToolError, request_id


class McpJavaBackendClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._schemas: dict[str, dict[str, Any]] | None = None

    def current_user(self, token: str) -> dict[str, Any]:
        return self.call_tool("current_user", {}, token, request_id())

    def query_device(self, token: str, device_id: str, rid: str) -> dict[str, Any]:
        return self.call_tool("query_device", {"deviceId": device_id}, token, rid)

    def create_ticket(self, token: str, rid: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.call_tool("create_ticket", payload, token, rid)

    def transfer_to_human(self, token: str, rid: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.call_tool("transfer_to_human", payload, token, rid)

    def list_tools(self, token: str) -> dict[str, dict[str, Any]]:
        if self._schemas is None:
            result = self._rpc("tools/list", {}, token, request_id())
            self._schemas = {
                item["name"]: item["inputSchema"] for item in result.get("tools", [])
            }
        return self._schemas

    def call_tool(
        self, name: str, arguments: dict[str, Any], token: str, rid: str
    ) -> dict[str, Any]:
        schema = self.list_tools(token).get(name)
        if schema is None:
            raise BackendToolError(400, f"MCP tool does not exist: {name}")
        properties = schema.get("properties", {})
        if set(arguments) - set(properties) or set(schema.get("required", [])) - set(arguments):
            raise BackendToolError(400, f"MCP tool parameters do not match schema: {name}")
        for field, value in arguments.items():
            expected = properties[field].get("type")
            if expected == "string" and (not isinstance(value, str) or not value.strip()):
                raise BackendToolError(400, f"MCP argument {field} must be a non-empty string")
            if expected == "boolean" and not isinstance(value, bool):
                raise BackendToolError(400, f"MCP argument {field} must be boolean")
        result = self._rpc("tools/call", {"name": name, "arguments": arguments}, token, rid)
        if result.get("isError"):
            raise BackendToolError(502, f"MCP tool failed: {name}")
        try:
            value = json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise BackendToolError(502, "MCP tool returned invalid content") from error
        if not isinstance(value, dict):
            raise BackendToolError(502, "MCP tool returned a non-object value")
        return value

    def _rpc(
        self, method: str, params: dict[str, Any], token: str, rid: str
    ) -> dict[str, Any]:
        if not token:
            raise BackendToolError(401, "执行工具前必须登录")
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/mcp", json=payload,
                    headers={"Authorization": f"Bearer {token}", "X-Request-Id": rid},
                )
        except httpx.TimeoutException as error:
            raise BackendToolError(504, "MCP tool request timed out") from error
        except httpx.TransportError as error:
            raise BackendToolError(503, "MCP endpoint unavailable") from error
        if response.is_error:
            raise BackendToolError(response.status_code, response.text[:500])
        try:
            body = response.json()
        except ValueError as error:
            raise BackendToolError(502, "MCP endpoint returned invalid JSON") from error
        if "error" in body:
            error = body["error"]
            raise BackendToolError(400 if error.get("code") == -32602 else 502, error.get("message", "MCP error"))
        result = body.get("result")
        if not isinstance(result, dict):
            raise BackendToolError(502, "MCP endpoint returned invalid result")
        return result
