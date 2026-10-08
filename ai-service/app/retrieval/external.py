"""Optional Elasticsearch and Milvus adapters for the built-in corpus."""

import json
from typing import Any

import httpx

from app.observability.trace import trace_stage
from app.retrieval.dense import EmbeddingEncoder, document_embedding_text
from app.retrieval.models import SearchResult


def _result(chunk: dict[str, Any], rank: int, score: float) -> SearchResult:
    return SearchResult(
        rank=rank, score=score, chunk_id=chunk["chunk_id"], title=chunk["title"],
        section_path=chunk["section_path"], source_path=chunk["source_path"],
        source_url=chunk["source_url"], content=chunk["content"],
        source_type=chunk.get("source_type", "official"),
    )


class ElasticsearchKeywordIndex:
    retriever_name = "elasticsearch-keyword"

    def __init__(self, url: str, index: str, api_key: str = "", timeout: float = 10.0) -> None:
        if not url or not index:
            raise ValueError("Elasticsearch URL and index are required")
        self.url = url.rstrip("/")
        self.index = index
        self.timeout = timeout
        self.headers = {"Authorization": f"ApiKey {api_key}"} if api_key else {}

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        with trace_stage("elasticsearch_search"):
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.url}/{self.index}/_search", headers=self.headers,
                    json={"size": top_k, "query": {"multi_match": {
                        "query": query, "fields": ["title^3", "section_path^2", "content"],
                    }}},
                )
            response.raise_for_status()
            hits = response.json()["hits"]["hits"]
        return [_result(hit["_source"], rank, float(hit["_score"]))
                for rank, hit in enumerate(hits, 1)]

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        with httpx.Client(timeout=self.timeout) as client:
            exists = client.head(f"{self.url}/{self.index}", headers=self.headers)
            if exists.status_code == 404:
                created = client.put(
                    f"{self.url}/{self.index}", headers=self.headers,
                    json={"mappings": {"properties": {
                        "title": {"type": "text"}, "section_path": {"type": "text"},
                        "content": {"type": "text"}, "chunk_id": {"type": "keyword"},
                        "source_path": {"type": "keyword"},
                    }}},
                )
                created.raise_for_status()
            else:
                exists.raise_for_status()
            for offset in range(0, len(chunks), 100):
                lines = []
                for chunk in chunks[offset:offset + 100]:
                    lines.append(json.dumps({"index": {"_index": self.index, "_id": chunk["chunk_id"]}}))
                    lines.append(json.dumps(chunk, ensure_ascii=False))
                response = client.post(
                    f"{self.url}/_bulk", headers={**self.headers, "Content-Type": "application/x-ndjson"},
                    content="\n".join(lines) + "\n",
                )
                response.raise_for_status()
                if response.json().get("errors"):
                    raise RuntimeError("Elasticsearch bulk indexing reported item errors")


class MilvusDenseIndex:
    retriever_name = "milvus-dense"

    def __init__(
        self, url: str, collection: str, token: str, encoder: EmbeddingEncoder,
        chunks: list[dict[str, Any]], timeout: float = 10.0,
    ) -> None:
        if not url or not collection or not token:
            raise ValueError("Milvus URL, collection and token are required")
        self.url = url.rstrip("/")
        self.collection = collection
        self.encoder = encoder
        self.chunks = {chunk["chunk_id"]: chunk for chunk in chunks}
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {token}"}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.url}{path}", headers=self.headers, json=payload)
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"Milvus error: {body.get('message', body.get('code'))}")
        return body

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        with trace_stage("milvus_search"):
            vector = self.encoder.encode_queries([query])[0]
            body = self._post("/v2/vectordb/entities/search", {
                "collectionName": self.collection, "data": [vector],
                "annsField": "vector", "limit": top_k,
            })
        matches = []
        for hit in body.get("data", []):
            chunk = self.chunks.get(str(hit.get("id")))
            if chunk:
                matches.append(_result(chunk, len(matches) + 1, float(hit["distance"])))
        return matches

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        existing = self._post("/v2/vectordb/collections/list", {}).get("data", [])
        if self.collection not in existing:
            self._post("/v2/vectordb/collections/create", {
                "collectionName": self.collection, "dimension": self.encoder.dimension,
                "idType": "VarChar", "primaryFieldName": "id", "vectorFieldName": "vector",
                "autoId": False, "metricType": "COSINE", "params": {"max_length": "64"},
            })
        for offset in range(0, len(chunks), 50):
            batch = chunks[offset:offset + 50]
            vectors = self.encoder.encode_documents([document_embedding_text(chunk) for chunk in batch])
            self._post("/v2/vectordb/entities/upsert", {
                "collectionName": self.collection,
                "data": [{"id": chunk["chunk_id"], "vector": vector}
                         for chunk, vector in zip(batch, vectors, strict=True)],
            })
