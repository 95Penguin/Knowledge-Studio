import json

from fastapi.testclient import TestClient

from app.agent.models import AgentState, AgentTurnResponse
from app.agent.runtime import get_agent_service
from app.generation.models import RequestTrace
from app.main import app


class FixedAgent:
    def turn(self, request: object) -> AgentTurnResponse:
        return AgentTurnResponse(
            conversation_id="conversation-1",
            state=AgentState.WAITING_FEEDBACK,
            message="**已校验回答**\n\n使用官方证据。",
            required_action="resolved_or_unresolved",
            trace=RequestTrace(
                request_id="request-1",
                total_ms=123.4,
                stages_ms={"reranker": 20.0, "llm_generation": 80.0},
                prompt_tokens=100,
                completion_tokens=20,
            ),
        )


def test_agent_stream_emits_status_validated_deltas_trace_and_complete() -> None:
    app.dependency_overrides[get_agent_service] = lambda: FixedAgent()
    try:
        response = TestClient(app).post(
            "/api/agent/stream",
            json={"action": "ask", "message": "question", "backend_token": "token"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    frames = [frame for frame in response.text.split("\n\n") if frame]
    events = [frame.splitlines()[0].removeprefix("event: ") for frame in frames]
    assert events[0] == "status"
    assert "trace" in events
    assert "answer_delta" in events
    assert events[-1] == "complete"
    complete = json.loads(frames[-1].splitlines()[1].removeprefix("data: "))
    assert complete["trace"]["request_id"] == "request-1"
    assert complete["message"].startswith("**已校验回答**")
