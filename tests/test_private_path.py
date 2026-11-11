"""Private-company path: blank template, any-format Excel mapping, data-integrity red flags (offline, no AI)."""
import json
from dataclasses import replace
from pathlib import Path

import openpyxl
import pytest

from credit_engine import pipeline
from credit_engine.integrity import integrity_flags
from credit_engine.mapper import build_periods, match_label, parse_period, read_statements
from credit_engine.workbook_export import write_template
from credit_engine.workbook_import import FIELD_ROWS, INPUT_COLUMNS
from credit_engine.xbrl_map import build_spread

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_XLSX = ROOT / "data" / "samples" / "sample_private_company_statements.xlsx"
LUV = build_spread(json.loads((ROOT / "data" / "sample" / "CIK0000092380.json").read_text(encoding="utf-8")))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(pipeline, "macro_panel", lambda: [])
    monkeypatch.setattr(pipeline, "industry_panel", lambda key: [])


def scores(report):
    return {p["label"]: (p["reported"]["rating"], round(p["reported"]["score"], 9),
                         p["lease_adjusted"]["rating"]) for p in report["periods"]}


def test_blank_template_has_no_values():
    ws = openpyxl.load_workbook(ROOT / "data" / "templates" / "private_company_template.xlsx")["Inputs"]
    assert all(ws[f"{c}{r}"].value is None for r in FIELD_ROWS.values() for c in INPUT_COLUMNS)
    assert ws["C9"].value == "=C7-C8"  # Ryan's formulas kept


def test_template_round_trip_matches_public(tmp_path):
    wb = write_template("Private Co", LUV.periods, LUV.openings, tmp_path / "p.xlsx", "Airlines")
    priv = pipeline.run_workbook(str(wb), use_ai=False)
    pub = pipeline.run_periods("Public", LUV.periods + LUV.openings, meta={"sector": "airlines"}, use_ai=False)
    shared = set(scores(priv)) & set(scores(pub))
    assert len(shared) >= 7
    assert all(scores(priv)[k] == scores(pub)[k] for k in shared)
    assert priv["sector_key"] == "airlines"
    assert not [f for f in priv["integrity"] if f["severity"] == "red"]


def test_balance_sheet_that_does_not_balance_is_red(tmp_path):
    fy = max((p for p in LUV.periods if p.kind == "Annual"), key=lambda p: p.period_end)
    bad = [replace(p, total_equity=p.total_equity * 1.05) if p is fy else p for p in LUV.periods]
    r = pipeline.run_workbook(str(write_template("Bad Co", bad, LUV.openings, tmp_path / "b.xlsx")), use_ai=False)
    red = [f for f in r["integrity"] if f["severity"] == "red"]
    assert red and red[0]["title"] == "Balance sheet doesn't balance" and fy.label in red[0]["periods"]
    # The numbers are flagged, never changed:
    assert r["primary"]["reported"]["rating"]


def test_other_integrity_checks():
    p = replace(LUV.periods[0], total_current_assets=LUV.periods[0].total_assets + 500, capex=50.0, cash=-5.0)
    titles = {f["title"] for f in integrity_flags([p])}
    assert {"Current assets exceeds total assets", "Capex is positive", "Negative cash"} <= titles


def test_label_and_period_parsing():
    assert match_label("Net Sales")[0] == "revenue"
    assert match_label("Total Stockholders' Equity")[0] == "total_equity"
    assert match_label("Purchases of property and equipment")[0] == "capex_gross"  # gross; net capex is derived
    assert match_label("Widget royalties")[0] is None
    assert parse_period("Q3 2026")["months"] == 3 and parse_period("FY2025")["months"] == 12
    assert parse_period("9M 2026")["months"] == 9


def test_company_format_excel_matches_public():
    m = read_statements(str(SAMPLE_XLSX))
    assert not [r for r in m["rows"] if r["field"] is None]
    periods, notes = build_periods(m)
    assert any("net interest income" in n for n in notes)  # sign convention disclosed
    priv = pipeline.run_periods(m["company"], periods, meta={"sector": "airlines"}, use_ai=False)
    pub = pipeline.run_periods("Public", LUV.periods + LUV.openings, meta={"sector": "airlines"}, use_ai=False)
    for label in ("FY 2025", "FY 2024"):
        assert scores(priv)[label] == scores(pub)[label]
    agg = priv["peer_aggregate"]  # private company compared with named public competitors and their median
    assert len(agg["names"]) >= 3 and agg["metrics"][0]["key"] == "revenue" and agg["metrics"][0]["peer_median"]
