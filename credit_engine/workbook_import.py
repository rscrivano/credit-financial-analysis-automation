"""Read a workbook built on Ryan's credit spread template into PeriodData objects.

This is both the regression-test loader and a real feature: an analyst can drop
in an existing spread (e.g., a private company spread by hand) and get the
app's analysis on it.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import openpyxl

from .models import PeriodData

INPUT_COLUMNS = ["C", "E", "G", "I", "K", "M", "O", "Q"]
# Inputs column -> the matching block on the Credit Rating sheet (ratio, rating, weight, score)
RATING_BLOCKS = {"C": ("C", "D", "F"), "E": ("G", "H", "J"), "G": ("K", "L", "N"),
                 "I": ("O", "P", "R"), "K": ("S", "T", "V"), "M": ("W", "X", "Z"),
                 "O": ("AA", "AB", "AD")}
RATIO_ROWS = {"ebitda_margin": 10, "ebit_coverage": 11, "ebitda_coverage": 12, "ffo_to_debt": 14,
              "fcf_to_debt": 15, "dcf_to_debt": 16, "debt_to_ebitda": 18, "debt_to_capital": 19,
              "return_on_capital": 20}

FIELD_ROWS = {
    "revenue": 7, "cogs": 8, "sga": 10, "other_opex": 11, "amortization": 13, "depreciation": 14,
    "operating_income": 17, "interest_expense": 18, "tax_expense": 19, "net_income": 21,
    "nonrecurring": 22, "amort_deferred_revenue": 24, "cfo": 26, "capex": 27, "deferred_taxes": 28,
    "other_noncash": 29, "dividends": 30, "total_assets": 32, "cash": 33, "receivables": 34,
    "total_current_assets": 36, "fixed_assets": 37, "goodwill": 38, "other_intangibles": 39,
    "total_liabilities": 41, "st_debt": 42, "accounts_payable": 43, "total_current_liabilities": 45,
    "deferred_tax_liability": 46, "lt_debt": 48,
}
# Rows added below the original template by tools/make_blank_template.py
EXTRA_ROWS = {"total_equity": 101, "inventory": 102, "operating_lease_liabilities": 103, "operating_lease_cost": 104}
FLOATING_ROW, SECTOR_CELL, AGENCY_CELL = 105, "C107", "C108"


def _kind(months: int) -> str:
    return "Annual" if months == 12 else ("Quarter" if months == 3 else "YTD")


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _as_date(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def template_meta(path: str) -> dict:
    """Sector, agency rating and floating-rate share entered in the template (blank-template rows)."""
    ws = openpyxl.load_workbook(path, data_only=True)["Inputs"]
    fl = next((_num(ws[f"{c}{FLOATING_ROW}"].value) for c in INPUT_COLUMNS if _num(ws[f"{c}{FLOATING_ROW}"].value) is not None), None)
    return {"sector_name": (ws[SECTOR_CELL].value or "").strip() if isinstance(ws[SECTOR_CELL].value, str) else "",
            "agency_rating": (str(ws[AGENCY_CELL].value).strip() if ws[AGENCY_CELL].value else ""),
            "floating_rate_share": None if fl is None else (fl / 100 if fl > 1 else fl)}


def load_template_workbook(path: str) -> tuple[str, list[PeriodData]]:
    """Returns (company name, periods in the workbook's column order, left to right)."""
    ws = openpyxl.load_workbook(path, data_only=True)["Inputs"]
    company = ws["B2"].value or "Unknown company"
    if company == "Company name":
        company = "Unnamed company"
    periods = []
    for col in INPUT_COLUMNS:
        end = _as_date(ws[f"{col}4"].value)
        if end is None:
            continue
        months = int(ws[f"{col}5"].value or 12)
        raw_kind = (ws[f"{col}6"].value or "").strip() if isinstance(ws[f"{col}6"].value, str) else ""
        kind = _kind(months)
        label = {"YTD": f"{months}M YTD {end:%b-%Y}", "Quarter": f"Q {end:%b-%Y}",
                 "Annual": f"FY {end:%Y}"}[kind]
        p = PeriodData(label=label, period_end=end, months=months, kind=kind, quality=raw_kind,
                       fx_avg=_num(ws[f"{col}51"].value) or 1.0)
        for name, row in {**FIELD_ROWS, **EXTRA_ROWS}.items():
            setattr(p, name, _num(ws[f"{col}{row}"].value))
            p.sources[name] = [f"{path.split('/')[-1].split(chr(92))[-1]} Inputs!{col}{row}"]
        p.sources["_column"] = col
        periods.append(p)
    return company, periods


def read_template_outputs(path: str) -> dict[str, dict]:
    """The workbook's own Credit Rating results, keyed by Inputs column (for regression tests)."""
    ws = openpyxl.load_workbook(path, data_only=True)["Credit Rating"]
    out = {}
    for col, (rc, nc, sc) in RATING_BLOCKS.items():
        out[col] = {
            "ratios": {k: ws[f"{rc}{r}"].value for k, r in RATIO_ROWS.items()},
            "notches": {k: ws[f"{nc}{r}"].value for k, r in RATIO_ROWS.items()},
            "score": ws[f"{sc}21"].value,
            "rating": ws[f"{nc}21"].value,
        }
    return out
