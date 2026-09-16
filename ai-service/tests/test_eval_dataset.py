import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_v1_eval_questions_are_unique_and_grounded() -> None:
    chunks = [
        json.loads(line)
        for line in (PROJECT_ROOT / "data/processed/chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    questions = [
        json.loads(line)
        for line in (PROJECT_ROOT / "data/eval/questions.v1.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(questions) == 50
    assert len({question["id"] for question in questions}) == len(questions)

    for question in questions:
        assert question["question"]
        assert isinstance(question["required_answer_points"], list)
        if question["should_refuse"]:
            assert question["expected_sources"] == []
            continue
        assert question["expected_sources"]
        assert question["required_answer_points"]
        for source in question["expected_sources"]:
            assert any(
                chunk["source_path"] == source["source_path"]
                and chunk["section_path"] == source["section_path"]
                for chunk in chunks
            ), f"Missing expected source for {question['id']}: {source}"
