"""Command-line run: python -m credit_engine.cli LUV

Pulls SEC data (or the offline sample), builds the spread, and prints the scorecard.
"""
from __future__ import annotations

import argparse
import sys

from .edgar import EdgarError, company_facts, lookup
from .engine import analyze
from .xbrl_map import build_spread


def _fmt_ratio(r) -> str:
    if r.value is None:
        return ""
    return f"{r.value:.1%}" if "(%)" in r.name else f"{r.value:.2f}x"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Credit/Financial Analysis Automation: implied credit rating from SEC filings")
    ap.add_argument("ticker")
    ap.add_argument("--years", type=int, default=3, help="fiscal years to include (default 3)")
    ap.add_argument("--quarters", type=int, default=4, help="quarters to include (default 4)")
    args = ap.parse_args(argv)
    try:
        ticker, cik, title = lookup(args.ticker)
        facts, source = company_facts(cik)
    except EdgarError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    sp = build_spread(facts, n_years=args.years, n_quarters=args.quarters)
    res = analyze(sp.company, sp.periods, openings=sp.openings)
    print(f"{sp.company} ({ticker}, CIK {cik}) — SEC data: {source}")
    for n in sp.notes + res.notes:
        print(f"  note: {n}")
    print(f"\n{'Period':18}{'EBITDA':>10}{'Reported':>12}{'Lease-adj':>12}")
    for r in res.periods:
        e = "" if r.ebitda.ebitda is None else f"{r.ebitda.ebitda:,.0f}"
        print(f"{r.label:18}{e:>10}{r.reported.rating or 'n/a':>12}{r.lease_adjusted.rating or 'n/a':>12}")
    p = res.primary
    for basis in (p.reported, p.lease_adjusted):
        print(f"\n{basis.basis} basis — {p.label}: {basis.rating or 'no rating'}"
              + (f" (score {basis.score:.2f})" if basis.score is not None else "")
              + (f"  [{basis.message}]" if basis.message else ""))
        for x in basis.ratios:
            print(f"  {x.name:38}{_fmt_ratio(x):>10}  {x.notch or '':5} {x.message} {x.note}".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
