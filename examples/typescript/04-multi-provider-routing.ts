/**
 * Calling multiple providers through one client - the core value of a gateway.
 *
 * Run: pnpm multi-provider-routing
 *
 * Same client, same code shape, different `model` string per provider - the
 * gateway resolves each to the right upstream provider and API format. Add real
 * provider API keys to the gateway's .env for genuinely different model
 * "personalities" here; with none configured, every provider returns its own
 * labeled mock response, which is still enough to see each one being reached.
 *
 * Note: the response's `model` field is the actual upstream model ID that
 * answered - it can differ from what you requested for two different reasons:
 * normal unified-ID-to-upstream-ID translation (e.g. "llama3" -> "llama3.2",
 * same provider), or the gateway's routing policy failing over to a genuinely
 * different *provider* if it currently has a higher trust score (see
 * /features/routing). This script prints it either way so it's never a silent
 * surprise; to force an exact provider instead of policy-based routing, use
 * POST /routing/replay - see 06-provider-comparison.ts.
 */
import { SetuClient, SetuAPIError, SetuConnectionError } from "@setu/sdk";

// One unified model ID per provider - see /providers/openai etc. for the full catalog.
const MODELS = ["gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro", "groq-llama-3.3", "llama3"];

async function main() {
  const client = new SetuClient();
  const prompt = "Say which model you are, in five words or fewer.";

  for (const model of MODELS) {
    try {
      const response = await client.chat.completions.create({ model, messages: [{ role: "user", content: prompt }] });
      const content = (response.choices as any[])[0].message.content;
      const servedBy = (response as any).model ?? "?";
      console.log(`${model.padEnd(20)} -> ${content}  [served by: ${servedBy}]`);
    } catch (e) {
      if (e instanceof SetuAPIError) {
        console.log(`${model.padEnd(20)} -> API error ${e.statusCode}: ${JSON.stringify(e.body)}`);
      } else if (e instanceof SetuConnectionError) {
        console.log(`${model.padEnd(20)} -> could not reach gateway: ${e.message}`);
      } else {
        throw e;
      }
    }
  }
}

main();
