"""Write a spread into the blank private-company template (Ryan's layout).

Used for the private-path logic test (public SEC data entered as if it were a private
company) and as a feature: download any analyzed company as a template workbook.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import openpyxl

from .config import REPO_ROOT
from .models import PeriodData
from .workbook_import import AGENCY_CELL, EXTRA_ROWS, FIELD_ROWS, FLOATING_ROW, SECTOR_CELL

BLANK = REPO_ROOT / "data" / "templates" / "private_company_template.xlsx"
STATEMENT = {"YTD": lambda m: f"{m} Mo. YTD", "Quarter": lambda m: "Quarterly", "Annual": lambda m: "Audited"}


def layout(periods: list[PeriodData], openings: list[PeriodData]) -> dict[str, PeriodData]:
    """Template columns: C = latest YTD, E/G/I = latest 3 quarters, K/M/O = latest 3 fiscal years,
    Q = the balance sheet before the oldest fiscal year (its opening balance)."""
    by = lambda kind: sorted((p for p in periods if p.kind == kind), key=lambda p: p.period_end, reverse=True)  # noqa: E731
    cols: dict[str, PeriodData] = {}
    ytd = by("YTD")
    if ytd:
        cols["C"] = ytd[0]
    for c, q in zip("EGI", by("Quarter")):
        cols[c] = q
    fys = by("Annual")
    for c, fy in zip("KMO", fys):
        cols[c] = fy
    if len(fys) >= 4:
        cols["Q"] = fys[3]
    elif fys:
        oldest = fys[min(2, len(fys) - 1)].period_end
        before = [o for o in openings if o.period_end < oldest]
        if before:
            cols["Q"] = max(before, key=lambda o: o.period_end)
    return cols


def write_template(company: str, periods: list[PeriodData], openings: list[PeriodData], path: Path | str,
                   sector_name: str = "", agency_rating: str = "", floating_pct: Optional[float] = None) -> Path:
    wb = openpyxl.load_workbook(BLANK)
    ws = wb["Inputs"]
    ws["B2"] = company
    for col, p in layout(periods, openings).items():
        ws[f"{col}4"] = p.period_end
        ws[f"{col}5"] = p.months or 12
        ws[f"{col}6"] = STATEMENT.get(p.kind, lambda m: "Audited")(p.months)
        for field, row in {**FIELD_ROWS, **EXTRA_ROWS}.items():
            v = getattr(p, field)
            ws[f"{col}{row}"] = v
    if floating_pct is not None:
        ws[f"C{FLOATING_ROW}"] = floating_pct
    ws[SECTOR_CELL] = sector_name or None
    ws[AGENCY_CELL] = agency_rating or None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
