"use client";

import { createContext, useContext, type ReactNode } from "react";
import { CircleAlert, Info, OctagonAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { FLAG_STYLES } from "@/lib/format";
import { pageUrl, type Cited, type Flag } from "@/lib/ipo";

// Which document the page links open, and how its printed page numbers map
// to PDF pages. Provided once by <Report>, read by every <PageLinks>.
export const DocumentContext = createContext<{ documentId: string; pageOffset: number } | null>(null);

/** "p. 162" links that open the uploaded PDF at each printed page. */
export function PageLinks({ pages, className }: { pages: number[]; className?: string }) {
  const document = useContext(DocumentContext);
  if (!pages.length || !document) return null;
  return (
    <span className={cn("inline-flex flex-wrap gap-1 align-middle", className)}>
      {pages.map((page) => (
        <a
          key={page}
          href={pageUrl(document.documentId, page, document.pageOffset)}
          target="_blank"
          rel="noreferrer"
          title={`Open page ${page} of the document`}
          className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium tabular-nums text-muted-foreground hover:bg-muted/60 hover:text-foreground"
        >
          p. {page}
        </a>
      ))}
    </span>
  );
}

/** A statement followed by the pages that support it. */
export function CitedText({ item }: { item: Cited }) {
  return (
    <>
      {item.text} <PageLinks pages={item.pages} />
    </>
  );
}

export function CitedList({ items, empty }: { items: Cited[]; empty: string }) {
  if (!items.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="flex list-disc flex-col gap-2 pl-5">
      {items.map((item, i) => (
        <li key={i}>
          <CitedText item={item} />
        </li>
      ))}
    </ul>
  );
}

const FLAG_ICONS = { red: OctagonAlert, amber: CircleAlert, info: Info };

export function FlagList({ flags }: { flags: Flag[] }) {
  if (!flags.length) return null;
  return (
    <ul className="flex flex-col gap-2">
      {flags.map((flag, i) => {
        const Icon = FLAG_ICONS[flag.severity];
        return (
          <li key={i} className={cn("flex gap-2 rounded-md border px-3 py-2 text-sm", FLAG_STYLES[flag.severity])}>
            <Icon className="mt-0.5 size-4 shrink-0" />
            <span>{flag.message}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="text-sm font-semibold">{children}</h3>;
}

type AgentOutput = { status: string; model: string; tokens: number; seconds: number; error?: string; warnings?: string[] };

/** How an agent's section was produced, and anything its checks noticed. */
export function AgentFooter({ output }: { output: AgentOutput | null }) {
  if (!output) return null;
  const warnings = output.warnings ?? [];
  return (
    <div className="flex flex-col gap-1 border-t pt-3 text-xs text-muted-foreground">
      <p>
        {output.model} · {output.tokens.toLocaleString("en-IN")} tokens · {output.seconds.toFixed(0)}s
        {output.status === "failed" && <span className="text-destructive"> · failed: {output.error}</span>}
      </p>
      {warnings.length > 0 && (
        <details>
          <summary className="cursor-pointer hover:text-foreground">
            {warnings.length} note{warnings.length === 1 ? "" : "s"} from the accuracy checks
          </summary>
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((warning, i) => (
              <li key={i}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** Shown in place of a section whose agent produced nothing. */
export function Unavailable({ what, output }: { what: string; output: { error?: string } | null }) {
  return (
    <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
      The {what} isn&apos;t available{output?.error ? `: ${output.error}` : "."}
    </p>
  );
}
