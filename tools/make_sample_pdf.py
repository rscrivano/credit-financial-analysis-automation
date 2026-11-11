"""Illustrative private-company PDF (reviewed statements + notes) for tests and the demo.

    pip install fpdf2   (dev only)
    python tools/make_sample_pdf.py

Figures are Southwest Airlines' public FY2025/FY2024 numbers presented in thousands, under a
fictional name and clearly marked illustrative. FY2024 equity is deliberately mis-keyed so the
balance-sheet red flag can be demonstrated. Note text is written for the sample, not copied.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from credit_engine.xbrl_map import build_spread  # noqa: E402

OUT = ROOT / "data" / "samples" / "sample_private_reviewed_statements.pdf"


def main():
    sp = build_spread(json.loads((ROOT / "data" / "sample" / "CIK0000092380.json").read_text(encoding="utf-8")))
    a, b = sorted((p for p in sp.periods if p.kind == "Annual"), key=lambda p: p.period_end, reverse=True)[:2]
    k = lambda v: f"({abs(v) * 1000:,.0f})" if v < 0 else f"{v * 1000:,.0f}"  # noqa: E731  thousands
    pdf = FPDF()
    pdf.set_auto_page_break(True, 15)

    def page(title):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, "Sample Airline Holdings LLC", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, "ILLUSTRATIVE SAMPLE - built from public data for software testing", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)

    def para(t):
        pdf.multi_cell(0, 5, t)
        pdf.ln(2)

    def table(rows):
        pdf.cell(110, 6, "(in thousands of U.S. dollars)")
        pdf.cell(40, 6, f"{a.period_end:%Y}", align="R")
        pdf.cell(40, 6, f"{b.period_end:%Y}", align="R", new_x="LMARGIN", new_y="NEXT")
        for label, va, vb in rows:
            pdf.cell(110, 6, label)
            pdf.cell(40, 6, k(va), align="R")
            pdf.cell(40, 6, k(vb), align="R", new_x="LMARGIN", new_y="NEXT")

    page("Independent Accountant's Review Report")
    para("We have reviewed the accompanying financial statements of Sample Airline Holdings LLC, which comprise the "
         "balance sheets as of December 31, 2025 and 2024, and the related statements of operations and cash flows for "
         "the years then ended. A review is substantially less in scope than an audit, and accordingly we do not "
         "express an opinion. Based on our review, we are not aware of any material modifications that should be made.")
    page("Statements of Operations")
    table([("Net sales", a.revenue, b.revenue), ("Depreciation and amortization", a.depreciation, b.depreciation),
           ("Income from operations", a.operating_income, b.operating_income),
           ("Interest expense (income), net", a.interest_expense, b.interest_expense),
           ("Provision for income taxes", a.tax_expense, b.tax_expense), ("Net income", a.net_income, b.net_income)])
    page("Balance Sheets")
    eq_b = b.total_equity + 900  # deliberate keying error (FY2024 equity off by $900m)
    table([("Cash and cash equivalents", a.cash, b.cash), ("Accounts receivable", a.receivables, b.receivables),
           ("Total current assets", a.total_current_assets, b.total_current_assets),
           ("Property and equipment, net", a.fixed_assets, b.fixed_assets), ("Goodwill", a.goodwill, b.goodwill),
           ("Total assets", a.total_assets, b.total_assets), ("Accounts payable", a.accounts_payable, b.accounts_payable),
           ("Current maturities of long-term debt", a.st_debt, b.st_debt),
           ("Total current liabilities", a.total_current_liabilities, b.total_current_liabilities),
           ("Long-term debt, net of current portion", a.lt_debt, b.lt_debt),
           ("Operating lease liabilities", a.operating_lease_liabilities, b.operating_lease_liabilities),
           ("Total liabilities", a.total_liabilities, b.total_liabilities), ("Total members' equity", a.total_equity, eq_b)])
    page("Statements of Cash Flows")
    table([("Net cash provided by operating activities", a.cfo, b.cfo), ("Capital expenditures", a.capex, b.capex),
           ("Distributions to members", a.dividends, b.dividends)])
    page("Notes to the Financial Statements")
    para("Note 6 - Leases. The Company leases aircraft and airport facilities under operating leases accounted for "
         "under ASC 842. Operating lease liabilities were $1,080 million at December 31, 2025. Lease cost for 2025 "
         "was $346 million.")
    para("Note 7 - Debt. The Company's term loan and revolving credit facility contain a financial covenant requiring a "
         "fixed charge coverage ratio of at least 1.25 to 1.00, tested quarterly. The Company was in compliance at "
         "December 31, 2025.")
    para("Note 8 - Commitments. The Company has firm purchase commitments for 86 aircraft scheduled for delivery in "
         "2026, with remaining payments of approximately $4.2 billion. These commitments are not recorded on the "
         "balance sheet.")
    para("Note 9 - Contingencies. The Company is a defendant in a class action relating to employee leave policies. "
         "A settlement including an $18.5 million settlement fund has been preliminarily approved.")
    para("Note 10 - Related party transactions. The Company paid management fees of $12 million in 2025 to an "
         "affiliate of its majority member under a services agreement.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
