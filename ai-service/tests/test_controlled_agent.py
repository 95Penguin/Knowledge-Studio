from pathlib import Path

from app.agent.backend import BackendToolError
from app.agent.models import AgentState, AgentTurnRequest
from app.agent.service import ControlledAgentService
from app.agent.store import ConversationStore
from app.generation.models import AnswerResponse, Citation


class FakeAnswers:
    def answer(self, question: str) -> AnswerResponse:
        return AnswerResponse(
            status="answered",
            answer="Use LATENCY DOCTOR.",
            citations=[
                Citation(
                    evidence_id="E1", chunk_id="c1", title="LATENCY DOCTOR",
                    section_path=["LATENCY DOCTOR"], source_path="content/commands/latency-doctor.md",
                    source_url="https://redis.io/docs/latest/commands/latency-doctor/",
                )
            ],
            top_evidence_score=0.99,
        )

    def general_answer(self, question: str) -> str:
        return "This is explicitly ungrounded general knowledge."


class RefusingAnswers(FakeAnswers):
    def answer(self, question: str) -> AnswerResponse:
        return AnswerResponse(
            status="refused", answer="insufficient evidence", citations=[],
            top_evidence_score=0.01, refusal_reason="no matching evidence",
        )


class FakeBackend:
    def __init__(self) -> None:
        self.device_calls = 0
        self.ticket_calls = 0

    def current_user(self, token: str) -> dict[str, object]:
        return {"userId": {"token-a": "user-a", "token-a-renewed": "user-a"}.get(token, "user-b")}

    def query_device(self, token: str, device_id: str, request_id: str) -> dict[str, object]:
        self.device_calls += 1
        if device_id == "forbidden":
            raise BackendToolError(403, "设备无权访问")
        return {"id": device_id, "name": "Redis Primary", "status": "DEGRADED"}

    def create_ticket(self, token: str, request_id: str, payload: dict[str, object]) -> dict[str, object]:
        self.ticket_calls += 1
        assert payload["confirmed"] is True
        assert str(payload["idempotencyKey"]).startswith("agent-")
        return {"id": "ticket-1", "status": "OPEN"}

    def transfer_to_human(self, token: str, request_id: str, payload: dict[str, object]) -> dict[str, object]:
        return {"id": "transfer-1", "status": "PENDING"}


def _request(action: str, **kwargs: object) -> AgentTurnRequest:
    return AgentTurnRequest(action=action, **kwargs)  # type: ignore[arg-type]


def test_full_controlled_flow_requires_authorization_and_confirmation() -> None:
    backend = FakeBackend()
    agent = ControlledAgentService(FakeAnswers(), backend)

    first = agent.turn(_request(
        "ask", message="我的生产 Redis 实例延迟飙升", backend_token="token-a"
    ))
    assert first.state == AgentState.WAITING_FEEDBACK
    assert first.tool_events[0].tool == "search_knowledge"

    authorization = agent.turn(_request(
        "unresolved", conversation_id=first.conversation_id, backend_token="token-a"
    ))
    assert authorization.required_action == "authorize_device"
    assert backend.device_calls == 0

    device = agent.turn(_request(
        "authorize_device", conversation_id=first.conversation_id,
        backend_token="token-a", device_id="device-1",
    ))
    assert device.state == AgentState.WAITING_DEVICE_FEEDBACK
    assert backend.device_calls == 1

    draft = agent.turn(_request(
        "unresolved", conversation_id=first.conversation_id, backend_token="token-a"
    ))
    assert draft.state == AgentState.WAITING_TICKET_CONFIRMATION
    assert backend.ticket_calls == 0

    ticket = agent.turn(_request(
        "confirm_ticket", conversation_id=first.conversation_id, backend_token="token-a"
    ))
    assert ticket.state == AgentState.TICKET_CREATED
    assert ticket.ticket["id"] == "ticket-1"
    assert backend.ticket_calls == 1


