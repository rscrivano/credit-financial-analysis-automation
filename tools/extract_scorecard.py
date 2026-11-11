"""Extract the rating scorecard (weights, notch scale, threshold grid) from Ryan's
credit spread template workbook into a JSON config the engine reads.

Run once per template change:
    python tools/extract_scorecard.py tests/fixtures/southwest_template.xlsx \
        credit_engine/config/ryan_template_scorecard.json

Reading the grid from the workbook (instead of retyping it) keeps the app
traceable to the original template cell by cell.
"""
from __future__ import annotations

import json
import sys

import openpyxl

# Rating label -> column in the threshold grid (row 43 of 'Credit Rating').
GRID_COLUMNS = {
    "AAA": "AQ", "AAA-": "AR", "AA+": "AS", "AA": "AU", "AA-": "AV", "A+": "AW",
    "A": "AY", "A-": "AZ", "BBB+": "BA", "BBB": "BC", "BBB-": "BD", "BB+": "BE",
    "BB": "BG", "BB-": "BH", "B+": "BI", "B": "BK", "B-": "BL", "CCC+": "BM",
    "CCC": "BN",
}
CC_COLUMN, C_COLUMN, NEGATIVE_FLOOR_COLUMN = "BQ", "BS", "BU"

# key, display name, weight row (col E), grid row, direction, shown as percent?
RATIOS = [
    ("ebitda_margin", "EBITDA / Revenue (%)", 10, 45, "higher", True),
    ("ebit_coverage", "EBIT / Interest (x)", 11, 46, "higher", False),
    ("ebitda_coverage", "EBITDA / Interest (x)", 12, 47, "higher", False),
    ("ffo_to_debt", "FFO / Total Debt (%)", 14, 49, "higher", True),
    ("fcf_to_debt", "FCF / Total Debt (%)", 15, 50, "higher", True),
    ("dcf_to_debt", "Discretionary Cash Flow / Debt (%)", 16, 51, "higher", True),
    ("debt_to_ebitda", "Total Debt / EBITDA (x)", 18, 53, "lower", False),
    ("debt_to_capital", "Total Debt / (Debt + Equity) (%)", 19, 54, "lower", True),
    ("return_on_capital", "Return on Capital (%)", 20, 55, "higher", True),
]


def extract(path: str) -> dict:
    ws = openpyxl.load_workbook(path, data_only=True)["Credit Rating"]

    notch_scale = {}
    for r in range(9, 33):
        label, number = ws[f"AK{r}"].value, ws[f"AL{r}"].value
        if label and isinstance(number, (int, float)):
            notch_scale[label] = number

    ratios = {}
    for key, name, weight_row, grid_row, direction, pct in RATIOS:
        entry = {
            "name": name,
            "weight": ws[f"E{weight_row}"].value,
            "direction": direction,
            "percent": pct,
            "thresholds": {lbl: ws[f"{col}{grid_row}"].value for lbl, col in GRID_COLUMNS.items()},
            "cc_cutoff": ws[f"{CC_COLUMN}{grid_row}"].value,
            "c_cutoff": ws[f"{C_COLUMN}{grid_row}"].value,
            "source_cells": f"Credit Rating!E{weight_row} (weight), row {grid_row} (grid)",
        }
        floor = ws[f"{NEGATIVE_FLOOR_COLUMN}{grid_row}"].value
        if isinstance(floor, (int, float)):
            entry["negative_floor"] = floor  # below this -> C (e.g., negative EBITDA)
        ratios[key] = entry

    return {
        "name": "Credit scorecard",
        "benchmark": "S&P 3-year medians, U.S. industrials (2006-2008); notch cutoffs interpolated in thirds; CC/C cutoffs set by template author",
        "notch_scale": notch_scale,
        "ratio_label_order": list(GRID_COLUMNS),
        "ratios": ratios,
    }


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    cfg = extract(src)
    total = sum(r["weight"] for r in cfg["ratios"].values())
    assert abs(total - 1.0) < 1e-9, f"weights sum to {total}"
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"wrote {dst}: {len(cfg['ratios'])} ratios, {len(cfg['notch_scale'])} notches")
