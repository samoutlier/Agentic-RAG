import type { DomainId } from "@/lib/domains";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// Shape of the JSON returned by the backend's POST /ingest
export type IngestResult = {
  filename: string;
  domain: DomainId;
  pages_parsed: number;
  chunks_stored: number;
};

// Carries the HTTP status so callers can react to specific cases, e.g. 429 rate limits
export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

// FastAPI sends errors as {"detail": "..."} for our own 400s,
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
  return `Request failed with status ${response.status}`;
}

// fetch() only throws when the server can't be reached at all
async function request(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch {
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

// The events the backend's POST /stream sends, one per `data:` line
type StreamEvent =
  | { type: "sources"; content: Source[] }
  | { type: "token"; content: string }
  | { type: "error"; content: string }
  | { type: "done"; content: string };

type StreamHandlers = {
  onSources: (sources: Source[]) => void;
  onToken: (token: string) => void;
};

// One earlier message, sent back so follow-up questions have context
export type ChatTurn = {
  role: "user" | "assistant";
  content: string;
};

/**
 * Ask a question via POST /stream and receive the answer piece by piece.
 * `history` is the earlier conversation, oldest first.
 * Resolves once the answer is complete; throws if anything goes wrong.
 */
export async function streamQuery(
  question: string,
  domain: DomainId,
  history: ChatTurn[],
  handlers: StreamHandlers,
): Promise<void> {
  const response = await request("/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, domain, history }),
  });

  // EventSource only supports GET, so we read the POST response body as a
  // stream ourselves. Each read() returns whatever bytes have arrived so far.
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    // A network chunk can end in the middle of an event, so split on the
    // blank line that ends each event and keep any incomplete tail for later.
    buffer += decoder.decode(value, { stream: true });
    const rawEvents = buffer.split("\n\n");
    buffer = rawEvents.pop() ?? "";

    for (const rawEvent of rawEvents) {
      if (!rawEvent.startsWith("data: ")) continue;
      const event: StreamEvent = JSON.parse(rawEvent.slice("data: ".length));

      if (event.type === "sources") handlers.onSources(event.content);
      else if (event.type === "token") handlers.onToken(event.content);
      else if (event.type === "error") throw new Error(event.content);
      else if (event.type === "done") return;
    }
  }

  // The connection closed without a "done" event: the answer was cut off
  throw new Error("The response was cut off before it finished. Please try again.");
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
