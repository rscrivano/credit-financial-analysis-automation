"""Compare the app's automatic SEC spread with Ryan's hand-built workbook spreads.

    python tools/compare_edgar_to_workbook.py > ../docs/validation_edgar_vs_workbook.md

Uses cached/sample SEC data when live access is unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from credit_engine.edgar import company_facts, lookup  # noqa: E402
from credit_engine.workbook_import import load_template_workbook  # noqa: E402
from credit_engine.xbrl_map import build_spread  # noqa: E402

FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
CASES = [("LUV", "southwest_template.xlsx"), ("ULCC", "frontier_template.xlsx")]
LINES = [("Revenue", "revenue"), ("Operating income", "operating_income"), ("D&A", "depreciation"),
         ("Interest expense (net)", "interest_expense"), ("Net income", "net_income"),
         ("Operating cash flow", "cfo"), ("Capex (net)", "capex"), ("Total assets", "total_assets"),
         ("Total liabilities", "total_liabilities"), ("Cash & ST investments", "cash"),
         ("Short-term debt", "st_debt"), ("Long-term debt", "lt_debt")]


def fmt(v):
    return "—" if v is None else f"{v:,.0f}"


def main():
    print("# Validation: automatic SEC spread vs. Ryan's hand-built workbooks\n")
    print("US$ millions. 'Match' = within 0.5. Differences are explained below each table.\n")
    total = matched = 0
    for ticker, wb in CASES:
        _, cik, _ = lookup(ticker)
        facts, source = company_facts(cik)
        sp = build_spread(facts)
        company, wb_periods = load_template_workbook(str(FIX / wb))
        auto = {p.label: p for p in sp.periods}
        print(f"## {company} ({ticker}) — SEC data source: {source}\n")
        for label in ("9M YTD Sep-2026", "FY 2025"):
            a = auto.get(label)
            w = next((p for p in wb_periods if p.label == label), None)
            if not a or not w:
                continue
            print(f"### {label}\n\n| Line | Workbook | App (SEC) | |\n|---|---:|---:|---|")
            for name, f in LINES:
                wv, av = getattr(w, f), getattr(a, f)
                ok = wv is not None and av is not None and abs(wv - av) < 0.5
                total += 1
                matched += ok
                print(f"| {name} | {fmt(wv)} | {fmt(av)} | {'Match' if ok else 'Differs'} |")
            print()
    print(f"**{matched} of {total} line items match exactly.**\n")


if __name__ == "__main__":
    main()
