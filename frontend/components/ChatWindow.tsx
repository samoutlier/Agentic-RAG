"use client";

import { useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, LoaderCircle, Square } from "lucide-react";
import {
  isAbortError,
  MAX_QUESTION_CHARS,
  streamQuery,
  type ChatTurn,
  type Source,
} from "@/lib/api";
import { getDomain, type DomainId } from "@/lib/domains";
import { SourceCitations } from "@/components/SourceCitation";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

// How many earlier messages to send with each question: the last 3
// question-and-answer pairs. The backend applies the same cap.
const HISTORY_MESSAGES_TO_SEND = 6;

// How close to the bottom (in pixels) still counts as "at the bottom"
const STICK_TO_BOTTOM_PX = 80;

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  error?: string;
  stopped?: boolean; // the user pressed Stop before the answer finished
};

// Messages are always added in pairs: a question, then its answer.
// Only pairs whose answer finished are sent back, so the model never sees
// an error message or a half-finished answer as if it were a real answer.
function toHistory(messages: ChatMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  for (let i = 0; i + 1 < messages.length; i += 2) {
    const question = messages[i];
    const answer = messages[i + 1];
    if (answer.content && !answer.error && !answer.stopped) {
      turns.push(
        { role: "user", content: question.content },
        { role: "assistant", content: answer.content },
      );
    }
  }
  return turns.slice(-HISTORY_MESSAGES_TO_SEND);
}

export function ChatWindow({ domain }: { domain: DomainId }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  // The id of the answer currently streaming in, or null when idle
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Whether new text should keep the view pinned to the bottom. It turns off
  // when the user scrolls up to read, so streaming doesn't drag them back down.
  const stickToBottomRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  // Lets the Stop button cancel the request that is streaming
  const abortRef = useRef<AbortController | null>(null);
  const label = getDomain(domain).label.toLowerCase();

  // useLayoutEffect runs after React updates the page but before the browser
  // paints it, so new text is scrolled into view without a visible jump.
  useLayoutEffect(() => {
    const container = scrollRef.current;
    if (container && stickToBottomRef.current) {
      container.scrollTop = container.scrollHeight;
      // Record where we scrolled to right away, so a user scrolling up in the
      // same moment is still detected as an upward move by handleScroll.
      lastScrollTopRef.current = container.scrollTop;
    }
  }, [messages]);

  function handleScroll() {
    const container = scrollRef.current;
    if (!container) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;

    if (distanceFromBottom < STICK_TO_BOTTOM_PX) {
      stickToBottomRef.current = true;
    } else if (container.scrollTop < lastScrollTopRef.current) {
      // Only an upward move means the user wants to read. Checking "far from
      // the bottom" alone isn't enough: the scroll event from our own
      // auto-scroll can fire after more text has already been added below,
      // which would wrongly switch auto-scrolling off.
      stickToBottomRef.current = false;
    }
    lastScrollTopRef.current = container.scrollTop;
  }

  // Change one message, found by id. The updater form of setMessages matters:
  // tokens arrive faster than React re-renders, so each update must build on
  // the latest state rather than on a stale copy captured earlier.
  function updateMessage(id: string, change: (message: ChatMessage) => ChatMessage) {
    setMessages((previous) => previous.map((m) => (m.id === id ? change(m) : m)));
  }

  async function sendQuestion() {
    const question = input.trim();
    if (!question || streamingId) return;

    // Capture the conversation before adding the new question to it
    const history = toHistory(messages);

    // Add the question and an empty answer that tokens will be appended to
    const answerId = crypto.randomUUID();
    setMessages((previous) => [
      ...previous,
      { id: crypto.randomUUID(), role: "user", content: question, sources: [] },
      { id: answerId, role: "assistant", content: "", sources: [] },
    ]);
    setInput("");
    setStreamingId(answerId);
    stickToBottomRef.current = true; // always show a newly sent question

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamQuery(
        question,
        domain,
        history,
        {
          onSources: (sources) => updateMessage(answerId, (m) => ({ ...m, sources })),
          onToken: (token) =>
            updateMessage(answerId, (m) => ({ ...m, content: m.content + token })),
        },
        controller.signal,
      );
    } catch (error) {
      if (isAbortError(error)) {
        // Stopped on purpose: keep whatever arrived, and don't show it as an error
        updateMessage(answerId, (m) => ({ ...m, stopped: true }));
      } else {
        const message = error instanceof Error ? error.message : "Something went wrong.";
        updateMessage(answerId, (m) => ({ ...m, error: message }));
      }
    } finally {
      abortRef.current = null;
      setStreamingId(null);
    }
  }

  return (
    <Card className="h-[70vh] min-h-[28rem] lg:h-[640px]">
      <CardHeader className="border-b">
        <CardTitle>Ask about your {label} documents</CardTitle>
        <CardDescription>
          Answers come only from indexed {label} documents, with their sources.
        </CardDescription>
        <CardAction>
          {/* Clearing the chat also clears the history sent with the next
              question, so a new topic starts without old context. */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setMessages([])}
            disabled={messages.length === 0 || streamingId !== null}
          >
            New chat
          </Button>
        </CardAction>
      </CardHeader>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto px-4"
      >
        {messages.length === 0 ? (
          <p className="flex h-full items-center justify-center text-center text-muted-foreground">
            Ask a question to get started. Follow-up questions remember this conversation.
          </p>
        ) : (
          <ul className="flex flex-col gap-5">
            {messages.map((message) => (
              <li key={message.id}>
                {message.role === "user" ? (
                  <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 whitespace-pre-wrap text-primary-foreground">
                    {message.content}
                  </div>
                ) : (
                  <div>
                    {message.content && (
                      // react-markdown turns the model's **bold**, lists and
                      // tables into HTML. It never renders raw HTML from the
                      // text, so model output can't inject scripts into the page.
                      <div className="prose prose-sm max-w-none dark:prose-invert [&_table]:block [&_table]:overflow-x-auto">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    )}

                    {message.id === streamingId && !message.content && (
                      // Sources arrive before the first word of the answer,
                      // so their arrival marks the switch from searching to writing.
                      <span className="flex items-center gap-2 text-muted-foreground">
                        <LoaderCircle className="size-4 animate-spin" />
                        {message.sources.length > 0
                          ? "Writing the answer…"
                          : "Searching your documents…"}
                      </span>
                    )}

                    {message.stopped && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        {message.content ? "Stopped." : "Stopped before the answer started."}
                      </p>
                    )}

                    {message.error && (
                      <p
                        role="alert"
                        className="mt-2 rounded-lg bg-destructive/10 px-3 py-2 text-destructive"
                      >
                        {message.error}
                      </p>
                    )}

                    <SourceCitations sources={message.sources} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          sendQuestion();
        }}
        className="flex items-end gap-2 border-t px-4 pt-4"
      >
        <Textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends, Shift+Enter adds a new line. isComposing skips the
            // Enter that confirms a word in IME keyboards (e.g. Chinese input).
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              sendQuestion();
            }
          }}
          placeholder={`Ask about your ${label} documents…`}
          aria-label="Your question"
          maxLength={MAX_QUESTION_CHARS}
          rows={1}
          className="max-h-40 min-h-9 resize-none"
        />
        {streamingId ? (
          <Button
            type="button"
            variant="outline"
            size="icon-lg"
            onClick={() => abortRef.current?.abort()}
            aria-label="Stop answer"
            title="Stop"
          >
            <Square className="fill-current" />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon-lg"
            disabled={!input.trim()}
            aria-label="Send question"
          >
            <ArrowUp />
          </Button>
        )}
      </form>
    </Card>
  );
}
