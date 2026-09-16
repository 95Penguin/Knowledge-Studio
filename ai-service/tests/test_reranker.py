from collections.abc import Sequence
from typing import ClassVar

from app.retrieval.models import SearchResult
from app.retrieval.reranker import RerankingRetriever, reranker_passage


def _result(chunk_id: str, rank: int, content: str) -> SearchResult:
    return SearchResult(
        rank=rank,
        score=1 / (60 + rank),
        chunk_id=chunk_id,
        title=chunk_id,
        section_path=["Details"],
        source_path=f"content/{chunk_id}.md",
        source_url=f"https://redis.io/{chunk_id}",
        content=content,
        retrieval_details={"components": {"dense": {"rank": rank}}},
    )


class FixedCandidates:
    retriever_name = "fixed-rrf"
    retriever_parameters: ClassVar[dict[str, int]] = {"candidate_k": 2}

    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.results[:top_k]


class KeywordScorer:
    model_name = "fake-reranker"
    model_revision = "test"

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return [10.0 if "REPLICAOF NO ONE" in passage else -2.0 for passage in passages]


def test_reranker_promotes_answering_passage_and_preserves_trace() -> None:
    candidates = FixedCandidates(
        [
            _result("generic", 1, "General replication text."),
            _result("replicaof", 2, "Use REPLICAOF NO ONE to promote the replica."),
        ]
    )
    retriever = RerankingRetriever(candidates, KeywordScorer(), rerank_k=2)
    results = retriever.search("How to promote a replica?", top_k=2)
    assert results[0].chunk_id == "replicaof"
    assert results[0].retrieval_details["before_rerank"]["rank"] == 2
    assert results[0].retrieval_details["reranker"]["score"] == 10.0


def test_reranker_passage_contains_title_section_and_content() -> None:
    passage = reranker_passage(_result("INFO", 1, "Server fields."))
    assert passage == "INFO\nDetails\nServer fields."
