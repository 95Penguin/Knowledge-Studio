import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.generation.evaluation import evaluate_answers, write_report
from app.generation.runtime import get_answer_service


def main() -> None:
    root = get_settings().project_root
    parser = argparse.ArgumentParser(description="Evaluate grounded answers in batch")
    parser.add_argument(
        "--questions",
        type=Path,
        default=root / "data/eval/answer-questions.v1.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data/eval/results/answers-deepseek-chat-v1.json",
    )
    args = parser.parse_args()

    report = evaluate_answers(get_answer_service(), args.questions)
    write_report(report, args.output)
    summary = {key: value for key, value in report.items() if key != "details"}
    summary["report"] = str(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
