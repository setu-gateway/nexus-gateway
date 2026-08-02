import { SetuAPIError, SetuConnectionError } from "./errors";

export const DEFAULT_BASE_URL = "http://localhost:8000";
const DEFAULT_TIMEOUT_MS = 60_000;

export interface ChatMessage {
  role: string;
  content: string | Array<Record<string, unknown>>;
  name?: string;
}

export interface ChatCompletionParams {
  model: string;
  messages: ChatMessage[];
  temperature?: number;
  topP?: number;
  maxTokens?: number;
  stop?: string | string[];
  [key: string]: unknown;
}

export interface EmbeddingsParams {
  model: string;
  input: string | string[];
  [key: string]: unknown;
}

export interface SetuClientOptions {
  apiKey?: string;
  baseUrl?: string;
  timeoutMs?: number;
  /** Injectable for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
}

function resolveEnv(name: string): string | undefined {
  // Works under Node (process.env) without requiring @types/node in consumers'
  // projects, and is a no-op (undefined) in browsers, where callers pass options
  // explicitly instead.
  const proc = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  return proc?.env?.[name];
}

async function parseErrorBody(response: Response): Promise<{ message: string; body: unknown }> {
  const text = await response.text();
  try {
    const body = JSON.parse(text);
    const message = typeof body?.detail === "string" ? body.detail : text;
    return { message, body };
  } catch {
    return { message: text, body: text };
  }
}

function* parseSseLine(line: string): Generator<Record<string, unknown>> {
  if (!line.startsWith("data: ")) return;
  const payload = line.slice("data: ".length).trim();
  if (payload === "[DONE]") return;
  try {
    yield JSON.parse(payload);
  } catch {
    // Ignore malformed chunks rather than aborting the whole stream over one bad line.
  }
}

function buildChatPayload(params: ChatCompletionParams, stream: boolean): Record<string, unknown> {
  const { temperature, topP, maxTokens, stop, ...rest } = params;
  return {
    ...rest,
    stream,
    ...(temperature !== undefined ? { temperature } : {}),
    ...(topP !== undefined ? { top_p: topP } : {}),
    ...(maxTokens !== undefined ? { max_tokens: maxTokens } : {}),
    ...(stop !== undefined ? { stop } : {}),
  };
}

/** Internal HTTP transport shared by every resource namespace below. */
class Transport {
  constructor(
    private readonly baseUrl: string,
    private readonly apiKey: string | undefined,
    private readonly timeoutMs: number,
    private readonly fetchImpl: typeof fetch
  ) {}

  private headers(): Record<string, string> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.apiKey) headers["Authorization"] = `Bearer ${this.apiKey}`;
    return headers;
  }

  private async rawFetch(path: string, init: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers: this.headers(), signal: controller.signal });
    } catch (e) {
      throw new SetuConnectionError(`Could not reach Setu Gateway at ${this.baseUrl}: ${(e as Error).message}`);
    } finally {
      clearTimeout(timeout);
    }
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await this.rawFetch(path, { method, body: body !== undefined ? JSON.stringify(body) : undefined });
    if (!response.ok) {
      const { message, body: errorBody } = await parseErrorBody(response);
      throw new SetuAPIError(`Setu Gateway request failed (${response.status}): ${message}`, response.status, errorBody);
    }
    return (await response.json()) as T;
  }

  async *stream(method: string, path: string, body: unknown): AsyncGenerator<Record<string, unknown>> {
    const response = await this.rawFetch(path, { method, body: JSON.stringify(body) });
    if (!response.ok) {
      const { message, body: errorBody } = await parseErrorBody(response);
      throw new SetuAPIError(`Setu Gateway request failed (${response.status}): ${message}`, response.status, errorBody);
    }
    if (!response.body) return;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        yield* parseSseLine(line.trimEnd());
      }
    }
    yield* parseSseLine(buffer.trimEnd());
  }
}

class ChatCompletions {
  constructor(private readonly transport: Transport) {}

  create(params: ChatCompletionParams & { stream: true }): AsyncGenerator<Record<string, unknown>>;
  create(params: ChatCompletionParams & { stream?: false }): Promise<Record<string, unknown>>;
  create(
    params: ChatCompletionParams & { stream?: boolean }
  ): Promise<Record<string, unknown>> | AsyncGenerator<Record<string, unknown>> {
    const payload = buildChatPayload(params, Boolean(params.stream));
    if (params.stream) {
      return this.transport.stream("POST", "/v1/chat/completions", payload);
    }
    return this.transport.request("POST", "/v1/chat/completions", payload);
  }
}

class Chat {
  readonly completions: ChatCompletions;
  constructor(transport: Transport) {
    this.completions = new ChatCompletions(transport);
  }
}

class Embeddings {
  constructor(private readonly transport: Transport) {}

  create(params: EmbeddingsParams): Promise<Record<string, unknown>> {
    return this.transport.request("POST", "/v1/embeddings", params);
  }
}

class Models {
  constructor(private readonly transport: Transport) {}

  list(): Promise<Record<string, unknown>> {
    return this.transport.request("GET", "/v1/models");
  }
}

/**
 * Client for the Setu Gateway's OpenAI-compatible API.
 *
 * ```ts
 * const client = new SetuClient({ apiKey: "sk_setu_...", baseUrl: "https://gateway.example.com" });
 * const response = await client.chat.completions.create({
 *   model: "gpt-4o",
 *   messages: [{ role: "user", content: "hi" }],
 * });
 * ```
 */
export class SetuClient {
  readonly apiKey?: string;
  readonly baseUrl: string;
  readonly chat: Chat;
  readonly embeddings: Embeddings;
  readonly models: Models;

  constructor(options: SetuClientOptions = {}) {
    this.apiKey = options.apiKey ?? resolveEnv("SETU_API_KEY");
    this.baseUrl = (options.baseUrl ?? resolveEnv("SETU_BASE_URL") ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    const fetchImpl = options.fetchImpl ?? fetch;

    const transport = new Transport(this.baseUrl, this.apiKey, timeoutMs, fetchImpl);
    this.chat = new Chat(transport);
    this.embeddings = new Embeddings(transport);
    this.models = new Models(transport);
  }
}
