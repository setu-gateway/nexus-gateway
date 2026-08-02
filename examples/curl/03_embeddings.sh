#!/usr/bin/env bash
# Text embeddings.
# Usage: BASE_URL=http://localhost:8000 ./03_embeddings.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

curl -s "${BASE_URL}/v1/embeddings" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "text-embedding-3-small",
    "input": ["Setu Gateway routes LLM requests.", "It also caches responses."]
  }' | python3 -m json.tool
