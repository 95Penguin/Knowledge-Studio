#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT/ai-service"
uv run support-pilot-retrieval evaluate \
  --index "$PROJECT_ROOT/data/indexes/bm25/index.json" \
  --questions "$PROJECT_ROOT/data/eval/questions.v1.jsonl" \
  --output "$PROJECT_ROOT/data/eval/results/bm25-v1.json" \
  --top-k 5
