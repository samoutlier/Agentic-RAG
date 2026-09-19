"""Try the full IPO analysis on one document, from the terminal.

    python try_agents.py "../samples/Jindal Supreme RHP.PDF"

Runs the LangGraph graph (parse → risk + financial + legal + index in
parallel → business + offer → score → synthesis), prints progress as it
happens, then the results. Uses ~45k Groq tokens across three models. A
new document's index takes a few minutes to build.
"""
import sys
import time

from app.agents.graph import build_graph

path = sys.argv[1] if len(sys.argv) > 1 else "../samples/Jindal Supreme RHP.PDF"
started, state = time.time(), {}
for mode, chunk in build_graph().stream({"file_path": path}, stream_mode=["custom", "values"]):
    if mode == "custom":
        print(f"{time.time() - started:6.1f}s  [{chunk['agent']}] {chunk['message']}")
    else:
        state = chunk

risk, fin = state["risk"], state["financial"]
counts = risk.get("counts", {})
print("\n=== RISK REGISTER", risk["status"], counts.get("by_severity", ""), "average score", counts.get("average_score"))
for r in risk.get("register", [])[:15]:
    print(f"  #{r['rank']:2d} score {r['score']} {r['category']:16s} p{r['page']:<4} {r['headline']}")

print("\n=== FINANCIAL HEALTH", fin["status"])
for s in fin.get("scorecard", []):
    print(f"  {s['dimension']:16s} {s['signal']:9s} {s['reason']}")
for f in fin.get("flags", []):
    print(f"  [{f['severity']}] {f['message']}")
a = fin.get("assessment")
if a:
    print("\n ", a["summary"])
    for p in a["strengths"]:
        print("  +", p["point"])
    for p in a["concerns"]:
        print("  -", p["point"])
biz, offer = state["business"], state["offer"]
print("\n=== BUSINESS & PROMOTERS", biz["status"])
profile = biz.get("profile")
if profile:
    print(" ", profile["description"]["text"], profile["description"]["pages"])
    for c in profile["strengths"]:
        print("  +", c["text"], c["pages"])
    for c in profile["weaknesses"]:
        print("  -", c["text"], c["pages"])
promoters = biz.get("promoters")
if promoters:
    print("  promoters:", ", ".join(f"{p['name']} ({p['role']})" for p in promoters["people"]))
    print("  holding:", promoters["holding_signal"]["reason"], "| pledged:", promoters["shares_pledged"],
          promoters["pledge_source"]["pages"])
    for c in promoters["governance_concerns"]:
        print("  governance:", c["text"], c["pages"])

print("\n=== OFFER & USE OF PROCEEDS", offer["status"])
structure = offer.get("structure")
if structure:
    for o in structure["objects"]:
        print(f"  use: {o['purpose']} = {o['amount']} {structure['amount_unit']} {o['pages']}")
    for f in offer["flags"]:
        print(f"  [{f['severity']}] {f['message']}")
peers = offer.get("peers")
if peers:
    print("  peers:", ", ".join(f"{p['name']} P/E {p['pe']}" for p in peers["peers"]),
          f"| peer P/E {peers['peer_pe_low']}-{peers['peer_pe_high']}, average {peers['peer_pe_average']}")

legal = state["legal"]
print("\n=== LEGAL & APPROVALS", legal["status"])
for case in legal.get("cases", []):
    if case["against_party"]:
        amount = f"₹{case['amount_million']:,.2f} m" if case["amount_million"] is not None else "amount not stated"
        print(f"  {case['type']:17s} against {case['party']:12s} {amount} p{case['page']}: {case['summary']}")
for f in legal.get("flags", []):
    print(f"  [{f['severity']}] {f['message']}")
approvals = legal.get("approvals") or {}
print("  approvals pending:", approvals.get("pending") or "none", "| not applied for:", approvals.get("not_applied") or "none")

score, report = state["score"], state["report"]
print(f"\n=== SCORE {score['score']:g}/100: {score['rating']} ({score['risk_reward']['quadrant']})")
for reason in score["knockouts"]:
    print("  knockout (caps the rating at Neutral):", reason)
for p in score["parts"]:
    print(f"  {p['label']:22s} {p['points']:>4g}/{p['max_points']:g}  {'; '.join(p['reasons'])}")

print("\n=== REPORT", report["status"])
print(" ", report.get("executive_summary", ""))
for p in report.get("bull_case", []):
    print("  +", p["text"], "pages", p["pages"])
for p in report.get("bear_case", []):
    print("  -", p["text"], "pages", p["pages"])
for c in report.get("check_before_investing", []):
    print("  ?", c)
print("\n ", report["disclaimer"])

for agent in (risk, fin, biz, offer, legal, report):
    for w in agent.get("warnings", []):
        print("  warning:", w)
