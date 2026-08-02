/** Base class for all errors raised by the Setu Gateway SDK. */
export class SetuError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SetuError";
  }
}

/**
 * The gateway responded with a non-2xx status. `statusCode` and `body` are the raw
 * HTTP status and parsed (or raw text) response body, for callers that want to
 * branch on specific error shapes rather than just the message.
 */
export class SetuAPIError extends SetuError {
  statusCode: number;
  body: unknown;

  constructor(message: string, statusCode: number, body: unknown) {
    super(message);
    this.name = "SetuAPIError";
    this.statusCode = statusCode;
    this.body = body;
  }
}

/** The gateway could not be reached at all (DNS, connection refused, timeout). */
export class SetuConnectionError extends SetuError {
  constructor(message: string) {
    super(message);
    this.name = "SetuConnectionError";
  }
}
