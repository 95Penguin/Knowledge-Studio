import json
from pathlib import Path

import pytest

from app.generation.evaluation import evaluate_answers, load_cases, write_report
from app.generation.models import AnswerResponse, Citation


class FixedAnswerService:
    def answer(self, question: str) -> AnswerResponse:
        if "PostgreSQL" in question:
            return AnswerResponse(
                status="refused",
                answer="当前知识库证据不足，无法可靠回答这个问题。",
                citations=[],
                refusal_reason="out of scope",
            )
        return AnswerResponse(
            status="answered",
            answer="故障时可能丢失约一秒数据。",
            top_evidence_score=0.98,
            citations=[
                Citation(
                    evidence_id="E1",
                    chunk_id="chunk-1",
                    title="Redis persistence",
                    section_path=["Append-only file", "How durable is the append only file?"],
                    source_path="content/persistence.md",
                    source_url="https://redis.io/docs/latest/persistence/",
                )
            ],
        )


def _dataset(path: Path) -> None:
    cases = [
        {
            "id": "positive",
            "category": "persistence",
            "question": "appendfsync everysec 有什么风险？",
            "expected_sources": [
                {
                    "source_path": "content/persistence.md",
                    "section_path": [
                        "Append-only file",
                        "How durable is the append only file?",
                    ],
                }
            ],
            "required_answer_points": ["可能丢失约一秒数据"],
            "should_refuse": False,
        },
        {
            "id": "negative",
            "category": "out_of_scope",
            "question": "PostgreSQL VACUUM 怎么配置？",
            "expected_sources": [],
            "required_answer_points": [],
            "should_refuse": True,
        },
    ]
    path.write_text("\n".join(json.dumps(item) for item in cases) + "\n", encoding="utf-8")


def test_answer_evaluation_reports_status_citation_and_latency(tmp_path: Path) -> None:
    questions = tmp_path / "questions.jsonl"
    output = tmp_path / "report.json"
    _dataset(questions)

    report = evaluate_answers(FixedAnswerService(), questions)
    write_report(report, output)

    assert report["answerability_accuracy"] == 1.0
    assert report["positive_answer_rate"] == 1.0
    assert report["negative_refusal_accuracy"] == 1.0
    assert report["citation_source_recall"] == 1.0
    assert report["details"][0]["answer_point_review"] == "pending"
    assert json.loads(output.read_text())["questions_total"] == 2


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    questions = tmp_path / "questions.jsonl"
    item = {
        "id": "same",
        "category": "x",
        "question": "q",
        "should_refuse": True,
    }
    questions.write_text(f"{json.dumps(item)}\n{json.dumps(item)}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        load_cases(questions)
