#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT/ai-service"
uv run --extra embeddings support-pilot-retrieval rerank-evaluate \
  --bm25-index "$PROJECT_ROOT/data/indexes/bm25/index.json" \
  --dense-index "$PROJECT_ROOT/data/indexes/dense/multilingual-e5-base.json" \
  --questions "$PROJECT_ROOT/data/eval/questions.v1.jsonl" \
  --output "$PROJECT_ROOT/data/eval/results/rrf-bge-reranker-base-k10-v1.json" \
  --top-k 5 \
  --candidate-k 20 \
  --rrf-k 60 \
  --rerank-k 10
