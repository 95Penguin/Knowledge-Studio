import json

from fastapi.testclient import TestClient

from app.generation.runtime import get_answer_service
from app.generation.service import GroundedAnswerService
from app.main import app
from app.retrieval.models import SearchResult


def _result(score: float = 0.99) -> SearchResult:
    return SearchResult(
        rank=1,
        score=score,
        chunk_id="chunk-1",
        title="Redis persistence",
        section_path=["Append-only file", "Durability"],
        source_path="content/persistence.md",
        source_url="https://redis.io/docs/latest/persistence/",
        content="appendfsync everysec may lose about one second of data in a disaster.",
    )


class FixedRetriever:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.results[:top_k]


class FixedLLM:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        assert "[E1]" in user_prompt
        return json.dumps(self.payload)


def test_answer_maps_model_evidence_id_to_program_owned_citation() -> None:
    llm = FixedLLM(
        {
            "answer": "故障时可能丢失约一秒数据。[E1]",
            "citation_ids": ["E1"],
            "should_refuse": False,
        }
    )
    response = GroundedAnswerService(FixedRetriever([_result()]), llm).answer("风险是什么？")
    assert response.status == "answered"
    assert response.citations[0].chunk_id == "chunk-1"
    assert response.citations[0].source_url.startswith("https://redis.io/")
    assert response.trace is not None
    assert response.trace.request_id
    assert response.trace.total_ms >= 0


def test_low_evidence_score_refuses_without_calling_llm() -> None:
    llm = FixedLLM({})
    response = GroundedAnswerService(
        FixedRetriever([_result(0.01)]), llm, evidence_score_threshold=0.1
    ).answer("PostgreSQL VACUUM?")
    assert response.status == "refused"
    assert response.citations == []
    assert llm.calls == 0


def test_hallucinated_citation_is_rejected() -> None:
    llm = FixedLLM(
        {
            "answer": "Unsupported claim.",
            "citation_ids": ["E99"],
            "should_refuse": False,
        }
    )
    response = GroundedAnswerService(FixedRetriever([_result()]), llm).answer("question")
    assert response.status == "refused"
    assert "不存在" in response.refusal_reason


def test_model_can_abstain_even_when_retrieval_passes_threshold() -> None:
    llm = FixedLLM(
        {
            "answer": "",
            "citation_ids": [],
            "should_refuse": True,
            "refusal_reason": "Evidence does not contain the required default value.",
        }
    )
    response = GroundedAnswerService(FixedRetriever([_result()]), llm).answer("question")
    assert response.status == "refused"
    assert "required default value" in response.refusal_reason


def test_malformed_model_output_fails_closed() -> None:
    class BrokenLLM:
        def generate(self, system_prompt: str, user_prompt: str) -> str:
            return "not-json"

    response = GroundedAnswerService(FixedRetriever([_result()]), BrokenLLM()).answer("question")
    assert response.status == "refused"
    assert response.citations == []


def test_answer_http_endpoint_uses_grounded_service() -> None:
    llm = FixedLLM(
        {
            "answer": "可能丢失约一秒的数据。[E1]",
            "citation_ids": ["E1"],
            "should_refuse": False,
        }
    )
    service = GroundedAnswerService(FixedRetriever([_result()]), llm)
    app.dependency_overrides[get_answer_service] = lambda: service
    try:
        response = TestClient(app).post(
            "/api/knowledge/answer",
            json={"question": "appendfsync everysec有什么风险？"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["citations"][0]["chunk_id"] == "chunk-1"


def test_knowledge_stream_emits_typed_answer_citation_followup_and_complete_events() -> None:
    llm = FixedLLM({
        "answer": "使用混合检索。[E1]", "citation_ids": ["E1"],
        "suggested_questions": ["RRF 如何融合？"], "should_refuse": False,
    })
    app.dependency_overrides[get_answer_service] = lambda: GroundedAnswerService(
        FixedRetriever([_result()]), llm
    )
    try:
        response = TestClient(app).post(
            "/api/knowledge/stream", json={"question": "如何检索？"}
        )
    finally:
        app.dependency_overrides.clear()
    events = [frame.splitlines()[0] for frame in response.text.split("\n\n") if frame]
    assert response.status_code == 200
    assert "event: answer_delta" in events
    assert "event: citation" in events
    assert "event: follow_up" in events
    assert events[-1] == "event: complete"
