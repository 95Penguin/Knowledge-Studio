from typing import Any, Protocol

from app.observability.trace import trace_stage
from app.retrieval.models import SearchResult


class Retriever(Protocol):
    def search(self, query: str, top_k: int = 5) -> list[SearchResult]: ...


class RRFHybridRetriever:
    """Weighted reciprocal rank fusion over lexical and dense candidate lists."""

    def __init__(
        self,
        lexical: Retriever,
        dense: Retriever,
        candidate_k: int = 20,
        rrf_k: int = 60,
        lexical_weight: float = 1.0,
        dense_weight: float = 1.0,
    ) -> None:
        if candidate_k < 1:
            raise ValueError("candidate_k must be positive")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if lexical_weight <= 0 or dense_weight <= 0:
            raise ValueError("RRF weights must be positive")
        self.lexical = lexical
        self.dense = dense
        self.candidate_k = candidate_k
        self.rrf_k = rrf_k
        self.lexical_weight = lexical_weight
        self.dense_weight = dense_weight

    @property
    def retriever_name(self) -> str:
        if self.lexical_weight == self.dense_weight == 1.0:
            return "rrf-hybrid"
        return (
            f"weighted-rrf-dense-{_weight_label(self.dense_weight)}"
            f"-bm25-{_weight_label(self.lexical_weight)}"
        )

    @property
    def retriever_parameters(self) -> dict[str, Any]:
        return {
            "lexical": getattr(self.lexical, "retriever_name", "lexical"),
            "dense": getattr(self.dense, "retriever_name", "dense"),
            "candidate_k_per_retriever": self.candidate_k,
            "rrf_k": self.rrf_k,
            "lexical_weight": self.lexical_weight,
            "dense_weight": self.dense_weight,
        }

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        lexical_results = self.lexical.search(query, top_k=self.candidate_k)
        dense_results = self.dense.search(query, top_k=self.candidate_k)

        with trace_stage("rrf_fusion"):
            fused: dict[str, dict[str, Any]] = {}
            self._add_results(fused, lexical_results, "bm25", self.lexical_weight)
            self._add_results(fused, dense_results, "dense", self.dense_weight)
            ranked = sorted(
                fused.values(),
                key=lambda item: (-item["rrf_score"], item["result"].chunk_id),
            )[:top_k]
            return [self._to_result(item, rank) for rank, item in enumerate(ranked, start=1)]

    def _add_results(
        self,
        fused: dict[str, dict[str, Any]],
        results: list[SearchResult],
        source: str,
        weight: float,
    ) -> None:
        for result in results:
            item = fused.setdefault(
                result.chunk_id,
                {"result": result, "rrf_score": 0.0, "components": {}},
            )
            contribution = weight / (self.rrf_k + result.rank)
            item["rrf_score"] += contribution
            item["components"][source] = {
                "rank": result.rank,
                "score": round(result.score, 6),
                "weight": weight,
                "rrf_contribution": round(contribution, 8),
            }

    @staticmethod
    def _to_result(item: dict[str, Any], rank: int) -> SearchResult:
        original: SearchResult = item["result"]
        return SearchResult(
            rank=rank,
            score=item["rrf_score"],
            chunk_id=original.chunk_id,
            title=original.title,
            section_path=original.section_path,
            source_path=original.source_path,
            source_url=original.source_url,
            content=original.content,
            source_type=original.source_type,
            retrieval_details={"components": item["components"]},
        )


def _weight_label(weight: float) -> str:
    numeric = float(weight)
    return str(int(numeric)) if numeric.is_integer() else str(numeric).replace(".", "p")
