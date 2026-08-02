#!/usr/bin/env bash
# Calling multiple providers with the same request shape - one unified model ID
# per provider (see /providers/openai etc. for the full catalog). Add real
# provider API keys to the gateway's .env for genuinely different responses;
# with none configured, every provider returns its own labeled mock response.
#
# Note: the response's `model` field is the actual upstream model ID that
# answered - it can differ from what you requested for two different reasons:
# normal unified-ID-to-upstream-ID translation (e.g. "llama3" -> "llama3.2",
# same provider), or the gateway's routing policy failing over to a genuinely
# different *provider* if it currently has a higher trust score (see
# /features/routing). This prints it either way so it's never a silent
# surprise; to force an exact provider instead of policy-based routing, use
# POST /routing/replay - see 06_provider_comparison.sh.
#
# Usage: BASE_URL=http://localhost:8000 ./04_multi_provider_routing.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
PROMPT="Say which model you are, in five words or fewer."

for model in gpt-4o claude-3-5-sonnet gemini-1.5-pro groq-llama-3.3 llama3; do
  echo "== ${model} =="
  curl -s "${BASE_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"${model}\", \"messages\": [{\"role\": \"user\", \"content\": \"${PROMPT}\"}]}" \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
content = d.get('choices', [{}])[0].get('message', {}).get('content', d)
served_by = d.get('model', '?')
print(f'{content}  [served by: {served_by}]')
"
  echo
done
