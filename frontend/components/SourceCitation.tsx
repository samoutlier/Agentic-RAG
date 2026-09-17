import { FileText } from "lucide-react";
import type { Source } from "@/lib/api";

// FAISS returns the squared distance between two unit-length vectors,
// which converts to cosine similarity as: similarity = 1 - distance / 2.
function toMatchPercent(distance: number): number {
  const similarity = Math.min(1, Math.max(0, 1 - distance / 2));
  return Math.round(similarity * 100);
}

export function SourceCitations({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;

  return (
    // Native <details>/<summary> gives an accessible expand/collapse
    // toggle with no JavaScript or state needed.
    <details className="mt-3 rounded-lg border text-sm">
      <summary className="cursor-pointer px-3 py-2 font-medium text-muted-foreground select-none hover:text-foreground">
        {sources.length} source{sources.length === 1 ? "" : "s"} used
      </summary>

      <ul className="flex flex-col gap-2 border-t p-3">
        {sources.map((source) => (
          <li
            key={`${source.filename}-${source.chunk_id}`}
            className="rounded-md bg-muted/50 p-2.5"
          >
            <div className="flex items-center gap-2">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate font-medium" title={source.filename}>
                {source.filename}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                Page {source.page} · {toMatchPercent(source.distance)}% match
              </span>
            </div>
            <p className="mt-1.5 line-clamp-3 text-muted-foreground">
              {source.text_preview}
              {source.text_preview.length >= 200 && "…"}
            </p>
          </li>
        ))}
      </ul>
    </details>
  );
}
