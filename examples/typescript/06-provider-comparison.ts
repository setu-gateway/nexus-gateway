/**
 * Comparing multiple providers' responses to the same prompt, side by side.
 *
 * Run: pnpm provider-comparison
 *
 * /routing/replay isn't wrapped by the SDK, so this uses fetch directly. Unlike
 * Time Machine, replay is a one-shot diagnostic call - nothing is stored, and it
 * isn't recorded to analytics.
 *
 * Passing an explicit `model` alongside `providers` sends that exact model
 * string to every provider listed (rather than each provider's own name as a
 * placeholder, which is what happens if you omit `model` here - harmless with
 * no provider API keys configured since nothing validates it, but a real
 * provider would reject a nonsense model name).
 *
 * Anthropic is disabled by default (see /providers/anthropic) - expect its
 * result to report `success: false` unless you've enabled it.
 */
export {}; // make this file a module, not a global script, so its top-level `const`s don't collide with other example files

const BASE_URL = process.env.SETU_BASE_URL ?? "http://localhost:8000";

async function main() {
  const resp = await fetch(`${BASE_URL}/routing/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      providers: ["openai", "anthropic", "gemini", "groq"],
      model: "gpt-4o",
      messages: [{ role: "user", content: "What makes a good API gateway? One sentence." }],
    }),
  });
  const body = (await resp.json()) as any;

  for (const result of body.results) {
    if (result.success) {
      console.log(`${result.provider.padEnd(12)} (${Math.round(result.latency_ms)}ms): ${result.response.choices[0].message.content}`);
    } else {
      console.log(`${result.provider.padEnd(12)} FAILED: ${result.error}`);
    }
  }
}

main();
