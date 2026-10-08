from collections.abc import Sequence
from typing import Any, Protocol

from app.observability.trace import trace_stage
from app.retrieval.models import SearchResult

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"
DEFAULT_RERANKER_REVISION = "a2ea80a31f4bb01c0b2db0a472a1512b6e5a4400"


class PairScorer(Protocol):
    model_name: str
    model_revision: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class BGERerankerScorer:
    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        model_revision: str = DEFAULT_RERANKER_REVISION,
        batch_size: int = 4,
        max_length: int = 512,
    ) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as error:
            raise RuntimeError(
                "Reranker dependencies are missing. Run with `uv run --extra embeddings`."
            ) from error
        self.model_name = model_name
        self.model_revision = model_revision
        self.batch_size = batch_size
        self.max_length = max_length
        self.model = CrossEncoder(
            model_name,
            revision=model_revision,
            device="cpu",
            max_length=max_length,
        )

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        pairs = [(query, passage) for passage in passages]
        scores = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=len(pairs) > self.batch_size,
            convert_to_numpy=True,
        )
        return [float(score) for score in scores]


def reranker_passage(result: SearchResult) -> str:
    section = " > ".join(result.section_path)
    return f"{result.title}\n{section}\n{result.content}"


class RerankingRetriever:
    retriever_name = "rrf-hybrid-cross-encoder-rerank"

    def __init__(self, candidate_retriever: Any, scorer: PairScorer, rerank_k: int = 10) -> None:
        if rerank_k < 1:
            raise ValueError("rerank_k must be positive")
        self.candidate_retriever = candidate_retriever
        self.scorer = scorer
        self.rerank_k = rerank_k

    @property
    def retriever_parameters(self) -> dict[str, Any]:
        return {
            "candidate_retriever": self.candidate_retriever.retriever_name,
            "candidate_parameters": self.candidate_retriever.retriever_parameters,
            "rerank_k": self.rerank_k,
            "reranker_model": self.scorer.model_name,
            "reranker_revision": self.scorer.model_revision,
        }

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.search_scoped(query, top_k, ())

    def search_scoped(
        self, query: str, top_k: int, knowledge_base_ids: tuple[str, ...]
    ) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        if hasattr(self.candidate_retriever, "search_scoped"):
            candidates = self.candidate_retriever.search_scoped(
                query, self.rerank_k, knowledge_base_ids
            )
        else:
            candidates = self.candidate_retriever.search(query, top_k=self.rerank_k)
        if not candidates:
            return []
        with trace_stage("reranker"):
            scores = self.scorer.score(query, [reranker_passage(result) for result in candidates])
        rescored = sorted(
            zip(candidates, scores, strict=True),
            key=lambda item: (-item[1], item[0].chunk_id),
        )[:top_k]
        return [
            self._to_result(candidate, score, rank)
            for rank, (candidate, score) in enumerate(rescored, start=1)
        ]

    def _to_result(self, candidate: SearchResult, score: float, rank: int) -> SearchResult:
        details = dict(candidate.retrieval_details or {})
        details["before_rerank"] = {"rank": candidate.rank, "rrf_score": candidate.score}
        details["reranker"] = {
            "model": self.scorer.model_name,
            "model_revision": self.scorer.model_revision,
            "score": round(score, 6),
        }
        return SearchResult(
            rank=rank,
            score=score,
            chunk_id=candidate.chunk_id,
            title=candidate.title,
            section_path=candidate.section_path,
            source_path=candidate.source_path,
            source_url=candidate.source_url,
            content=candidate.content,
            source_type=candidate.source_type,
            retrieval_details=details,
        )
