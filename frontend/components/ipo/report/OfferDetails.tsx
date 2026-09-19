"use client";

import { formatCount, formatMillion } from "@/lib/format";
import type { OfferResult } from "@/lib/ipo";
import { AgentFooter, FlagList, PageLinks, SectionTitle, Unavailable } from "@/components/ipo/report/shared";

const pct = (value: number | null | undefined) => (value === null || value === undefined ? "–" : `${value}%`);
const plain = (value: number | null | undefined) => (value === null || value === undefined ? "–" : String(value));

export function OfferDetails({ offer }: { offer: OfferResult | null }) {
  const structure = offer?.structure;
  const metrics = offer?.metrics ?? {};
  const peers = offer?.peers;
  if (!structure && !peers) return <Unavailable what="offer analysis" output={offer} />;

  return (
    <div className="flex flex-col gap-6">
      {structure && (
        <section className="flex flex-col gap-3">
          <SectionTitle>
            The offer <PageLinks pages={structure.pages} />
          </SectionTitle>
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[14rem_1fr]">
            <dt className="text-muted-foreground">Fresh issue (money for the company)</dt>
            <dd>
              {metrics.fresh_issue_million ? formatMillion(metrics.fresh_issue_million) : "Amount not yet fixed"}
              {structure.fresh_issue_shares ? ` · ${formatCount(structure.fresh_issue_shares)} shares` : ""}
            </dd>
            <dt className="text-muted-foreground">Offer for sale (money for sellers)</dt>
            <dd>
              {structure.offer_for_sale_shares
                ? `${formatCount(structure.offer_for_sale_shares)} shares, ${pct(metrics.offer_for_sale_pct_of_shares_offered)} of the shares offered`
                : "None"}
            </dd>
            {structure.selling_shareholders.length > 0 && (
              <>
                <dt className="text-muted-foreground">Selling shareholders</dt>
                <dd>
                  {structure.selling_shareholders.join(", ")}
                  {structure.promoters_selling && " (promoter group)"}
                </dd>
              </>
            )}
            <dt className="text-muted-foreground">Shares before → after</dt>
            <dd>
              {formatCount(structure.shares_before_offer)} → {formatCount(structure.shares_after_offer)}
              {metrics.dilution_pct !== null && metrics.dilution_pct !== undefined &&
                ` (new shares are ${metrics.dilution_pct}% of the total)`}
            </dd>
          </dl>

          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium">What the fresh issue pays for</th>
                  <th className="px-3 py-2 text-right font-medium whitespace-nowrap">₹ {structure.amount_unit}</th>
                  <th className="px-3 py-2 font-medium">Pages</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {structure.objects.map((use, i) => (
                  <tr key={i}>
                    <td className="px-3 py-1.5">{use.purpose}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {use.amount === null ? "[●]" : use.amount.toLocaleString("en-IN")}
                    </td>
                    <td className="px-3 py-1.5">
                      <PageLinks pages={use.pages} />
                    </td>
                  </tr>
                ))}
                <tr>
                  <td className="px-3 py-1.5">General corporate purposes (capped at 25% of the gross proceeds)</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {structure.general_corporate_purposes_amount?.toLocaleString("en-IN") ?? "[●]"}
                  </td>
                  <td />
                </tr>
              </tbody>
            </table>
          </div>
          {metrics.unspecified_pct_of_fresh_issue !== null && metrics.unspecified_pct_of_fresh_issue !== undefined && (
            <p className="text-sm text-muted-foreground">
              {metrics.specified_pct_of_fresh_issue}% of the fresh issue is tied to stated uses; up to{" "}
              {metrics.unspecified_pct_of_fresh_issue}% goes to general corporate purposes and issue expenses.
            </p>
          )}
          <FlagList flags={offer?.flags ?? []} />
        </section>
      )}

      {peers && (
        <section className="flex flex-col gap-3 border-t pt-5">
          <SectionTitle>
            Listed peers, as the document compares them <PageLinks pages={peers.pages} />
          </SectionTitle>
          {peers.peers.length > 0 && (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-left">
                  <tr>
                    <th className="px-3 py-2 font-medium">Company</th>
                    <th className="px-3 py-2 text-right font-medium">P/E</th>
                    <th className="px-3 py-2 text-right font-medium">EPS (₹)</th>
                    <th className="px-3 py-2 text-right font-medium">Return on net worth</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {peers.peers.map((peer) => (
                    <tr key={peer.name}>
                      <td className="px-3 py-1.5">{peer.name}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{plain(peer.pe)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{plain(peer.eps)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{pct(peer.ronw_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-sm">
            Peer P/E {plain(peers.peer_pe_low)} to {plain(peers.peer_pe_high)}, average {plain(peers.peer_pe_average)}.
            The company&apos;s return on net worth: {pct(peers.company_ronw_pct)}; net asset value per share: ₹
            {plain(peers.company_nav_per_share)}.
          </p>
          <p className="text-xs text-muted-foreground">
            There&apos;s no P/E at the issue price: the price band is announced after the DRHP and RHP are filed.
            A negative P/E means the peer made a loss.
          </p>
        </section>
      )}

      <AgentFooter output={offer} />
    </div>
  );
}
