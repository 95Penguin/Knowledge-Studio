#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <query> [top_k]" >&2
  exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUERY="$1"
TOP_K="${2:-5}"

cd "$PROJECT_ROOT/ai-service"
uv run support-pilot-retrieval search \
  --index "$PROJECT_ROOT/data/indexes/bm25/index.json" \
  --query "$QUERY" \
  --top-k "$TOP_K"
