#!/usr/bin/env bash
# Basic (non-streaming) chat completion.
# Usage: BASE_URL=http://localhost:8000 ./01_basic_chat.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

curl -s "${BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "system", "content": "You are a concise assistant."},
      {"role": "user", "content": "What does an AI gateway do? One sentence."}
    ]
  }' | python3 -m json.tool
