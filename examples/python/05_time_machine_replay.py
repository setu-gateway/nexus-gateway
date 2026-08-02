"""Recording a request with Time Machine, then replaying it later.

Run: python 05_time_machine_replay.py

Neither /time-machine/* endpoint is wrapped by the SDK yet, so this uses
httpx directly against the REST API - see /features/time-machine.

The gateway's internal request_id (what /time-machine/* is keyed on) is NOT
the same as the chat completion response body's own "id" field - by default
it isn't returned to the caller at all. Also sending X-Setu-Debug: true
surfaces it in the X-Setu-Routing-Debug response header, which is what this
reads instead.

A cache hit never calls the code path that records to Time Machine at all,
regardless of X-Setu-Time-Machine - a cached response is a hit precisely
because nothing new happened for this request to record (see
/features/caching). The prompt below includes a random token so repeat runs
of this script always produce a fresh cache miss instead of silently
recording nothing on the second and later runs.
"""

import json
import os
import uuid

import httpx

BASE_URL = os.environ.get("SETU_BASE_URL", "http://localhost:8000")


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # Record: X-Setu-Time-Machine opts this one request into being stored.
        # X-Setu-Debug surfaces the gateway's own request_id in a response header.
        prompt = f"Explain routing in one sentence. [{uuid.uuid4().hex[:8]}]"
        resp = client.post(
            "/v1/chat/completions",
            headers={"X-Setu-Time-Machine": "true", "X-Setu-Debug": "true"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}]},
        )
        resp.raise_for_status()
        request_id = json.loads(resp.headers["X-Setu-Routing-Debug"])["request_id"]
        print(f"Recorded request_id={request_id}")

        # Inspect what was stored.
        record = client.get(f"/time-machine/{request_id}").json()
        print(f"Original response: {record['response_body']['choices'][0]['message']['content']!r}")

        # Replay against the same provider (checks for drift over time).
        replay = client.post(f"/time-machine/{request_id}/replay").json()
        print(f"Replayed response: {replay['replayed']['response_content']!r}")
        print(f"Diff ratio vs. original: {replay['diff_ratio']:.2f}")

        # Replay against a different provider for comparison.
        replay_gemini = client.post(f"/time-machine/{request_id}/replay", params={"provider": "gemini"}).json()
        print(f"Gemini response:   {replay_gemini['replayed']['response_content']!r}")


if __name__ == "__main__":
    main()
