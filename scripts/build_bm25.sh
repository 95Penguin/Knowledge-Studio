#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT/ai-service"
uv run support-pilot-retrieval build \
  --chunks "$PROJECT_ROOT/data/processed/chunks.jsonl" \
  --output "$PROJECT_ROOT/data/indexes/bm25/index.json" \
  --k1 1.5 \
  --b 0.75
