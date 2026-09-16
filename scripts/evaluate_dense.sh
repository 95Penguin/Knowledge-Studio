#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT/ai-service"
uv run --extra embeddings support-pilot-retrieval dense-evaluate \
  --index "$PROJECT_ROOT/data/indexes/dense/multilingual-e5-base.json" \
  --questions "$PROJECT_ROOT/data/eval/questions.v1.jsonl" \
  --output "$PROJECT_ROOT/data/eval/results/dense-multilingual-e5-base-v1.json" \
  --top-k 5
