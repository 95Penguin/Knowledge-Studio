import argparse
import json
from pathlib import Path

from app.ingestion.pipeline import build_corpus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean and chunk the Redis documentation corpus")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=450)
    parser.add_argument("--overlap-tokens", type=int, default=60)
    parser.add_argument("--supplemental-dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = build_corpus(
        args.raw_dir,
        args.output_dir,
        max_tokens=args.max_tokens,
        overlap_tokens=args.overlap_tokens,
        supplemental_dir=args.supplemental_dir,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
