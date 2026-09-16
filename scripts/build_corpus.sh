#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT/ai-service"
uv run support-pilot-build-corpus \
  --raw-dir "$PROJECT_ROOT/data/raw/redis-docs" \
  --output-dir "$PROJECT_ROOT/data/processed" \
  --supplemental-dir "$PROJECT_ROOT/knowledge/engineering-practices" \
  --max-tokens 450 \
  --overlap-tokens 60
