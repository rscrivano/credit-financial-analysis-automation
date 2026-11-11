"""Sample 'company's own format' statements built from Southwest's SEC numbers (for tests and the demo).

    python tools/make_sample_company_excel.py
Different labels from the template, three sheets, expenses shown negative, years as column headers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from credit_engine.xbrl_map import build_spread  # noqa: E402

OUT = ROOT / "data" / "samples" / "sample_private_company_statements.xlsx"
IS = [("Net sales", "revenue", 1), ("Depreciation & amortization", "depreciation", -1), ("Income from operations", "operating_income", 1),
      ("Interest expense, net", "interest_expense", -1), ("Provision for income taxes", "tax_expense", -1), ("Net income", "net_income", 1),
      ("Rent expense", "operating_lease_cost", -1)]
BS = [("Cash and cash equivalents", "cash", 1), ("Trade receivables", "receivables", 1), ("Inventories", "inventory", 1),
      ("Total current assets", "total_current_assets", 1), ("Property and equipment, net", "fixed_assets", 1), ("Goodwill", "goodwill", 1),
      ("Intangible assets, net", "other_intangibles", 1), ("Total assets", "total_assets", 1), ("Accounts payable", "accounts_payable", 1),
      ("Current maturities of long-term debt", "st_debt", 1), ("Total current liabilities", "total_current_liabilities", 1),
      ("Long-term debt, net of current portion", "lt_debt", 1), ("Deferred tax liabilities", "deferred_tax_liability", 1),
      ("Operating lease liabilities", "operating_lease_liabilities", 1), ("Total liabilities", "total_liabilities", 1),
      ("Total stockholders' equity", "total_equity", 1)]
CF = [("Net cash provided by operating activities", "cfo", 1), ("Deferred income taxes", "deferred_taxes", 1),
      ("Capital expenditures", "capex", 1), ("Dividends paid", "dividends", 1)]


def main():
    facts = json.loads((ROOT / "data" / "sample" / "CIK0000092380.json").read_text(encoding="utf-8"))
    sp = build_spread(facts)
    fys = sorted((p for p in sp.periods if p.kind == "Annual"), key=lambda p: p.period_end, reverse=True)[:2]
    opening = next(o for o in sp.periods + sp.openings if o.period_end.year == fys[-1].period_end.year - 1
                   and o.period_end.month == 12 and o.total_assets)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, lines, cols in (("Income Statement", IS, fys), ("Balance Sheet", BS, fys + [opening]), ("Cash Flow", CF, fys)):
        ws = wb.create_sheet(title)
        ws["A1"] = "Sample Airline Holdings LLC (illustrative; built from public data)"
        ws["A2"] = "US$ millions"
        for j, p in enumerate(cols):
            ws.cell(3, j + 2, f"FY{p.period_end:%Y}")
        for i, (label, field, sign) in enumerate(lines, start=4):
            ws.cell(i, 1, label)
            for j, p in enumerate(cols):
                v = getattr(p, field)
                ws.cell(i, j + 2, None if v is None else round(v * sign if field not in ("capex", "dividends") else v, 1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
