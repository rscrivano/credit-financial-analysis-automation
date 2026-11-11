"""Make the blank private-company input template from Ryan's credit spread workbook.

    python tools/make_blank_template.py

Starts from the Southwest working example, clears every input value (company,
dates, months, statement type, all financial lines) and keeps Ryan's formulas,
Summary and Credit Rating sheets. Adds a short block of extra inputs the app
uses (equity for the balance-sheet check, inventory, leases, floating-rate share,
sector, agency rating) and an Instructions sheet.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from credit_engine.workbook_import import (AGENCY_CELL, EXTRA_ROWS, FIELD_ROWS, FLOATING_ROW,  # noqa: E402
                                           INPUT_COLUMNS, SECTOR_CELL)

SRC = ROOT / "tests" / "fixtures" / "southwest_template.xlsx"
OUT = ROOT / "data" / "templates" / "private_company_template.xlsx"
INPUT_ROWS = sorted(set(FIELD_ROWS.values()) | {4, 5, 6, 52})
STATEMENT_TYPES = "Audited,Reviewed,Compiled,Management,Quarterly,9 Mo. YTD,6 Mo. YTD"
PINK = PatternFill("solid", fgColor="FFE3F0")


def main():
    wb = openpyxl.load_workbook(SRC)
    ws = wb["Inputs"]
    ws["B2"] = "Company name"
    for r in INPUT_ROWS:
        for c in INPUT_COLUMNS:
            ws[f"{c}{r}"] = None
            ws[f"{c}{r}"].fill = PINK
    for c in INPUT_COLUMNS:  # FX: blank means 1.0 (US$)
        ws[f"{c}52"] = 1

    ws["B100"] = "Additional inputs (Credit/Financial Analysis Automation)"
    ws["B100"].font = Font(bold=True)
    labels = {"total_equity": "Total Shareholders' Equity (as reported)", "inventory": "Inventory",
              "operating_lease_liabilities": "Operating lease liabilities (current + non-current)",
              "operating_lease_cost": "Operating lease cost (period)"}
    for f, row in EXTRA_ROWS.items():
        ws[f"B{row}"] = labels[f]
        for c in INPUT_COLUMNS:
            ws[f"{c}{row}"].fill = PINK
    ws[f"B{FLOATING_ROW}"] = "Floating-rate share of debt (%)"
    ws[f"C{FLOATING_ROW}"].fill = PINK
    ws["B107"], ws["B108"] = "Sector", "Agency rating, if any (S&P/Moody's)"
    ws[SECTOR_CELL].fill = PINK
    ws[AGENCY_CELL].fill = PINK

    sectors = [s["name"] for s in json.loads((ROOT / "credit_engine" / "config" / "sectors.json")
                                             .read_text(encoding="utf-8"))["sectors"].values()]
    lists = wb.create_sheet("Lists")
    for i, name in enumerate(sectors, 1):
        lists[f"A{i}"] = name
    lists.sheet_state = "hidden"
    dv = DataValidation(type="list", formula1=f"=Lists!$A$1:$A${len(sectors)}", allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(SECTOR_CELL)
    dv2 = DataValidation(type="list", formula1=f'"{STATEMENT_TYPES}"', allow_blank=True)
    ws.add_data_validation(dv2)
    for c in INPUT_COLUMNS:
        dv2.add(f"{c}6")

    cr = wb["Credit Rating"]
    for r in range(34, 42):  # stale commentary from the working example
        cr[f"R{r}"] = None
    for r in range(4, 7):
        for c in "HIJK":
            cr[f"{c}{r}"] = None

    ins = wb.create_sheet("Instructions", 0)
    lines = [
        "Credit/Financial Analysis Automation: private company input template",
        "",
        "Fill the pink cells on the Inputs sheet. Leave a cell blank if you don't have the figure; the app will say so.",
        "Units: US$ millions. Expenses (COGS, SG&A, interest, tax) are positive; capex and dividends are negative.",
        "Columns C, E, G, I = most recent YTD and quarters; K, M, O, Q = fiscal years (most recent first).",
        "Row 4: period end date. Row 5: months in the period (3, 6, 9 or 12).",
        "Row 6: statement type (Audited, Reviewed, Compiled, Management). Unaudited figures are flagged for review.",
        "Row 101: Total Shareholders' Equity as reported. The app checks Total Assets = Total Liabilities + Equity.",
        "Rows 102-105: inventory, operating leases, floating-rate share of debt (optional).",
        "Row 107: pick the sector from the dropdown (used for sector benchmarks and the industry/economic analysis).",
        "Row 108: agency rating if one exists (optional; used only for comparison).",
        "The app never changes your numbers. Anything that looks inconsistent is flagged, not corrected.",
    ]
    for i, t in enumerate(lines, 1):
        ins[f"A{i}"] = t
    ins["A1"].font = Font(bold=True, size=14)
    ins.column_dimensions["A"].width = 120
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
