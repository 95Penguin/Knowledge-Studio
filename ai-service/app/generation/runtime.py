from functools import lru_cache

from app.config import get_settings
from app.generation.llm import OpenAICompatibleChatClient
from app.generation.service import GroundedAnswerService
from app.knowledge_bases import KnowledgeBaseStore, KnowledgeCorpusRetriever
from app.knowledge_history import KnowledgeConversationStore
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex, SentenceTransformerE5Encoder
from app.retrieval.external import ElasticsearchKeywordIndex, MilvusDenseIndex
from app.retrieval.graph import HeadingGraphIndex
from app.retrieval.hybrid import MultiRouteRRFRetriever
from app.retrieval.planning import ModelQueryPlanner, PlannedRetriever
from app.retrieval.reranker import BGERerankerScorer, RerankingRetriever


@lru_cache
def get_embedding_encoder() -> SentenceTransformerE5Encoder:
    return SentenceTransformerE5Encoder()


@lru_cache
def get_knowledge_base_store() -> KnowledgeBaseStore:
    settings = get_settings()
    return KnowledgeBaseStore(
        settings.knowledge_base_path, get_embedding_encoder(), settings.knowledge_max_revisions
    )


@lru_cache
def get_knowledge_conversation_store() -> KnowledgeConversationStore:
    return KnowledgeConversationStore(get_settings().agent_database_path)


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
    encoder = get_embedding_encoder()
    bm25 = BM25Index.load(root / "data/indexes/bm25/index.json")
    dense = DenseIndex.load(root / "data/indexes/dense/multilingual-e5-base.json", encoder)
    graph = HeadingGraphIndex(bm25.documents)
    if settings.retrieval_mode == "external":
        lexical = ElasticsearchKeywordIndex(
            settings.elasticsearch_url,
            settings.elasticsearch_index,
            settings.elasticsearch_api_key,
        )
        vector = MilvusDenseIndex(
            settings.milvus_url,
            settings.milvus_collection,
            settings.milvus_token,
            encoder,
            bm25.documents,
        )
    elif settings.retrieval_mode == "local":
        lexical, vector = bm25, dense
    else:
        raise ValueError("retrieval_mode must be local or external")
    hybrid = MultiRouteRRFRetriever(
        {
            "keyword": (lexical, 1.0),
            "dense": (vector, 1.0),
            "graph": (graph, 0.5),
        },
        candidate_k=20,
        rrf_k=60,
    )
    corpora = KnowledgeCorpusRetriever(hybrid, get_knowledge_base_store())
    retriever = PlannedRetriever(
        RerankingRetriever(corpora, BGERerankerScorer(), rerank_k=10),
        planner=ModelQueryPlanner(llm),
    )
    return GroundedAnswerService(
        retriever,
        llm,
        top_k=settings.answer_top_k,
        evidence_score_threshold=settings.evidence_score_threshold,
    )
