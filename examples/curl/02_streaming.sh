#!/usr/bin/env bash
# Streaming chat completion (Server-Sent Events). -N disables curl's output
# buffering so chunks print as they arrive rather than all at once at the end.
# Usage: BASE_URL=http://localhost:8000 ./02_streaming.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

curl -s -N "${BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Count from 1 to 5, one number per line."}],
    "stream": true
  }'
