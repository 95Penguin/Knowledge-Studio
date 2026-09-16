#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT/ai-service"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/support-pilot-uv-cache}" \
HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" \
uv run --extra embeddings support-pilot-retrieval compare \
  --bm25-index "$PROJECT_ROOT/data/indexes/bm25/index.json" \
  --dense-index "$PROJECT_ROOT/data/indexes/dense/multilingual-e5-base.json" \
  --questions "$PROJECT_ROOT/data/eval/questions.v1.jsonl" \
  --output-dir "$PROJECT_ROOT/data/eval/results/comparison-v1" \
  --top-k 5 \
  --candidate-k 20 \
  --rrf-k 60 \
  --rerank-k 10
