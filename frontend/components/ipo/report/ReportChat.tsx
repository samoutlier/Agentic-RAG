"use client";

import { useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CircleStop, LoaderCircle, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import { isAbortError, MAX_QUESTION_CHARS, type ChatTurn } from "@/lib/api";
import { streamChat, type IpoSource } from "@/lib/ipo";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PageLinks } from "@/components/ipo/report/shared";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: IpoSource[];
  error?: string;
};

const SUGGESTIONS = [
  "What does the company do, in plain English?",
  "What are the biggest risks for an investor?",
  "How will the IPO money be used?",
  "Is the profit backed by cash?",
];

/** The last few turns, as the backend expects them. */
function toHistory(messages: Message[]): ChatTurn[] {
  return messages
    .filter((message) => !message.error && message.content.trim())
    .map((message) => ({ role: message.role, content: message.content }));
}

export function ReportChat({ documentId }: { documentId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Following the answer down, until the reader scrolls up to read
  const stickToBottomRef = useRef(true);
  const lastScrollTopRef = useRef(0);

  // Scroll after the DOM updates but before the browser paints, so new
  // text appears already scrolled into view
  useLayoutEffect(() => {
    const container = scrollRef.current;
    if (container && stickToBottomRef.current) {
      container.scrollTop = container.scrollHeight;
      lastScrollTopRef.current = container.scrollTop;
    }
  }, [messages]);

  function handleScroll() {
    const container = scrollRef.current;
    if (!container) return;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceFromBottom < 40) {
      stickToBottomRef.current = true;
    } else if (container.scrollTop < lastScrollTopRef.current) {
      stickToBottomRef.current = false; // the reader scrolled up
    }
    lastScrollTopRef.current = container.scrollTop;
  }

  function update(id: string, change: (message: Message) => Message) {
    setMessages((current) => current.map((message) => (message.id === id ? change(message) : message)));
  }

  async function ask(question: string) {
    const text = question.trim();
    if (!text || streamingId) return;

    const answerId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content: text },
      { id: answerId, role: "assistant", content: "" },
    ]);
    setInput("");
    setStreamingId(answerId);
    stickToBottomRef.current = true;

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamChat(
        documentId,
        text,
        toHistory(messages),
        {
          onSources: (sources) => update(answerId, (message) => ({ ...message, sources })),
          onToken: (token) => update(answerId, (message) => ({ ...message, content: message.content + token })),
        },
        controller.signal,
      );
    } catch (error) {
      if (isAbortError(error)) {
        update(answerId, (message) => ({ ...message, content: message.content || "(stopped)" }));
      } else {
        update(answerId, (message) => ({
          ...message,
          error: error instanceof Error ? error.message : "The answer failed.",
        }));
      }
    } finally {
      abortRef.current = null;
      setStreamingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        Ask about this IPO. Answers come from the analysis above and from passages found in the document, with the
        pages they came from.
      </p>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex max-h-[28rem] min-h-40 flex-col gap-4 overflow-y-auto rounded-md border p-4"
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-muted-foreground">Try one of these:</p>
            {SUGGESTIONS.map((suggestion) => (
              <Button key={suggestion} variant="outline" size="sm" onClick={() => ask(suggestion)}>
                {suggestion}
              </Button>
            ))}
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={cn("flex flex-col gap-1", message.role === "user" ? "items-end" : "items-start")}
            >
              <div
                className={cn(
                  "max-w-[90%] rounded-lg px-3 py-2 text-sm",
                  message.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted",
                )}
              >
                {message.error ? (
                  <span className="text-destructive">{message.error}</span>
                ) : message.content ? (
                  <div className="prose prose-sm dark:prose-invert max-w-none [&_p]:my-1">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                  </div>
                ) : (
                  <LoaderCircle className="size-4 animate-spin" />
                )}
              </div>
              {message.sources && message.sources.length > 0 && (
                <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                  From <PageLinks pages={[...new Set(message.sources.map((source) => source.page))].sort((a, b) => a - b)} />
                </p>
              )}
            </div>
          ))
        )}
      </div>

      <form
        className="flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          ask(input);
        }}
      >
        <Textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends; Shift+Enter starts a new line
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              ask(input);
            }
          }}
          maxLength={MAX_QUESTION_CHARS}
          rows={2}
          placeholder="Ask about the risks, financials, promoters, the offer…"
          disabled={Boolean(streamingId)}
          className="min-h-0 flex-1 resize-none"
        />
        {streamingId ? (
          <Button type="button" variant="outline" onClick={() => abortRef.current?.abort()}>
            <CircleStop /> Stop
          </Button>
        ) : (
          <Button type="submit" disabled={!input.trim()}>
            <Send /> Ask
          </Button>
        )}
      </form>
    </div>
  );
}
