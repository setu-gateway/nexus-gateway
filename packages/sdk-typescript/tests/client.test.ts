import { describe, expect, it, vi } from "vitest";
import { SetuAPIError, SetuClient, SetuConnectionError } from "../src/index";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function sseResponse(): Response {
  const sse =
    'data: {"choices": [{"delta": {"content": "Hel"}}]}\n\n' +
    'data: {"choices": [{"delta": {"content": "lo"}}]}\n\n' +
    "data: [DONE]\n\n";
  return new Response(sse, { status: 200, headers: { "content-type": "text/event-stream" } });
}

function fakeFetch(
  handler: (url: string, init: RequestInit) => Response | Promise<Response>
): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    return handler(input.toString(), init ?? {});
  }) as unknown as typeof fetch;
}

describe("SetuClient.chat.completions.create", () => {
  it("returns the parsed response for a non-streaming request", async () => {
    const fetchImpl = fakeFetch(() =>
      jsonResponse({ choices: [{ message: { role: "assistant", content: "hi there" } }] })
    );
    const client = new SetuClient({ baseUrl: "http://fake", fetchImpl });

    const response = await client.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "hi" }],
    });
    expect((response.choices as any[])[0].message.content).toBe("hi there");
  });

  it("sends the Authorization header when an API key is set", async () => {
    let seenAuth: string | null = null;
    const fetchImpl = fakeFetch((_url, init) => {
      seenAuth = (init.headers as Record<string, string>)["Authorization"];
      return jsonResponse({ choices: [] });
    });
    const client = new SetuClient({ baseUrl: "http://fake", apiKey: "sk_setu_abc123", fetchImpl });

    await client.chat.completions.create({ model: "gpt-4o", messages: [{ role: "user", content: "hi" }] });
    expect(seenAuth).toBe("Bearer sk_setu_abc123");
  });

  it("sends snake_case fields for camelCase params", async () => {
    let sentBody: any = null;
    const fetchImpl = fakeFetch((_url, init) => {
      sentBody = JSON.parse(init.body as string);
      return jsonResponse({ choices: [] });
    });
    const client = new SetuClient({ baseUrl: "http://fake", fetchImpl });

    await client.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "hi" }],
      topP: 0.9,
      maxTokens: 100,
    });
    expect(sentBody.top_p).toBe(0.9);
    expect(sentBody.max_tokens).toBe(100);
  });

  it("streams parsed SSE chunks", async () => {
    const fetchImpl = fakeFetch(() => sseResponse());
    const client = new SetuClient({ baseUrl: "http://fake", fetchImpl });

    const stream = client.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "hi" }],
      stream: true,
    });

    let content = "";
    for await (const chunk of stream) {
      const delta = (chunk.choices as any[])[0]?.delta;
      if (delta?.content) content += delta.content;
    }
    expect(content).toBe("Hello");
  });

  it("throws SetuAPIError with status and body on a non-2xx response", async () => {
    const fetchImpl = fakeFetch(() => jsonResponse({ detail: "messages is required" }, 400));
    const client = new SetuClient({ baseUrl: "http://fake", fetchImpl });

    await expect(client.chat.completions.create({ model: "gpt-4o", messages: [] })).rejects.toMatchObject({
      statusCode: 400,
    });
    try {
      await client.chat.completions.create({ model: "gpt-4o", messages: [] });
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(SetuAPIError);
      expect((e as SetuAPIError).message).toContain("messages is required");
    }
  });

  it("throws SetuConnectionError when the fetch itself fails", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const client = new SetuClient({ baseUrl: "http://fake", fetchImpl });

    await expect(
      client.chat.completions.create({ model: "gpt-4o", messages: [{ role: "user", content: "hi" }] })
    ).rejects.toBeInstanceOf(SetuConnectionError);
  });
});

describe("SetuClient.embeddings.create", () => {
  it("posts to /v1/embeddings", async () => {
    let seenUrl = "";
    const fetchImpl = fakeFetch((url) => {
      seenUrl = url;
      return jsonResponse({ data: [{ embedding: [0.1, 0.2] }] });
    });
    const client = new SetuClient({ baseUrl: "http://fake", fetchImpl });

    const response = await client.embeddings.create({ model: "text-embedding-3-small", input: "hello" });
    expect(seenUrl).toBe("http://fake/v1/embeddings");
    expect((response.data as any[])[0].embedding).toEqual([0.1, 0.2]);
  });
});

describe("SetuClient.models.list", () => {
  it("gets /v1/models", async () => {
    let seenMethod = "";
    const fetchImpl = fakeFetch((_url, init) => {
      seenMethod = init.method ?? "";
      return jsonResponse({ data: [{ id: "gpt-4o" }] });
    });
    const client = new SetuClient({ baseUrl: "http://fake", fetchImpl });

    const response = await client.models.list();
    expect(seenMethod).toBe("GET");
    expect((response.data as any[])[0].id).toBe("gpt-4o");
  });
});

describe("SetuClient construction", () => {
  it("reads apiKey and baseUrl from environment variables when not passed explicitly", () => {
    process.env.SETU_API_KEY = "sk_setu_from_env";
    process.env.SETU_BASE_URL = "https://env.example.com";
    try {
      const client = new SetuClient();
      expect(client.apiKey).toBe("sk_setu_from_env");
      expect(client.baseUrl).toBe("https://env.example.com");
    } finally {
      delete process.env.SETU_API_KEY;
      delete process.env.SETU_BASE_URL;
    }
  });

  it("defaults to localhost:8000 when nothing is configured", () => {
    const client = new SetuClient({ apiKey: undefined, baseUrl: undefined });
    expect(client.baseUrl).toBe("http://localhost:8000");
  });

  it("strips trailing slashes from baseUrl", () => {
    const client = new SetuClient({ baseUrl: "http://fake///" });
    expect(client.baseUrl).toBe("http://fake");
  });
});
