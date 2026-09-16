from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "ai-service"


def test_web_app_is_served() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "SupportPilot" in response.text
    assert "/app.js" in response.text
