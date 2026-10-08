"""Small, inspectable query planner for multi-turn knowledge questions."""

import re
from dataclasses import dataclass

from app.observability.trace import trace_stage
from app.retrieval.hybrid import Retriever
from app.retrieval.models import SearchResult


@dataclass(frozen=True)
class QueryPlan:
    original: str
    rewritten: str
    subqueries: tuple[str, ...]
    knowledge_base_ids: tuple[str, ...] = ()


class QueryPlanner:
    def plan(
        self,
        question: str,
        history: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
    ) -> QueryPlan:
        question = question.strip()
        if not question:
            raise ValueError("question must not be blank")
        history = [item.strip() for item in (history or []) if item.strip()]
        rewritten = question
        # Keep the current question untouched unless it explicitly depends on prior context.
        if history and re.search(
            r"^(它|这个|那|上述|刚才|这种|其|那么|what about|and )",
            question,
            re.IGNORECASE,
        ):
            rewritten = f"{history[-1][:240]}；{question}"
        parts = [part.strip(" ，,。;；") for part in re.split(r"[；;]|(?:并且|同时|以及)", rewritten)]
        parts = [part for part in parts if part]
        # Preserve a broad query for recall and add at most two focused queries.
        subqueries = tuple(dict.fromkeys([rewritten, *parts[:2]]))
        return QueryPlan(question, rewritten, subqueries, tuple(knowledge_base_ids or ()))


class PlannedRetriever:
    """Run broad and focused queries, then fuse duplicate chunks across queries."""

    retriever_name = "planned-multi-query"

    def __init__(self, retriever: Retriever, planner: QueryPlanner | None = None, candidate_k: int = 10):
        if candidate_k < 1:
            raise ValueError("candidate_k must be positive")
        self.retriever = retriever
        self.planner = planner or QueryPlanner()
        self.candidate_k = candidate_k

    @property
    def retriever_parameters(self) -> dict[str, object]:
        return {"candidate_retriever": getattr(self.retriever, "retriever_name", "unknown")}

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.search_plan(self.planner.plan(query), top_k)

    def search_plan(self, plan: QueryPlan, top_k: int = 5) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        with trace_stage("query_planning"):
            queries = plan.subqueries
        fused: dict[str, tuple[SearchResult, float, list[str]]] = {}
        for query in queries:
            if hasattr(self.retriever, "search_scoped"):
                candidates = self.retriever.search_scoped(
                    query, self.candidate_k, plan.knowledge_base_ids
                )
            else:
                candidates = self.retriever.search(query, self.candidate_k)
            for rank, result in enumerate(candidates, 1):
                if plan.knowledge_base_ids and not any(
                    result.source_path.startswith(f"{kb}/") for kb in plan.knowledge_base_ids
                ):
                    continue
                previous = fused.get(result.chunk_id)
                score = 1 / (60 + rank)
                if previous:
                    fused[result.chunk_id] = (previous[0], previous[1] + score, previous[2] + [query])
                else:
                    fused[result.chunk_id] = (result, score, [query])
        ranked = sorted(fused.values(), key=lambda item: (-item[1], item[0].chunk_id))[:top_k]
        return [
            SearchResult(
                rank=index, score=result.score, chunk_id=result.chunk_id, title=result.title,
                section_path=result.section_path, source_path=result.source_path,
                source_url=result.source_url, content=result.content, source_type=result.source_type,
                retrieval_details={**(result.retrieval_details or {}), "matched_queries": queries},
            )
            for index, (result, _, queries) in enumerate(ranked, 1)
        ]
