import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


def evaluate(index: Any, questions_path: Path, top_k: int = 5) -> dict[str, Any]:
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    details: list[dict[str, Any]] = []
    category_recalls: dict[str, list[float]] = defaultdict(list)
    latencies_ms: list[float] = []
    cutoffs = sorted({cutoff for cutoff in (1, 3, 5, top_k) if cutoff <= top_k})

    for question in questions:
        started = time.perf_counter()
        results = index.search(question["question"], top_k=top_k)
        latency_ms = (time.perf_counter() - started) * 1000
        latencies_ms.append(latency_ms)

        if question["should_refuse"]:
            details.append(
                {
                    "id": question["id"],
                    "category": question["category"],
                    "question": question["question"],
                    "excluded_from_recall": True,
                    "reason": "retrieval_only_baseline_does_not_decide_answer_abstention",
                    "latency_ms": round(latency_ms, 3),
                    "results": [result.to_dict() for result in results],
                }
            )
            continue

        expected = question["expected_sources"]
        recalls: dict[int, float] = {}
        hits_by_cutoff: dict[int, list[dict[str, Any]]] = {}
        for cutoff in cutoffs:
            hit_sources = [
                source
                for source in expected
                if any(_matches(result, source) for result in results[:cutoff])
            ]
            hits_by_cutoff[cutoff] = hit_sources
            recalls[cutoff] = len(hit_sources) / len(expected)
        recall = recalls[top_k]
        first_relevant_rank = next(
            (
                rank
                for rank, result in enumerate(results, start=1)
                if any(_matches(result, source) for source in expected)
            ),
            None,
        )
        category_recalls[question["category"]].append(recall)
        details.append(
            {
                "id": question["id"],
                "category": question["category"],
                "question": question["question"],
                **{f"recall_at_{cutoff}": recalls[cutoff] for cutoff in cutoffs},
                "reciprocal_rank": 1 / first_relevant_rank if first_relevant_rank else 0.0,
                "first_relevant_rank": first_relevant_rank,
                "expected_sources": expected,
                "hit_sources": hits_by_cutoff[top_k],
                "latency_ms": round(latency_ms, 3),
                "results": [result.to_dict() for result in results],
            }
        )

    answerable = [detail for detail in details if not detail.get("excluded_from_recall")]
    recall_key = f"recall_at_{top_k}"
    recall_metrics = {
        f"recall_at_{cutoff}": round(
            sum(item[f"recall_at_{cutoff}"] for item in answerable) / len(answerable), 6
        )
        for cutoff in cutoffs
    }
    return {
        "retriever": index.retriever_name,
        "parameters": {**index.retriever_parameters, "top_k": top_k},
        "questions_total": len(questions),
        "questions_evaluated_for_recall": len(answerable),
        "questions_excluded_from_recall": len(questions) - len(answerable),
        **recall_metrics,
        "mrr": round(sum(item["reciprocal_rank"] for item in answerable) / len(answerable), 6),
        "hit_count": sum(item[recall_key] > 0 for item in answerable),
        "latency_ms": _latency_summary(latencies_ms),
        "recall_by_category": {
            category: round(sum(values) / len(values), 6)
            for category, values in sorted(category_recalls.items())
        },
        "details": details,
    }


def _matches(result: Any, source: dict[str, Any]) -> bool:
    return (
        result.source_path == source["source_path"]
        and result.section_path == source["section_path"]
    )


def _latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"average": 0.0, "p50": 0.0, "p95": 0.0}

    def percentile(fraction: float) -> float:
        index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
        return round(ordered[index], 3)

    return {
        "average": round(sum(ordered) / len(ordered), 3),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
    }
