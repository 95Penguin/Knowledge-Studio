from app.retrieval.models import SearchResult
from app.retrieval.planning import PlannedRetriever, QueryPlanner


class QueryAwareRetriever:
    retriever_name = "query-aware"

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        chunk_id = "shared" if "RRF" in query else query
        return [SearchResult(
            rank=1, score=0.8, chunk_id=chunk_id, title=query, section_path=[query],
            source_path="kb/chunk.md", source_url="/chunk", content=query,
        )]


def test_planner_rewrites_context_dependent_question_and_splits_compound_query() -> None:
    plan = QueryPlanner().plan("这个如何配置；同时怎么评测", ["RRF 融合有什么作用"])
    assert plan.rewritten.startswith("RRF 融合有什么作用")
    assert len(plan.subqueries) == 3


def test_planned_retriever_deduplicates_chunks_across_subqueries() -> None:
    retriever = PlannedRetriever(QueryAwareRetriever(), candidate_k=3)
    results = retriever.search("RRF是什么；同时RRF怎么调参", top_k=5)
    assert [result.chunk_id for result in results] == ["shared"]
    assert len(results[0].retrieval_details["matched_queries"]) >= 2
