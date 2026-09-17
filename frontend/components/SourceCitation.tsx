import { FileText } from "lucide-react";
import type { Source } from "@/lib/api";

// Sources scoring within this much of the best match are shown directly;
// the rest are folded away as weaker matches. A fixed cut-off (e.g. "hide
// below 50%") doesn't work: in testing, clearly relevant passages scored as
// low as 55% in one document while unrelated ones reached 60% in another.
// Within a single question, though, the useful passages cluster near the top.
const WEAKER_MATCH_MARGIN = 0.1;

// If even the best passage scores below this, warn that the sources may not
// relate to the question at all.
const LOW_CONFIDENCE = 0.5;

// FAISS returns the squared distance between two unit-length vectors,
// which converts to cosine similarity as: similarity = 1 - distance / 2.
function toSimilarity(distance: number): number {
  return Math.min(1, Math.max(0, 1 - distance / 2));
}

function SourceList({ sources }: { sources: Source[] }) {
  return (
    <ul className="flex flex-col gap-2">
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
              Page {source.page} · {Math.round(toSimilarity(source.distance) * 100)}% match
            </span>
          </div>
          <p className="mt-1.5 line-clamp-3 text-muted-foreground">
            {source.text_preview}
            {source.text_preview.length >= 200 && "…"}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function SourceCitations({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;

  // Best match first; the backend already sends them in this order
  const sorted = [...sources].sort((a, b) => a.distance - b.distance);
  const best = toSimilarity(sorted[0].distance);
  const strong = sorted.filter((s) => toSimilarity(s.distance) >= best - WEAKER_MATCH_MARGIN);
  const weaker = sorted.filter((s) => toSimilarity(s.distance) < best - WEAKER_MATCH_MARGIN);

  return (
    // Native <details>/<summary> gives an accessible expand/collapse
    // toggle with no JavaScript or state needed.
    <details className="mt-3 rounded-lg border text-sm">
      <summary className="cursor-pointer px-3 py-2 font-medium text-muted-foreground select-none hover:text-foreground">
        {strong.length} source{strong.length === 1 ? "" : "s"}
        {weaker.length > 0 && ` · ${weaker.length} weaker match${weaker.length === 1 ? "" : "es"} hidden`}
      </summary>

      <div className="flex flex-col gap-2 border-t p-3">
        {best < LOW_CONFIDENCE && (
          <p className="text-xs text-muted-foreground">
            Even the closest passage is a weak match, so these may not relate to your question.
          </p>
        )}

        <SourceList sources={strong} />

        {weaker.length > 0 && (
          <details>
            <summary className="cursor-pointer text-xs text-muted-foreground select-none hover:text-foreground">
              Show {weaker.length} weaker match{weaker.length === 1 ? "" : "es"}
            </summary>
            <div className="mt-2">
              <SourceList sources={weaker} />
            </div>
          </details>
        )}
      </div>
    </details>
  );
}
