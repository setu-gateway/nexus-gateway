/**
 * Recording a request with Time Machine, then replaying it later.
 *
 * Run: pnpm time-machine-replay
 *
 * Neither /time-machine/* endpoint is wrapped by the SDK yet, so this uses
 * fetch directly against the REST API - see /features/time-machine.
 *
 * The gateway's internal request_id (what /time-machine/* is keyed on) is NOT
 * the same as the chat completion response body's own "id" field - by default
 * it isn't returned to the caller at all. Also sending X-Setu-Debug: true
 * surfaces it in the X-Setu-Routing-Debug response header, which is what this
 * reads instead.
 *
 * A cache hit never calls the code path that records to Time Machine at all,
 * regardless of X-Setu-Time-Machine - a cached response is a hit precisely
 * because nothing new happened for this request to record (see
 * /features/caching). The prompt below includes a random token so repeat runs
 * of this script always produce a fresh cache miss instead of silently
 * recording nothing on the second and later runs.
 */
export {}; // make this file a module, not a global script, so its top-level `const`s don't collide with other example files

const BASE_URL = process.env.SETU_BASE_URL ?? "http://localhost:8000";

async function main() {
  // Record: X-Setu-Time-Machine opts this one request into being stored.
  // X-Setu-Debug surfaces the gateway's own request_id in a response header.
  const prompt = `Explain routing in one sentence. [${Math.random().toString(16).slice(2, 10)}]`;
  const chatResp = await fetch(`${BASE_URL}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Setu-Time-Machine": "true", "X-Setu-Debug": "true" },
    body: JSON.stringify({ model: "gpt-4o", messages: [{ role: "user", content: prompt }] }),
  });
  const debugHeader = chatResp.headers.get("X-Setu-Routing-Debug");
  const requestId = JSON.parse(debugHeader ?? "{}").request_id;
  console.log(`Recorded request_id=${requestId}`);

  // Inspect what was stored.
  const record = (await (await fetch(`${BASE_URL}/time-machine/${requestId}`)).json()) as any;
  console.log(`Original response: ${JSON.stringify(record.response_body.choices[0].message.content)}`);

  // Replay against the same provider (checks for drift over time).
  const replay = (await (await fetch(`${BASE_URL}/time-machine/${requestId}/replay`, { method: "POST" })).json()) as any;
  console.log(`Replayed response: ${JSON.stringify(replay.replayed.response_content)}`);
  console.log(`Diff ratio vs. original: ${replay.diff_ratio.toFixed(2)}`);

  // Replay against a different provider for comparison.
  const replayGemini = (await (
    await fetch(`${BASE_URL}/time-machine/${requestId}/replay?provider=gemini`, { method: "POST" })
  ).json()) as any;
  console.log(`Gemini response:   ${JSON.stringify(replayGemini.replayed.response_content)}`);
}

main();
