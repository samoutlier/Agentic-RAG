"use client";

import { CASE_TYPES, PARTIES, formatMillion } from "@/lib/format";
import type { LegalCase, LegalResult } from "@/lib/ipo";
import { AgentFooter, FlagList, PageLinks, SectionTitle, Unavailable } from "@/components/ipo/report/shared";

function CaseList({ cases }: { cases: LegalCase[] }) {
  if (!cases.length) return <p className="text-sm text-muted-foreground">None listed.</p>;
  return (
    <ul className="flex flex-col divide-y rounded-md border text-sm">
      {cases.map((c, i) => (
        <li key={i} className="flex gap-3 px-3 py-2">
          <div className="min-w-0 flex-1">
            <p>{c.summary}</p>
            <p className="text-xs text-muted-foreground">
              {CASE_TYPES[c.type]} · {PARTIES[c.party] ?? c.party}
              {c.count > 1 && ` · ${c.count} cases`}
              {c.total_row && " · table total"}
              {c.in_total_row && " · counted in the table total"}
            </p>
          </div>
          <span className="shrink-0 text-right tabular-nums">
            {c.amount_million === null ? "–" : formatMillion(c.amount_million)}
          </span>
          <PageLinks pages={[c.page]} />
        </li>
      ))}
    </ul>
  );
}

export function LegalDetails({ legal }: { legal: LegalResult | null }) {
  const summary = legal?.summary;
  const approvals = legal?.approvals;
  if (!summary && !approvals) return <Unavailable what="legal analysis" output={legal} />;
  const cases = legal?.cases ?? [];

  return (
    <div className="flex flex-col gap-6">
      {summary && (
        <section className="flex flex-col gap-3">
          <SectionTitle>Proceedings against the company, its subsidiaries, promoters and directors</SectionTitle>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 text-right font-medium">Cases</th>
                  <th className="px-3 py-2 text-right font-medium">Amount involved</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {Object.entries(summary.against_by_type).map(([type, { count, amount_million }]) => (
                  <tr key={type}>
                    <td className="px-3 py-1.5">{CASE_TYPES[type] ?? type}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{count}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{count ? formatMillion(amount_million) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-sm">
            Quantified claims total <span className="font-medium">{formatMillion(summary.total_amount_against_million)}</span>
            {summary.amount_pct_of_net_worth !== null &&
              `, ${summary.amount_pct_of_net_worth}% of net worth (${formatMillion(summary.net_worth_million)})`}
            . Cases the company and its people filed themselves: {summary.filed_by_parties}.
          </p>
          <FlagList flags={legal?.flags ?? []} />
        </section>
      )}

      {cases.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-2">
          <section className="flex flex-col gap-2">
            <SectionTitle>Against them</SectionTitle>
            <CaseList cases={cases.filter((c) => c.against_party)} />
          </section>
          <section className="flex flex-col gap-2">
            <SectionTitle>Filed by them</SectionTitle>
            <CaseList cases={cases.filter((c) => !c.against_party)} />
          </section>
        </div>
      )}

      {approvals && (
        <section className="flex flex-col gap-2 border-t pt-5 text-sm">
          <SectionTitle>
            Government and other approvals <PageLinks pages={approvals.pages} />
          </SectionTitle>
          <p>
            {approvals.all_material_obtained === true
              ? "The document says the company holds all material approvals, apart from any listed below."
              : approvals.all_material_obtained === false
                ? "The document says some material approvals are missing."
                : "The document doesn't say whether all material approvals are held."}
          </p>
          <p>
            <span className="text-muted-foreground">Applied for, not yet received: </span>
            {approvals.pending.length ? approvals.pending.join("; ") : "none"}
          </p>
          <p>
            <span className="text-muted-foreground">Required but not yet applied for: </span>
            {approvals.not_applied.length ? approvals.not_applied.join("; ") : "none"}
          </p>
        </section>
      )}

      <AgentFooter output={legal} />
    </div>
  );
}
