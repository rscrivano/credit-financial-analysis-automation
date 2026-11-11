"""Sector tiers, S&P-style anchor and stress tests (deterministic)."""
import json
from pathlib import Path

import pytest

from credit_engine.engine import analyze
from credit_engine.scorecard import Scorecard
from credit_engine.sector import analyze_sector, tier
from credit_engine.sp_method import anchor, financial_risk, suggest_business_risk
from credit_engine.stress import run_stress
from credit_engine.xbrl_map import build_spread

ROOT = Path(__file__).resolve().parent.parent
LUV = build_spread(json.loads((ROOT / "data" / "sample" / "CIK0000092380.json").read_text(encoding="utf-8")))


def test_benchmarks_show_sector_differences():
    b = json.loads((ROOT / "data" / "benchmarks" / "sector_benchmarks.json").read_text())["sectors"]
    assert len(b) == 22
    it = lambda k: b[k]["ratios"]["inventory_turnover"]["p50"]  # noqa: E731
    assert it("restaurants") > it("retail") > it("industrial_mfg")


def test_tiers_respect_direction():
    hi = {"p10": 1, "p25": 2, "p50": 3, "p75": 4, "p90": 5, "direction": "higher"}
    lo = {**hi, "direction": "lower"}
    assert tier(4.5, hi) == "Strong" and tier(1.5, hi) == "Struggling"
    assert tier(1.5, lo) == "Strong" and tier(4.5, lo) == "Struggling"


def test_sp_tables():
    assert financial_risk(0.65, 1.2)["category"] == "Minimal"
    f = financial_risk(0.35, 4.5)  # FFO/debt says Intermediate, leverage says Aggressive
    assert f["disagree"] and f["category"] == "Aggressive"
    assert financial_risk(0.35, 4.5, rule="stronger")["category"] == "Intermediate"
    assert financial_risk(None, None, ebitda_negative=True)["category"] == "Highly leveraged"
    assert anchor("Satisfactory", 2) == "BBB / BBB-" and anchor("Vulnerable", 5) == "B-"
    s = suggest_business_risk(90, 90, -0.46)
    assert s["suggested"] == "Satisfactory" and "capped" in s["rule"]  # cyclical cap


def test_sector_and_stress_on_southwest():
    res = analyze(LUV.company, LUV.periods, openings=LUV.openings)
    sec = analyze_sector("airlines", res.primary_input)
    assert sec["available"] and sec["overall"] in ("Strong", "Normal", "Struggling")
    st = run_stress(res.primary_input, res.primary_opening, Scorecard.load(), 1 / 3, None,
                    sec["recession_2020"], res.primary.ebitda.ebitda)
    assert len(st["scenarios"]) == 4  # 3 floating-rate cases + sector recession
    rev = st["reverse"]
    assert 0 < rev["B-"] < rev["CCC+"] < 1


def test_volatility_tables_and_liquidity_cap():
    from credit_engine.sp_method import cap_rating, financial_risk_table
    assert financial_risk_table(0.30, 3.2, table="standard")["category"] == "Significant"
    assert financial_risk_table(0.30, 3.2, table="low")["category"] == "Intermediate"   # utilities: looser scale
    assert financial_risk_table(0.15, 5.5, rule="ffo", table="low")["category"] == "Intermediate"  # FFO/debt primary
    assert cap_rating("BBB / BBB-", "BB+") == "BB+" and cap_rating("B+", "B-") == "B-" and cap_rating("BB", "BB+") == "BB"


def test_debt_structure_and_liquidity_from_filings():
    from credit_engine.debt import liquidity
    res = analyze(LUV.company, LUV.periods, openings=LUV.openings)
    ds = LUV.debt
    assert ds["debt"]["Y1"] == 321 and ds["debt"]["Y2"] == 2150 and ds["op_lease"]["Y1"] == 345
    liq = liquidity(res.primary_input, ds, 2975)
    assert liq["basis"] == "debt maturity table" and liq["assessment"] in ("Exceptional", "Strong")
