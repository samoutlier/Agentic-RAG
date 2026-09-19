"use client";

import type { ScoreResult } from "@/lib/ipo";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function ScoreBreakdown({ score }: { score: ScoreResult }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>How the score is made</CardTitle>
        <CardDescription>
          Calculated in Python from the agents&apos; findings, so it never varies between runs. Every point lost
          has a reason.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {score.parts.map((part) => {
          const share = part.points / part.max_points;
          return (
            <section key={part.name} className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="font-medium">
                  {part.label}
                  {!part.complete && <span className="font-normal text-muted-foreground"> (incomplete)</span>}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {part.points.toFixed(1)} / {part.max_points}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted" role="presentation">
                <div
                  className={share >= 0.6 ? "h-full bg-emerald-500" : share >= 0.4 ? "h-full bg-amber-500" : "h-full bg-red-500"}
                  style={{ width: `${Math.max(share * 100, 2)}%` }}
                />
              </div>
              <ul className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                {part.reasons.map((reason, i) => (
                  <li key={i}>{reason}</li>
                ))}
              </ul>
            </section>
          );
        })}
      </CardContent>
    </Card>
  );
}
