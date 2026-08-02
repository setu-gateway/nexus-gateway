#!/usr/bin/env bash
# Compare several providers' responses to the same prompt in one call. A
# diagnostic tool (apps/gateway/api/routing_tools.py) - not recorded to
# analytics, nothing is cached or stored. See /features/routing.
#
# Passing an explicit "model" alongside "providers" sends that exact model
# string to every provider listed (rather than each provider's own name as a
# placeholder, which is what happens if you omit "model" here - harmless with
# no provider API keys configured since nothing validates it, but a real
# provider would reject a nonsense model name).
#
# Anthropic is disabled by default (see /providers/anthropic) - expect its
# result to report "success": false unless you've enabled it.
#
# Usage: BASE_URL=http://localhost:8000 ./06_provider_comparison.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

curl -s "${BASE_URL}/routing/replay" \
  -H "Content-Type: application/json" \
  -d '{
    "providers": ["openai", "anthropic", "gemini", "groq"],
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "What makes a good API gateway? One sentence."}]
  }' | python3 -m json.tool
