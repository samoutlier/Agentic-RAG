"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, LoaderCircle } from "lucide-react";
import { streamQuery, type ChatTurn, type Source } from "@/lib/api";
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

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  error?: string;
};

// Messages are always added in pairs: a question, then its answer.
// Only pairs whose answer finished successfully are sent back, so the model
// never sees an error message as if it were a real answer.
function toHistory(messages: ChatMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  for (let i = 0; i + 1 < messages.length; i += 2) {
    const question = messages[i];
    const answer = messages[i + 1];
    if (answer.content && !answer.error) {
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
  const label = getDomain(domain).label.toLowerCase();

  // Keep the newest text in view as tokens arrive
  useEffect(() => {
    const container = scrollRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages]);

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

    try {
      await streamQuery(question, domain, history, {
        onSources: (sources) => updateMessage(answerId, (m) => ({ ...m, sources })),
        onToken: (token) =>
          updateMessage(answerId, (m) => ({ ...m, content: m.content + token })),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Something went wrong.";
      updateMessage(answerId, (m) => ({ ...m, error: message }));
    } finally {
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

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4">
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
                      <span className="flex items-center gap-2 text-muted-foreground">
                        <LoaderCircle className="size-4 animate-spin" />
                        Reading the documents…
                      </span>
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
          rows={1}
          className="max-h-40 min-h-9 resize-none"
        />
        <Button
          type="submit"
          size="icon-lg"
          disabled={!input.trim() || streamingId !== null}
          aria-label="Send question"
        >
          {streamingId ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}
        </Button>
      </form>
    </Card>
  );
}