def test_backend_denial_fails_closed_and_transfers() -> None:
    backend = FakeBackend()
    agent = ControlledAgentService(FakeAnswers(), backend)
    first = agent.turn(_request("ask", message="我的 Redis 实例报错", backend_token="token-a"))
    agent.turn(_request("unresolved", conversation_id=first.conversation_id, backend_token="token-a"))
    denied = agent.turn(_request(
        "authorize_device", conversation_id=first.conversation_id,
        backend_token="token-a", device_id="forbidden",
    ))
    assert denied.state == AgentState.TRANSFERRED
    assert denied.tool_events[0].status == "denied"


def test_conversation_rejects_identity_switch_and_invalid_state() -> None:
    agent = ControlledAgentService(FakeAnswers(), FakeBackend())
    first = agent.turn(_request("ask", message="q", backend_token="token-a"))
    try:
        agent.turn(_request("unresolved", conversation_id=first.conversation_id, backend_token="token-b"))
        raise AssertionError("identity switch should fail")
    except PermissionError:
        pass

    try:
        agent.turn(_request("confirm_ticket", conversation_id=first.conversation_id, backend_token="token-a"))
        raise AssertionError("invalid transition should fail")
    except ValueError:
        pass


def test_max_steps_transfers_to_human() -> None:
    agent = ControlledAgentService(FakeAnswers(), FakeBackend(), max_steps=1)
    first = agent.turn(_request("ask", message="q", backend_token="token-a"))
    result = agent.turn(_request(
        "resolved", conversation_id=first.conversation_id, backend_token="token-a"
    ))
    assert result.state == AgentState.TRANSFERRED
    assert result.tool_events[0].tool == "transfer_to_human"


def test_conversation_resumes_from_sqlite_after_service_restart(tmp_path: Path) -> None:
    database = tmp_path / "agent.db"
    first_service = ControlledAgentService(
        FakeAnswers(), FakeBackend(), store=ConversationStore(database)
    )
    first = first_service.turn(_request(
        "ask", message="我的 Redis 实例无法连接", backend_token="token-a"
    ))

    restarted = ControlledAgentService(
        FakeAnswers(), FakeBackend(), store=ConversationStore(database)
    )
    resumed = restarted.turn(
        _request(
            "unresolved", conversation_id=first.conversation_id, backend_token="token-a"
        )
    )

    assert resumed.state == AgentState.WAITING_DEVICE_AUTHORIZATION
    assert restarted.conversations[first.conversation_id].step_count == 2
    history = restarted.conversation_history(first.conversation_id, "token-a")
    assert [turn.user_message for turn in history.turns] == [
        "我的 Redis 实例无法连接",
        "仍未解决",
    ]
    assert history.turns[0].response.citations[0].evidence_id == "E1"
    assert restarted.list_conversations("token-a")[0].id == first.conversation_id
    assert restarted.list_conversations("token-a-renewed")[0].id == first.conversation_id
    assert restarted.list_conversations("token-b") == []


def test_conceptual_refusal_offers_labeled_general_answer_without_device_access() -> None:
    backend = FakeBackend()
    agent = ControlledAgentService(RefusingAnswers(), backend)

    first = agent.turn(_request(
        "ask", message="缓存雪崩、击穿和穿透有什么区别？", backend_token="token-a"
    ))
    assert first.state == AgentState.WAITING_GENERAL_ANSWER_CONFIRMATION
    assert first.required_action == "general_answer_or_stop"
    assert backend.device_calls == 0

    general = agent.turn(_request(
        "general_answer", conversation_id=first.conversation_id, backend_token="token-a"
    ))
    assert general.state == AgentState.COMPLETED
    assert "无知识库证据" in general.message
    assert general.tool_events[0].tool == "general_knowledge"
    assert backend.device_calls == 0


def test_grounded_conceptual_answer_does_not_route_to_device_when_unresolved() -> None:
    backend = FakeBackend()
    agent = ControlledAgentService(FakeAnswers(), backend)
    first = agent.turn(_request(
        "ask", message="appendfsync everysec 是什么？", backend_token="token-a"
    ))

    next_turn = agent.turn(_request(
        "unresolved", conversation_id=first.conversation_id, backend_token="token-a"
    ))
    assert next_turn.required_action == "general_answer_or_stop"
    assert backend.device_calls == 0
