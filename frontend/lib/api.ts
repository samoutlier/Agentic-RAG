import type { DomainId } from "@/lib/domains";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// Must match MAX_UPLOAD_MB and MAX_QUESTION_CHARS in backend/app/config.py.
// Checking here too gives instant feedback without a round trip.
export const MAX_UPLOAD_MB = 50;
export const MAX_QUESTION_CHARS = 2000;

// Shape of the JSON returned by the backend's POST /ingest
export type IngestResult = {
  filename: string;
  domain: DomainId;
  // Who chose the domain: the user, the LLM classifier, or the keyword fallback
  detected_by: "user" | "llm" | "keywords";
  pages_parsed: number;
  chunks_stored: number;
};

// One document stored on the backend, as returned by GET /documents
export type StoredDocument = {
  filename: string;
  domain: DomainId;
  chunks: number;
  pages: number;
};

// Carries the HTTP status so callers can react to specific cases, e.g. 429 rate limits
export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

// True when a request was cancelled on purpose with an AbortController
// (the chat's Stop button), as opposed to failing.
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

// FastAPI sends errors as {"detail": "..."} for our own 4xx responses,
// or {"detail": [{msg: "..."}, ...]} when request validation fails (422).
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg: string }) => d.msg).join("; ");
    }
  } catch {
    // Body wasn't JSON (e.g. a plain "Internal Server Error")
  }
  if (response.status >= 500) {
    return `The server hit an unexpected error (${response.status}). Check the backend terminal for details.`;
  }
  return `Request failed with status ${response.status}`;
}

// fetch() only throws when the server can't be reached at all, or when the
// request was cancelled on purpose (which must not be reported as "unreachable")
export async function request(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(
      `Can't reach the backend at ${API_URL}. Is uvicorn running?`,
      0,
    );
  }
  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response), response.status);
  }
  return response;
}

// One retrieved chunk, as sent in the stream's "sources" event
export type Source = {
  filename: string;
  page: number;
  chunk_id: number;
  text_preview: string;
  distance: number;
};

// The events a streaming endpoint sends, one per `data:` line. The shape of
// "sources" depends on the endpoint, so each caller casts it.
export type StreamEvent = { type: "sources" | "token" | "error" | "done"; content: unknown };

type StreamHandlers = {
  onSources: (sources: Source[]) => void;
  onToken: (token: string) => void;
};

/**
 * Read a Server-Sent Events response, passing each event to `onEvent`.
 * Returns when the stream's "done" event arrives; throws if the stream
 * reports an error or stops early.
 */
export async function readEventStream(
  response: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  // EventSource only supports GET, so we read the POST response body as a
  // stream ourselves. Each read() returns whatever bytes have arrived so far.
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch (error) {
      if (isAbortError(error)) throw error;
      // The connection dropped mid-answer (backend stopped, network lost)
      throw new Error("Lost the connection to the backend while the answer was arriving. Please try again.");
    }
    if (chunk.done) break;

    // A network chunk can end in the middle of an event, so split on the
    // blank line that ends each event and keep any incomplete tail for later.
    buffer += decoder.decode(chunk.value, { stream: true });
    const rawEvents = buffer.split("\n\n");
    buffer = rawEvents.pop() ?? "";

    for (const rawEvent of rawEvents) {
      if (!rawEvent.startsWith("data: ")) continue;

      let event: StreamEvent;
      try {
        event = JSON.parse(rawEvent.slice("data: ".length));
      } catch {
        throw new Error("Received an unreadable response from the backend. Please try again.");
      }

      if (event.type === "error") throw new Error(String(event.content));
      if (event.type === "done") return;
      onEvent(event);
    }
  }

  // The connection closed without a "done" event: the answer was cut off
  throw new Error("The response was cut off before it finished. Please try again.");
}

// One earlier message, sent back so follow-up questions have context
export type ChatTurn = {
  role: "user" | "assistant";
  content: string;
};

/**
 * Ask a question via POST /stream and receive the answer piece by piece.
 * `history` is the earlier conversation, oldest first.
 * Pass an AbortSignal to be able to cancel; cancelling throws an AbortError.
 * Resolves once the answer is complete; throws if anything goes wrong.
 */
export async function streamQuery(
  question: string,
  domain: DomainId,
  history: ChatTurn[],
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await request("/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, domain, history }),
    signal,
  });

  await readEventStream(response, (event) => {
    if (event.type === "sources") handlers.onSources(event.content as Source[]);
    else if (event.type === "token") handlers.onToken(event.content as string);
  });
}

/**
 * Upload a document to POST /ingest.
 * Pass `domain = null` to let the backend auto-detect the domain.
 */
export async function uploadDocument(
  file: File,
  domain: DomainId | null,
): Promise<IngestResult> {
  // multipart/form-data: the browser sets the Content-Type header (including
  // the boundary string) automatically, so we must not set it ourselves.
  const form = new FormData();
  form.append("file", file);
  if (domain) form.append("domain", domain);

  const response = await request("/ingest", { method: "POST", body: form });
  return response.json();
}

/** Every document stored on the backend, across all domains. */
export async function listDocuments(): Promise<StoredDocument[]> {
  const response = await request("/documents");
  return response.json();
}

/** Delete a document from its domain on the backend. */
export async function deleteDocument(domain: DomainId, filename: string): Promise<void> {
  // encodeURIComponent keeps spaces, "#", "?" etc. in filenames from breaking the URL
  await request(`/documents/${domain}/${encodeURIComponent(filename)}`, { method: "DELETE" });
}
