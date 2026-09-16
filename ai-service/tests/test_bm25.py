import json
from pathlib import Path

from app.retrieval.bm25 import BM25Index
from app.retrieval.evaluation import evaluate
from app.retrieval.tokenizer import tokenize


def _chunk(chunk_id: str, title: str, content: str, section: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "title": title,
        "section_path": [section],
        "source_path": f"content/{chunk_id}.md",
        "source_url": f"https://redis.io/{chunk_id}",
        "content": content,
    }


def test_tokenizer_preserves_redis_identifiers() -> None:
    assert tokenize("Redis CONFIG SET latency-monitor-threshold 100") == [
        "config",
        "set",
        "latency-monitor-threshold",
        "100",
    ]


def test_bm25_ranks_rare_matching_terms_first(tmp_path: Path) -> None:
    index = BM25Index.build(
        [
            _chunk("latency", "Latency", "Use LATENCY DOCTOR for latency spikes.", "Doctor"),
            _chunk("memory", "Memory", "Use MEMORY DOCTOR for memory issues.", "Doctor"),
        ]
    )
    results = index.search("LATENCY DOCTOR", top_k=2)
    assert results[0].chunk_id == "latency"
    path = tmp_path / "index.json"
    index.save(path)
    assert BM25Index.load(path).search("memory", top_k=1)[0].chunk_id == "memory"


def test_evaluation_computes_recall_at_k(tmp_path: Path) -> None:
    index = BM25Index.build(
        [
            _chunk("latency", "Latency", "Use LATENCY DOCTOR for spikes.", "Doctor"),
            _chunk("memory", "Memory", "Use MEMORY USAGE for a key.", "Usage"),
        ]
    )
    questions = tmp_path / "questions.jsonl"
    questions.write_text(
        json.dumps(
            {
                "id": "q1",
                "category": "latency",
                "question": "LATENCY DOCTOR",
                "expected_sources": [
                    {"source_path": "content/latency.md", "section_path": ["Doctor"]}
                ],
                "required_answer_points": ["doctor"],
                "should_refuse": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = evaluate(index, questions, top_k=1)
    assert report["recall_at_1"] == 1.0
    assert report["mrr"] == 1.0
    assert report["hit_count"] == 1
