"""Synchronize processed chunks into configured ES and Milvus services."""

import json

from app.config import get_settings
from app.retrieval.dense import SentenceTransformerE5Encoder
from app.retrieval.external import ElasticsearchKeywordIndex, MilvusDenseIndex


def main() -> None:
    settings = get_settings()
    root = settings.project_root
    chunks = [json.loads(line) for line in (root / "data/processed/chunks.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    encoder = SentenceTransformerE5Encoder()
    ElasticsearchKeywordIndex(settings.elasticsearch_url, settings.elasticsearch_index,
                              settings.elasticsearch_api_key).upsert_chunks(chunks)
    MilvusDenseIndex(settings.milvus_url, settings.milvus_collection, settings.milvus_token,
                     encoder, chunks).upsert_chunks(chunks)
    print(f"Indexed {len(chunks)} chunks in Elasticsearch and Milvus")


if __name__ == "__main__":
    main()
