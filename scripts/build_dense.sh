#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT/ai-service"
uv run --extra embeddings support-pilot-retrieval dense-build \
  --chunks "$PROJECT_ROOT/data/processed/chunks.jsonl" \
  --output "$PROJECT_ROOT/data/indexes/dense/multilingual-e5-base.json"
