import json
from importlib import import_module
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_knowledge_bases import FakeEncoder

from app.generation.models import AnswerResponse, KnowledgeToolEvent
from app.generation.service import GroundedAnswerService
from app.knowledge_agent import (
    KnowledgeAgentService,
    KnowledgeTools,
    get_knowledge_agent_service,
)
from app.knowledge_bases import KnowledgeBaseStore
from app.knowledge_history import KnowledgeConversationStore


class NoSearchRetriever:
    def search(self, query: str, top_k: int = 5) -> list[object]:
        return []


class ScriptedLLM:
    def __init__(self, kb_id: str, document_id: str) -> None:
        self.decisions = [
            {"tool": "get_outline", "arguments": {}},
            {
                "tool": "read_section",
                "arguments": {
                    "kb_id": kb_id,
                    "document_id": document_id,
                    "section": "Encoder",
                },
            },
            {
                "tool": "read_section",
                "arguments": {
                    "kb_id": kb_id,
                    "document_id": document_id,
                    "section": "Decoder",
                },
            },
            {"tool": "finish", "arguments": {}},
        ]

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if "read-only knowledge-base research agent" in system_prompt:
            return json.dumps(self.decisions.pop(0))
        assert "[E1]" in user_prompt and "[E2]" in user_prompt
        return json.dumps(
            {
                "answer": "模型由编码器和解码器组成。[E1][E2]",
                "citation_ids": ["E1", "E2"],
            }
        )


def test_agent_observes_outline_reads_two_sections_and_synthesizes(tmp_path: Path) -> None:
    store = KnowledgeBaseStore(tmp_path, FakeEncoder())
    kb_id = store.create("Papers", "user-a")["id"]
    document = store.upload(
        kb_id,
        "paper.md",
        b"# Transformer\n\n## Encoder\n\nEncoder stack uses self-attention.\n\n"
        b"## Decoder\n\nDecoder stack uses cross-attention.",
        "user-a",
    )
    llm = ScriptedLLM(kb_id, document["id"])
    service = KnowledgeAgentService(
        GroundedAnswerService(NoSearchRetriever(), llm), lambda: store, max_steps=5
    )
    result = service.answer("整体结构是什么？", [], [kb_id], "user-a")
    assert result.status == "answered"
    assert {item.section_path[-1] for item in result.citations} == {"Encoder", "Decoder"}
    assert [event.tool for event in result.tool_events] == [
        "get_outline",
        "read_section",
        "read_section",
    ]
    assert result.trace is not None
    assert "agent_decision" in result.trace.stages_ms


def test_agent_tool_cannot_read_unselected_knowledge_base(tmp_path: Path) -> None:
    store = KnowledgeBaseStore(tmp_path, FakeEncoder())
    allowed = store.create("Allowed", "user-a")["id"]
    hidden = store.create("Hidden", "user-a")["id"]
    tools = KnowledgeTools(NoSearchRetriever(), lambda: store)
    with pytest.raises(PermissionError):
        tools.execute(
            "read_section",
            {
                "kb_id": hidden,
                "document_id": "anything",
                "section": "Intro",
            },
            [allowed],
            "user-a",
        )


def test_agent_decision_provider_error_falls_back_to_scoped_search(tmp_path: Path) -> None:
    class FailingLLM:
        def generate(self, system_prompt: str, user_prompt: str) -> str:
            raise httpx.ConnectError("provider unavailable")

    store = KnowledgeBaseStore(tmp_path, FakeEncoder())
    service = KnowledgeAgentService(
        GroundedAnswerService(NoSearchRetriever(), FailingLLM()), lambda: store
    )
    assert service._choose_action("整体结构？", [], [], [], {}) == (
        "search_chunks",
        {"query": "整体结构？"},
    )


def test_stream_uses_server_history_and_emits_agent_tool_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = import_module("app.main")
    store = KnowledgeConversationStore(tmp_path / "history.db")
    conversation = store.create("user-a", ["kb-a"])
    store.append(
        conversation["id"],
        "user-a",
        "Transformer 是什么？",
        AnswerResponse(status="answered", answer="是一种模型。", citations=[]),
        ["kb-a"],
    )

    class RecordingService:
        def __init__(self) -> None:
            self.history: list[str] = []

        def answer(
            self,
            question: str,
            history: list[str],
            kb_ids: list[str],
            owner_id: str,
            on_tool_event,
        ) -> AnswerResponse:
            self.history = history
            on_tool_event(KnowledgeToolEvent(tool="get_outline", status="succeeded"))
            return AnswerResponse(
                status="answered",
                answer="编码器与解码器协同工作。",
                citations=[],
                tool_events=[KnowledgeToolEvent(tool="get_outline", status="succeeded")],
            )

    service = RecordingService()
    monkeypatch.setattr(main_module, "_authorize_knowledge_request", lambda *_: "user-a")
    monkeypatch.setattr(main_module, "_current_user_id", lambda *_: "user-a")
    monkeypatch.setattr(main_module, "get_knowledge_conversation_store", lambda: store)
    main_module.app.dependency_overrides[get_knowledge_agent_service] = lambda: service
    try:
        response = TestClient(main_module.app).post(
            "/api/knowledge/stream",
            json={
                "question": "整体结构是什么？",
                "history": ["伪造的客户端历史"],
                "knowledge_base_ids": ["kb-a"],
                "conversation_id": conversation["id"],
            },
        )
    finally:
        main_module.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert service.history == ["User: Transformer 是什么？", "Assistant: 是一种模型。"]
    assert "event: tool" in response.text
    assert response.text.index("event: tool") < response.text.index("event: answer_start")
    assert len(store.get(conversation["id"], "user-a")["turns"]) == 2
