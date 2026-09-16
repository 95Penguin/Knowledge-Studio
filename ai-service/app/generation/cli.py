import argparse
import json

from app.generation.runtime import get_answer_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a grounded Redis answer")
    parser.add_argument("question")
    args = parser.parse_args()
    response = get_answer_service().answer(args.question)
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
