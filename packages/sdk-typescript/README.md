# TypeScript SDK (`packages/sdk-typescript`)

Official TypeScript client library for integrating Node.js / web applications with Setu Gateway.

## Install

```bash
npm install @setu/sdk
```

## Usage

```ts
import { SetuClient } from "@setu/sdk";

const client = new SetuClient({ apiKey: "sk_setu_...", baseUrl: "https://gateway.example.com" });

const response = await client.chat.completions.create({
  model: "gpt-4o",
  messages: [{ role: "user", content: "Summarize what an AI gateway does." }],
});
console.log(response.choices[0].message.content);
```

`apiKey` and `baseUrl` also fall back to the `SETU_API_KEY` / `SETU_BASE_URL`
environment variables (Node only), and `baseUrl` defaults to `http://localhost:8000`
if neither is set.

### Streaming

```ts
const stream = client.chat.completions.create({
  model: "gpt-4o",
  messages: [{ role: "user", content: "Count to five." }],
  stream: true,
});

for await (const chunk of stream) {
  const delta = chunk.choices[0]?.delta;
  if (delta?.content) process.stdout.write(delta.content);
}
```

### Embeddings and models

```ts
await client.embeddings.create({ model: "text-embedding-3-small", input: "hello world" });
await client.models.list();
```

### Errors

`SetuAPIError` is thrown for non-2xx responses (`.statusCode` and `.body` carry the
gateway's error detail); `SetuConnectionError` is thrown when the gateway can't be
reached at all.

```ts
import { SetuAPIError } from "@setu/sdk";

try {
  await client.chat.completions.create({ model: "gpt-4o", messages: [] });
} catch (e) {
  if (e instanceof SetuAPIError) {
    console.error(e.statusCode, e.body);
  }
}
```

## Development

```bash
pnpm --filter @setu/sdk test    # run the test suite
pnpm --filter @setu/sdk build   # type-check and emit dist/
```
