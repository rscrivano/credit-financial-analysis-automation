"""SEC XBRL -> spread mapping, run offline against the bundled sample data."""
import json
from datetime import date
from pathlib import Path

import pytest

from credit_engine import edgar
from credit_engine.engine import analyze
from credit_engine.xbrl_map import build_spread

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def spread(cik):
    return build_spread(json.loads((SAMPLE / f"CIK{cik:010d}.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def luv():
    return spread(92380)


@pytest.fixture(scope="module")
def ulcc():
    return spread(1670076)


def period(sp, label):
    return next(p for p in sp.periods if p.label == label)


def test_southwest_9m_ties_to_workbook(luv):
    p = period(luv, "9M YTD Sep-2026")
    assert (p.revenue, p.operating_income, p.depreciation, p.net_income, p.cfo) == (24104, 994, 1198, 730, 2460)
    assert (p.total_assets, p.cash, p.lt_debt) == (30539, 3624, 3734)
    assert p.total_liabilities == 23210  # derived: liabilities & equity - equity
    assert p.sources["total_liabilities"][0].startswith("Derived")


def test_net_interest_convention(luv):
    p = period(luv, "9M YTD Sep-2026")
    assert p.interest_expense == 188 - 90  # gross - interest income; capitalized not tagged
    assert any("not tagged" in s for s in p.sources["interest_expense"])


def test_quarter_cash_flow_derived_from_ytd(ulcc):
    q3 = period(ulcc, "Q Sep-2026")
    assert q3.cfo == pytest.approx(-41)  # 9M 150 - 6M 191
    assert q3.sources["cfo"][0].startswith("Derived")


def test_lease_cost_estimate_is_labelled(luv):
    p = period(luv, "9M YTD Sep-2026")
    assert p.operating_lease_cost == pytest.approx(346 * 9 / 12)
    assert p.sources["operating_lease_cost"][0].startswith("Estimate")


def test_every_number_has_a_source(luv):
    p = period(luv, "FY 2025")
    for f in ("revenue", "operating_income", "net_income", "total_assets", "lt_debt", "st_debt"):
        assert p.sources.get(f), f


def test_ltm_is_primary_with_both_bases(luv, ulcc):
    for sp in (luv, ulcc):
        res = analyze(sp.company, sp.periods, openings=sp.openings)
        assert res.primary.kind == "LTM" and res.primary.period_end == date(2026, 9, 30)
        assert res.primary.reported.rating and res.primary.lease_adjusted.rating
        assert res.primary.reported.weight_used == pytest.approx(1.0)


@pytest.mark.parametrize("bad", ["", "LUV; DROP", "../etc", "A" * 11, "luv?x=1", "<script>"])
def test_ticker_validation_rejects_bad_input(bad):
    with pytest.raises(edgar.EdgarError):
        edgar.normalize_ticker(bad)


def test_offline_fallback_to_sample(monkeypatch, tmp_path):
    monkeypatch.setattr(edgar, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(edgar, "load_env", lambda: [])
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setattr(edgar, "DEFAULT_USER_AGENT", "")  # simulate no contact -> no live calls
    t, cik, _ = edgar.lookup("ulcc")
    facts, source = edgar.company_facts(cik)
    assert (t, cik, source) == ("ULCC", 1670076, "sample")
    with pytest.raises(edgar.EdgarError, match="offline sample"):
        edgar.lookup("AAPL")
