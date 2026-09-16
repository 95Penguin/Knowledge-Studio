import json
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

from app.generation.models import AnswerResponse


class ExpectedSource(BaseModel):
    source_path: str
    section_path: list[str]


class AnswerEvaluationCase(BaseModel):
    id: str
    category: str
    question: str
    expected_sources: list[ExpectedSource] = Field(default_factory=list)
    required_answer_points: list[str] = Field(default_factory=list)
    should_refuse: bool


def load_cases(path: Path) -> list[AnswerEvaluationCase]:
    cases = [
        AnswerEvaluationCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case ids must be unique")
    if not cases:
        raise ValueError("evaluation dataset must not be empty")
    return cases


def evaluate_answers(service: Any, cases_path: Path) -> dict[str, Any]:
    cases = load_cases(cases_path)
    details: list[dict[str, Any]] = []
    latencies: list[float] = []
    category_correctness: dict[str, list[float]] = defaultdict(list)

    for case in cases:
        started = time.perf_counter()
        try:
            response = service.answer(case.question)
            error = None
        # A batch may contain paid remote calls; record one provider/runtime failure
        # instead of discarding all completed results.
        except Exception as exc:  # noqa: BLE001
            response = None
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        detail = _evaluate_case(case, response, error)
        detail["latency_ms"] = round(latency_ms, 3)
        details.append(detail)
        category_correctness[case.category].append(float(detail["status_correct"]))

    positives = [item for item in details if not item["should_refuse"]]
    negatives = [item for item in details if item["should_refuse"]]
    successful = [item for item in details if item["error"] is None]
    citation_cases = [item for item in positives if item["actual_status"] == "answered"]
    total_expected = sum(len(item["expected_sources"]) for item in citation_cases)
    total_hit = sum(len(item["hit_sources"]) for item in citation_cases)

    return {
        "schema_version": 1,
        "dataset": str(cases_path),
        "questions_total": len(details),
        "positive_questions": len(positives),
        "negative_questions": len(negatives),
        "request_success_rate": _ratio(len(successful), len(details)),
        "answerability_accuracy": _average_bool(details, "status_correct"),
        "positive_answer_rate": _ratio(
            sum(item["actual_status"] == "answered" for item in positives), len(positives)
        ),
        "negative_refusal_accuracy": _ratio(
            sum(item["actual_status"] == "refused" for item in negatives), len(negatives)
        ),
        "citation_source_recall": _ratio(total_hit, total_expected),
        "citation_cases_evaluated": len(citation_cases),
        "manual_answer_point_review": {
            "status": "required",
            "reason": "语义要点不能用字符串包含关系可靠判断；请依据 details 中的清单人工复核。",
        },
        "latency_ms": _latency_summary(latencies),
        "accuracy_by_category": {
            category: round(mean(values), 6)
            for category, values in sorted(category_correctness.items())
        },
        "details": details,
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _evaluate_case(
    case: AnswerEvaluationCase,
    response: AnswerResponse | None,
    error: str | None,
) -> dict[str, Any]:
    actual_status = response.status if response else "error"
    expected_status = "refused" if case.should_refuse else "answered"
    expected_sources = [source.model_dump() for source in case.expected_sources]
    citations = [citation.model_dump() for citation in response.citations] if response else []
    hit_sources = [
        expected
        for expected in expected_sources
        if any(
            citation["source_path"] == expected["source_path"]
            and citation["section_path"] == expected["section_path"]
            for citation in citations
        )
    ]
    return {
        "id": case.id,
        "category": case.category,
        "question": case.question,
        "should_refuse": case.should_refuse,
        "expected_status": expected_status,
        "actual_status": actual_status,
        "status_correct": actual_status == expected_status,
        "answer": response.answer if response else None,
        "refusal_reason": response.refusal_reason if response else None,
        "top_evidence_score": response.top_evidence_score if response else None,
        "expected_sources": expected_sources,
        "hit_sources": hit_sources,
        "citation_source_recall": _ratio(len(hit_sources), len(expected_sources)),
        "citations": citations,
        "required_answer_points": case.required_answer_points,
        "answer_point_review": "pending" if not case.should_refuse else "not_applicable",
        "error": error,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _average_bool(items: list[dict[str, Any]], key: str) -> float | None:
    return _ratio(sum(bool(item[key]) for item in items), len(items))


def _latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"average": 0.0, "p50": 0.0, "p95": 0.0}

    def percentile(fraction: float) -> float:
        index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
        return round(ordered[index], 3)

    return {
        "average": round(mean(ordered), 3),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
    }
