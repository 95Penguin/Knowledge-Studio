import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.observability.trace import trace_stage
from app.retrieval.models import SearchResult
from app.retrieval.tokenizer import searchable_tokens, tokenize


class BM25Index:
    """A compact, auditable Okapi BM25 inverted index."""

    schema_version = 1
    retriever_name = "okapi-bm25"

    def __init__(
        self,
        documents: list[dict[str, Any]],
        postings: dict[str, list[list[int]]],
        document_lengths: list[int],
        average_document_length: float,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.documents = documents
        self.postings = postings
        self.document_lengths = document_lengths
        self.average_document_length = average_document_length
        self.k1 = k1
        self.b = b

    @property
    def retriever_parameters(self) -> dict[str, float]:
        return {"k1": self.k1, "b": self.b}

    @classmethod
    def build(cls, chunks: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> "BM25Index":
        if not chunks:
            raise ValueError("Cannot build a BM25 index without chunks")
        postings: dict[str, list[list[int]]] = defaultdict(list)
        lengths: list[int] = []
        for document_id, chunk in enumerate(chunks):
            frequencies = Counter(searchable_tokens(chunk))
            length = sum(frequencies.values())
            lengths.append(length)
            for term, frequency in frequencies.items():
                postings[term].append([document_id, frequency])
        return cls(
            documents=chunks,
            postings=dict(postings),
            document_lengths=lengths,
            average_document_length=sum(lengths) / len(lengths),
            k1=k1,
            b=b,
        )

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        with trace_stage("bm25"):
            return self._search(query, top_k)

    def _search(self, query: str, top_k: int) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        query_frequencies = Counter(tokenize(query))
        scores: dict[int, float] = defaultdict(float)
        document_count = len(self.documents)
        for term, query_frequency in query_frequencies.items():
            term_postings = self.postings.get(term, [])
            document_frequency = len(term_postings)
            if document_frequency == 0:
                continue
            inverse_document_frequency = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            for document_id, term_frequency in term_postings:
                length = self.document_lengths[document_id]
                normalization = self.k1 * (
                    1 - self.b + self.b * length / self.average_document_length
                )
                term_score = inverse_document_frequency * (
                    term_frequency * (self.k1 + 1) / (term_frequency + normalization)
                )
                scores[document_id] += query_frequency * term_score

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
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
            "algorithm": "okapi-bm25",
            "parameters": {"k1": self.k1, "b": self.b},
            "document_count": len(self.documents),
            "average_document_length": self.average_document_length,
            "documents": self.documents,
            "document_lengths": self.document_lengths,
            "postings": self.postings,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != cls.schema_version:
            raise ValueError(f"Unsupported BM25 index schema: {payload.get('schema_version')}")
        return cls(
            documents=payload["documents"],
            postings=payload["postings"],
            document_lengths=payload["document_lengths"],
            average_document_length=payload["average_document_length"],
            k1=payload["parameters"]["k1"],
            b=payload["parameters"]["b"],
        )
