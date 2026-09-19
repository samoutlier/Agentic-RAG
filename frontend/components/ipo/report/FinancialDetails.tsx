"use client";

import { cn } from "@/lib/utils";
import { METRICS, SIGNAL_STYLES, formatMetric, humanise } from "@/lib/format";
import type { FinancialResult } from "@/lib/ipo";
import { AgentFooter, FlagList, PageLinks, SectionTitle, Unavailable } from "@/components/ipo/report/shared";

const GROWTH_LABELS: Record<string, string> = {
  revenue_cagr: "Revenue",
  ebitda_cagr: "EBITDA",
  pat_cagr: "Profit after tax",
  trade_receivables_cagr: "Trade receivables",
  borrowings_cagr: "Borrowings",
};

export function FinancialDetails({ financial }: { financial: FinancialResult | null }) {
  if (!financial?.scorecard || !financial.periods || !financial.metrics) {
    return <Unavailable what="financial analysis" output={financial} />;
  }
  const metrics = financial.metrics;
  // Oldest full year first so trends read left to right; part-year periods last
  const periods = [
    ...financial.periods.filter((p) => p.full_year).reverse(),
    ...financial.periods.filter((p) => !p.full_year),
  ];
  const rows = Object.entries(METRICS).filter(([key]) =>
    periods.some((p) => metrics[key]?.[p.label] !== null && metrics[key]?.[p.label] !== undefined),
  );
  const growth = financial.growth ?? {};
  const assessment = financial.assessment;

  return (
    <div className="flex flex-col gap-6">
      {assessment && (
        <section className="flex flex-col gap-3">
          <p className="leading-relaxed">{assessment.summary}</p>
          <div className="grid gap-4 md:grid-cols-2">
            {[
              { title: "Strengths", items: assessment.strengths },
              { title: "Concerns", items: assessment.concerns },
            ].map(({ title, items }) => (
              <div key={title} className="flex flex-col gap-2">
                <SectionTitle>{title}</SectionTitle>
                <ul className="flex list-disc flex-col gap-2 pl-5 text-sm">
                  {items.map((item, i) => (
                    <li key={i}>
                      {item.point}{" "}
                      <span className="text-xs text-muted-foreground">
                        ({item.metrics.map((m) => METRICS[m]?.label ?? m).join(", ")})
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <SectionTitle>Scorecard</SectionTitle>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {financial.scorecard.map((item) => (
            <div key={item.dimension} className="flex flex-col gap-1 rounded-md border p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{humanise(item.dimension)}</span>
                <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", SIGNAL_STYLES[item.signal])}>
                  {item.signal}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">{item.reason}</p>
            </div>
          ))}
        </div>
      </section>

      {(financial.flags ?? []).length > 0 && (
        <section className="flex flex-col gap-2">
          <SectionTitle>Red flags</SectionTitle>
          <FlagList flags={financial.flags!} />
        </section>
      )}

      <section className="flex flex-col gap-2">
        <SectionTitle>Ratios by period</SectionTitle>
        <p className="text-xs text-muted-foreground">
          ₹ million (the document reports in {financial.reported_unit}). From the Summary of Financial Information:
          balance sheet, profit and loss and cash flow on <PageLinks pages={Object.values(financial.pages ?? {})} />
        </p>
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">Metric</th>
                {periods.map((p) => (
                  <th key={p.label} className="px-3 py-2 text-right font-medium whitespace-nowrap">
                    {p.label}
                    {!p.full_year && <span className="block text-xs font-normal text-muted-foreground">part-year</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map(([key, { label, unit }]) => (
                <tr key={key}>
                  <td className="px-3 py-1.5 whitespace-nowrap">{label}</td>
                  {periods.map((p) => (
                    <td key={p.label} className="px-3 py-1.5 text-right tabular-nums">
                      {formatMetric(metrics[key]?.[p.label], unit)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {growth.from && (
          <p className="text-sm text-muted-foreground">
            Growth per year, {String(growth.from)} to {String(growth.to)}:{" "}
            {Object.entries(GROWTH_LABELS)
              .filter(([key]) => typeof growth[key] === "number")
              .map(([key, label]) => `${label} ${(growth[key] as number).toFixed(1)}%`)
              .join(" · ")}
          </p>
        )}
      </section>

      <AgentFooter output={financial} />
    </div>
  );
}
