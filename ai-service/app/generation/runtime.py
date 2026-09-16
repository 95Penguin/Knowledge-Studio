from functools import lru_cache

from app.config import get_settings
from app.generation.llm import OpenAICompatibleChatClient
from app.generation.service import GroundedAnswerService
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex, SentenceTransformerE5Encoder
from app.retrieval.hybrid import RRFHybridRetriever
from app.retrieval.reranker import BGERerankerScorer, RerankingRetriever


@lru_cache
def get_answer_service() -> GroundedAnswerService:
    settings = get_settings()
    root = settings.project_root
    # Validate generation configuration before loading the two comparatively
    # expensive local retrieval models.
    llm = OpenAICompatibleChatClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    encoder = SentenceTransformerE5Encoder()
    bm25 = BM25Index.load(root / "data/indexes/bm25/index.json")
    dense = DenseIndex.load(root / "data/indexes/dense/multilingual-e5-base.json", encoder)
    hybrid = RRFHybridRetriever(bm25, dense, candidate_k=20, rrf_k=60)
    retriever = RerankingRetriever(hybrid, BGERerankerScorer(), rerank_k=10)
    return GroundedAnswerService(
        retriever,
        llm,
        top_k=settings.answer_top_k,
        evidence_score_threshold=settings.evidence_score_threshold,
    )
