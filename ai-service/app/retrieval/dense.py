import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from app.observability.trace import trace_stage
from app.retrieval.models import SearchResult

DEFAULT_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_MODEL_REVISION = "b1a0e29a27225d956284aec11899fc85b0fe3ad8"


class EmbeddingEncoder(Protocol):
    model_name: str
    model_revision: str
    dimension: int

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]: ...


class SentenceTransformerE5Encoder:
    """Lazy adapter so BM25 and unit tests do not require ML dependencies."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        model_revision: str = DEFAULT_MODEL_REVISION,
        batch_size: int = 16,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "Dense retrieval dependencies are missing. Run with `uv run --extra embeddings`."
            ) from error
        self.model_name = model_name
        self.model_revision = model_revision
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, revision=model_revision, device="cpu")
        self.dimension = self.model.get_embedding_dimension()

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([f"passage: {text}" for text in texts])

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([f"query: {text}" for text in texts])

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > self.batch_size,
            convert_to_numpy=True,
        )
        return vectors.tolist()


def document_embedding_text(chunk: dict[str, Any]) -> str:
    section = " > ".join(chunk["section_path"])
    return f"{chunk['title']}\n{section}\n{chunk['content']}"


class DenseIndex:
    schema_version = 1
    retriever_name = "dense-cosine"

    def __init__(
        self,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
        encoder: EmbeddingEncoder,
    ) -> None:
        if len(documents) != len(embeddings):
            raise ValueError("Documents and embeddings must have the same length")
        self.documents = documents
        self.embeddings = embeddings
        self.encoder = encoder

    @property
    def retriever_parameters(self) -> dict[str, Any]:
        return {
            "model": self.encoder.model_name,
            "model_revision": self.encoder.model_revision,
            "dimension": self.encoder.dimension,
            "similarity": "cosine_via_normalized_dot_product",
        }

    @classmethod
    def build(cls, chunks: list[dict[str, Any]], encoder: EmbeddingEncoder) -> "DenseIndex":
        if not chunks:
            raise ValueError("Cannot build a dense index without chunks")
        texts = [document_embedding_text(chunk) for chunk in chunks]
        embeddings = encoder.encode_documents(texts)
        return cls(chunks, embeddings, encoder)

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        with trace_stage("query_embedding"):
            query_vector = self.encoder.encode_queries([query])[0]
        with trace_stage("dense_search"):
            scored = [
                (document_id, _dot_product(query_vector, vector))
                for document_id, vector in enumerate(self.embeddings)
            ]
            ranked = sorted(scored, key=lambda item: (-item[1], item[0]))[:top_k]
        return [
            self._result(document_id, score, rank)
            for rank, (document_id, score) in enumerate(ranked, start=1)
        ]

    def _result(self, document_id: int, score: float, rank: int) -> SearchResult:
        document = self.documents[document_id]
        return SearchResult(
            rank=rank,
            score=score,
            chunk_id=document["chunk_id"],
            title=document["title"],
            section_path=document["section_path"],
            source_path=document["source_path"],
            source_url=document["source_url"],
            content=document["content"],
            source_type=document.get("source_type", "official"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "algorithm": self.retriever_name,
            "model": self.encoder.model_name,
            "model_revision": self.encoder.model_revision,
            "dimension": self.encoder.dimension,
            "normalized": True,
            "documents": self.documents,
            "embeddings": self.embeddings,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, encoder: EmbeddingEncoder) -> "DenseIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != cls.schema_version:
            raise ValueError(f"Unsupported dense index schema: {payload.get('schema_version')}")
        if payload["model"] != encoder.model_name:
            raise ValueError("Index model does not match the query encoder")
        if payload["model_revision"] != encoder.model_revision:
            raise ValueError("Index model revision does not match the query encoder")
        if payload["dimension"] != encoder.dimension:
            raise ValueError("Index dimension does not match the query encoder")
        return cls(payload["documents"], payload["embeddings"], encoder)


def _dot_product(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Vector dimensions do not match")
    return sum(a * b for a, b in zip(left, right, strict=True))
