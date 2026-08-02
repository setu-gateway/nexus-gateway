/**
 * Streaming a chat completion token-by-token via the TypeScript SDK.
 *
 * Run: pnpm streaming
 *
 * Note: OpenAI, Groq, and Ollama stream incrementally end-to-end. Anthropic and
 * Gemini currently deliver the full answer as a single chunk rather than
 * token-by-token (see /support/troubleshooting) - the code below works
 * identically either way, it's just less visually "typed out" for those two.
 */
import { SetuClient } from "@setu/sdk";

async function main() {
  const client = new SetuClient();

  const stream = client.chat.completions.create({
    model: "gpt-4o",
    messages: [{ role: "user", content: "Count from 1 to 5, one number per line." }],
    stream: true,
  });

  for await (const chunk of stream) {
    const delta = (chunk.choices as any[])[0]?.delta;
    if (delta?.content) process.stdout.write(delta.content);
  }
  process.stdout.write("\n");
}

main();
