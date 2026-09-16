from app.retrieval.comparison import _markdown


def test_comparison_markdown_contains_metrics_and_latency_note() -> None:
    report = {
        "questions": "questions.jsonl",
        "top_k": 5,
        "retrievers": [
            {
                "retriever": "bm25",
                "recall_at_1": 0.5,
                "recall_at_3": 0.75,
                "recall_at_5": 1.0,
                "mrr": 0.7,
                "hit_count": 4,
                "evaluated": 4,
                "latency_ms": {"average": 1.2, "p50": 1.0, "p95": 2.0},
            }
        ],
    }

    markdown = _markdown(report)

    assert "Recall@1" in markdown
    assert "0.7000" in markdown
    assert "4/4" in markdown
    assert "不包含模型首次加载" in markdown
