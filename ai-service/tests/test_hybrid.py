from app.retrieval.hybrid import RRFHybridRetriever
from app.retrieval.models import SearchResult


def _result(chunk_id: str, rank: int, score: float) -> SearchResult:
    return SearchResult(
        rank=rank,
        score=score,
        chunk_id=chunk_id,
        title=chunk_id,
        section_path=[chunk_id],
        source_path=f"content/{chunk_id}.md",
        source_url=f"https://redis.io/{chunk_id}",
        content=chunk_id,
    )


class FixedRetriever:
    def __init__(self, results: list[SearchResult], name: str) -> None:
        self.results = results
        self.retriever_name = name

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.results[:top_k]


def test_rrf_promotes_document_found_by_both_retrievers() -> None:
    lexical = FixedRetriever([_result("lexical-only", 1, 9.0), _result("both", 2, 8.0)], "bm25")
    dense = FixedRetriever([_result("dense-only", 1, 0.9), _result("both", 2, 0.8)], "dense")
    retriever = RRFHybridRetriever(lexical, dense, candidate_k=2, rrf_k=60)
    results = retriever.search("query", top_k=3)
    assert results[0].chunk_id == "both"
    assert results[0].retrieval_details == {
        "components": {
            "bm25": {"rank": 2, "score": 8.0, "weight": 1.0, "rrf_contribution": 0.01612903},
            "dense": {"rank": 2, "score": 0.8, "weight": 1.0, "rrf_contribution": 0.01612903},
        }
    }


def test_rrf_keeps_single_source_candidates() -> None:
    lexical = FixedRetriever([_result("lexical", 1, 5.0)], "bm25")
    dense = FixedRetriever([_result("dense", 1, 0.7)], "dense")
    results = RRFHybridRetriever(lexical, dense, candidate_k=1).search("query", top_k=2)
    assert {result.chunk_id for result in results} == {"lexical", "dense"}


def test_weighted_rrf_can_prioritize_dense_results() -> None:
    lexical = FixedRetriever([_result("lexical", 1, 10.0)], "bm25")
    dense = FixedRetriever([_result("dense", 1, 0.9)], "dense")
    retriever = RRFHybridRetriever(
        lexical, dense, candidate_k=1, lexical_weight=1.0, dense_weight=4.0
    )

    results = retriever.search("query", top_k=2)

    assert results[0].chunk_id == "dense"
    assert retriever.retriever_name == "weighted-rrf-dense-4-bm25-1"
