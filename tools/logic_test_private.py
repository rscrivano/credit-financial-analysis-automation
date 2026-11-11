"""Private-path logic test: run public companies through the private upload path.

    python tools/logic_test_private.py LUV ULCC DAL > ../docs/logic_test_private.md

For each ticker: SEC data -> written into the blank template as if it were a private company
(no ticker, no filing) -> uploaded through run_workbook. Every period both paths share must
get the same ratings ("the finances are the finances"). Then a copy with equity mis-keyed by
5% must trigger the balance-sheet red flag. No AI used (use_ai=False).
"""
from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from credit_engine.edgar import company_facts, lookup  # noqa: E402
from credit_engine.macro import benchmarks  # noqa: E402
from credit_engine.pipeline import run, run_workbook  # noqa: E402
from credit_engine.workbook_export import write_template  # noqa: E402
from credit_engine.xbrl_map import build_spread  # noqa: E402


def compare(ticker: str, tmp: Path) -> dict:
    t, cik, _ = lookup(ticker)
    sp = build_spread(company_facts(cik)[0])
    public = run(t, use_ai=False)
    sector_name = benchmarks()["sectors"].get(public["sector_key"] or "", {}).get("name", "")
    wb = write_template(f"Private Co (from {t} public data)", sp.periods, sp.openings, tmp / f"{t}.xlsx", sector_name)
    private = run_workbook(str(wb), use_ai=False)
    pub = {p["label"]: p for p in public["periods"]}
    rows, ok = [], True
    for p in private["periods"]:
        q = pub.get(p["label"])
        if not q:
            continue
        same = all(p[b]["rating"] == q[b]["rating"] and (p[b]["score"] is None) == (q[b]["score"] is None)
                   and (p[b]["score"] is None or abs(p[b]["score"] - q[b]["score"]) < 1e-9)
                   for b in ("reported", "lease_adjusted"))
        ok &= same
        rows.append((p["label"], q["reported"]["rating"], p["reported"]["rating"], q["lease_adjusted"]["rating"],
                     p["lease_adjusted"]["rating"], "Match" if same else "DIFFERENT"))

    # Mis-key equity in the latest fiscal year by +5% -> balance-sheet red flag expected
    fy = max((p for p in sp.periods if p.kind == "Annual"), key=lambda p: p.period_end)
    bad = [replace(p, total_equity=p.total_equity * 1.05) if p is fy and p.total_equity else p for p in sp.periods]
    wb2 = write_template(f"Private Co (from {t}, equity mis-keyed)", bad, sp.openings, tmp / f"{t}_bad.xlsx", sector_name)
    flagged = run_workbook(str(wb2), use_ai=False)
    red = [f for f in flagged["integrity"] if f["severity"] == "red" and "balance" in f["title"].lower()]
    clean_red = [f for f in private["integrity"] if f["severity"] == "red"]
    return {"ticker": t, "company": public["company"], "rows": rows, "ok": ok, "red": red, "clean_red": clean_red,
            "sector": sector_name, "public_sp": public["sp_anchor"].get("anchor"),
            "private_sp": private["sp_anchor"].get("anchor")}


def main(tickers):
    print("# Logic test: public companies run through the private-company path\n")
    print("Each company's SEC financials were written into the blank private template (no ticker, no filing) "
          "and uploaded. Ratings must match the public path for every shared period. A copy with "
          "shareholders' equity mis-keyed by +5% in the latest fiscal year must raise the balance-sheet red flag.\n")
    allok = True
    with tempfile.TemporaryDirectory() as d:
        for t in tickers:
            r = compare(t, Path(d))
            allok &= r["ok"] and bool(r["red"]) and not r["clean_red"]
            print(f"## {r['company']} ({r['ticker']}) — sector: {r['sector']}\n")
            print("| Period | Public: Reported | Private: Reported | Public: Lease-adj | Private: Lease-adj | |\n|---|---|---|---|---|---|")
            for row in r["rows"]:
                print("| " + " | ".join(str(x) for x in row) + " |")
            print(f"\nS&P-style anchor: public {r['public_sp']}, private {r['private_sp']}.  ")
            print(f"Clean upload red flags: {len(r['clean_red'])}.  ")
            print("Mis-keyed equity: " + (f"**red flag raised**: {r['red'][0]['detail']}" if r["red"] else "**NOT flagged**") + "\n")
    print(f"**Result: {'PASS' if allok else 'FAIL'}**")


if __name__ == "__main__":
    main(sys.argv[1:] or ["LUV", "ULCC", "DAL"])
