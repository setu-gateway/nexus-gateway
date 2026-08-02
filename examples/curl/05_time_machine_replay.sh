#!/usr/bin/env bash
# Record a request with Time Machine, then replay it - against the same
# provider (drift check) and a different one (comparison). See /features/time-machine.
#
# The gateway's internal request_id (what /time-machine/* is keyed on) is NOT
# the same as the chat completion response body's own "id" field - by default
# it isn't returned to the caller at all. X-Setu-Debug surfaces it in the
# X-Setu-Routing-Debug response HEADER, which is why this captures headers
# separately from the body below.
#
# A cache hit never calls the code path that records to Time Machine at all,
# regardless of X-Setu-Time-Machine - a cached response is a hit precisely
# because nothing new happened for this request to record (see
# /features/caching). The prompt below includes a random token so repeat runs
# of this script always produce a fresh cache miss instead of silently
# recording nothing on the second and later runs.
#
# Usage: BASE_URL=http://localhost:8000 ./05_time_machine_replay.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
HEADERS_FILE=$(mktemp)
trap 'rm -f "$HEADERS_FILE"' EXIT
TOKEN=$(python3 -c "import uuid; print(uuid.uuid4().hex[:8])")

curl -s -D "$HEADERS_FILE" -o /dev/null "${BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Setu-Time-Machine: true" \
  -H "X-Setu-Debug: true" \
  -d "{\"model\": \"gpt-4o\", \"messages\": [{\"role\": \"user\", \"content\": \"Explain routing in one sentence. [${TOKEN}]\"}]}"

REQUEST_ID=$(grep -i '^x-setu-routing-debug:' "$HEADERS_FILE" | sed 's/^[^:]*: *//' | python3 -c "import json,sys;print(json.load(sys.stdin)['request_id'])")

echo "Recorded request_id=${REQUEST_ID}"

echo "--- stored record ---"
curl -s "${BASE_URL}/time-machine/${REQUEST_ID}" | python3 -m json.tool

echo "--- replay (same provider) ---"
curl -s -X POST "${BASE_URL}/time-machine/${REQUEST_ID}/replay" | python3 -m json.tool

echo "--- replay (against gemini) ---"
curl -s -X POST "${BASE_URL}/time-machine/${REQUEST_ID}/replay?provider=gemini" | python3 -m json.tool
