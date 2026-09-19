"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { RISK_CATEGORIES, SCORE_STYLES } from "@/lib/format";
import type { RiskResult } from "@/lib/ipo";
import { Button } from "@/components/ui/button";
import { AgentFooter, PageLinks, Unavailable } from "@/components/ipo/report/shared";

const SEVERITIES = ["all", "high", "medium", "low"] as const;

export function RiskDetails({ risk }: { risk: RiskResult | null }) {
  const [severity, setSeverity] = useState<(typeof SEVERITIES)[number]>("all");
  const [category, setCategory] = useState("all");

  if (!risk?.register || !risk.counts) return <Unavailable what="risk register" output={risk} />;
  const counts = risk.counts;
  const shown = risk.register.filter(
    (r) => (severity === "all" || r.severity === severity) && (category === "all" || r.category === category),
  );
  const largestCategory = Math.max(...Object.values(counts.by_category), 1);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <p className="text-sm leading-relaxed">
          <span className="font-medium">{counts.total} risk factors</span>, each scored from 1 (standard wording
          found in most offer documents) to 5 (a threat to the core business). Average score{" "}
          <span className="font-medium">{counts.average_score ?? "–"}</span>: {counts.by_severity.high} high (4–5),{" "}
          {counts.by_severity.medium} medium (3), {counts.by_severity.low} low (1–2).
        </p>
        <ul className="flex flex-col gap-1 text-sm">
          {Object.entries(counts.by_category).map(([key, count]) => (
            <li key={key} className="grid grid-cols-[10rem_1fr_2rem] items-center gap-2">
              <span className="truncate text-muted-foreground">{RISK_CATEGORIES[key] ?? key}</span>
              <span className="h-2 rounded-full bg-muted">
                <span className="block h-full rounded-full bg-foreground/60" style={{ width: `${(count / largestCategory) * 100}%` }} />
              </span>
              <span className="text-right tabular-nums">{count}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {SEVERITIES.map((level) => (
          <Button
            key={level}
            size="sm"
            variant={severity === level ? "default" : "outline"}
            onClick={() => setSeverity(level)}
          >
            {level === "all" ? "All" : level[0].toUpperCase() + level.slice(1)}
          </Button>
        ))}
        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          aria-label="Filter by category"
          className="h-7 rounded-md border bg-background px-2 text-sm"
        >
          <option value="all">All categories</option>
          {Object.entries(RISK_CATEGORIES).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <span className="text-sm text-muted-foreground">{shown.length} shown</span>
      </div>

      <ol className="flex flex-col divide-y rounded-md border">
        {shown.map((item) => (
          <li key={item.number}>
            <details className="group px-3 py-2">
              <summary className="flex cursor-pointer list-none items-start gap-3">
                <span
                  className={cn("mt-0.5 w-6 shrink-0 rounded text-center text-xs font-semibold leading-5", SCORE_STYLES[item.score ?? 1])}
                  title="Risk score, 1 to 5"
                >
                  {item.score ?? "?"}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{item.headline}</span>
                  <span className="block text-xs text-muted-foreground">
                    #{item.number} · {RISK_CATEGORIES[item.category ?? ""] ?? "Unclassified"}
                  </span>
                </span>
                <PageLinks pages={[item.page]} />
              </summary>
              <p className="mt-2 pl-9 text-sm text-muted-foreground">{item.text}</p>
            </details>
          </li>
        ))}
      </ol>

      <AgentFooter output={risk} />
    </div>
  );
}
