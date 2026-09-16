import math
from collections.abc import Sequence
from pathlib import Path

from app.retrieval.dense import DenseIndex, document_embedding_text


class FakeEncoder:
    model_name = "fake-multilingual"
    model_revision = "test-revision"
    dimension = 2

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        raw = [1.0, 0.0] if "latency" in text.lower() or "延迟" in text else [0.0, 1.0]
        norm = math.sqrt(sum(value * value for value in raw))
        return [value / norm for value in raw]


def _chunk(chunk_id: str, title: str, content: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "title": title,
        "section_path": [title],
        "source_path": f"content/{chunk_id}.md",
        "source_url": f"https://redis.io/{chunk_id}",
        "content": content,
    }


def test_document_embedding_text_contains_structure() -> None:
    text = document_embedding_text(_chunk("latency", "Latency Doctor", "Find spikes."))
    assert text == "Latency Doctor\nLatency Doctor\nFind spikes."


def test_dense_index_supports_cross_language_semantics_and_round_trip(tmp_path: Path) -> None:
    encoder = FakeEncoder()
    index = DenseIndex.build(
        [
            _chunk("latency", "Latency", "Diagnose latency spikes."),
            _chunk("memory", "Memory", "Inspect memory usage."),
        ],
        encoder,
    )
    assert index.search("如何排查延迟", top_k=1)[0].chunk_id == "latency"
    path = tmp_path / "dense.json"
    index.save(path)
    assert DenseIndex.load(path, encoder).search("memory", top_k=1)[0].chunk_id == "memory"
