/**
 * Generating text embeddings via the TypeScript SDK.
 *
 * Run: pnpm embeddings
 */
import { SetuClient } from "@setu/sdk";

async function main() {
  const client = new SetuClient();

  const response = await client.embeddings.create({
    model: "text-embedding-3-small",
    input: ["Setu Gateway routes LLM requests.", "It also caches responses."],
  });

  for (const item of response.data as any[]) {
    console.log(`embedding[${item.index}]: dim=${item.embedding.length}, first values=${item.embedding.slice(0, 4)}`);
  }
}

main();
