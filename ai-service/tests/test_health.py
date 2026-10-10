from fastapi.testclient import TestClient

from app.agent.backend import JavaBackendClient
from app.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "ai-service"


def test_web_app_is_served() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Knowledge Studio" in response.text
    assert "/assets/index-" in response.text


def test_same_origin_login_proxies_to_java(monkeypatch) -> None:
    def fake_login(self, email: str, password: str) -> dict[str, str]:
        assert (email, password) == ("demo@example.com", "secret")
        return {"accessToken": "token", "displayName": "Demo"}

    monkeypatch.setattr(JavaBackendClient, "login", fake_login)
    response = TestClient(app).post(
        "/api/auth/login", json={"email": "demo@example.com", "password": "secret"}
    )
    assert response.status_code == 200
    assert response.json()["accessToken"] == "token"
