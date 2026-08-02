/**
 * Basic (non-streaming) chat completion via the TypeScript SDK.
 *
 * Run: pnpm basic-chat
 * Requires a gateway running at SETU_BASE_URL (default http://localhost:8000).
 * No API key needed - see /getting-started/quickstart for why.
 */
import { SetuClient } from "@setu/sdk";

async function main() {
  const client = new SetuClient(); // baseUrl/apiKey default to SETU_BASE_URL/SETU_API_KEY env vars, then localhost:8000

  const response = await client.chat.completions.create({
    model: "gpt-4o",
    messages: [
      { role: "system", content: "You are a concise assistant." },
      { role: "user", content: "What does an AI gateway do? One sentence." },
    ],
  });

  console.log((response.choices as any[])[0].message.content);
  console.log(`\nTokens used: ${(response.usage as any).total_tokens}`);
}

main();
