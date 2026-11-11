"""Tests for the rules Ryan decided on (docs/spread_model_spec.md -> Decisions)."""
from dataclasses import replace
from datetime import date

import pytest

from credit_engine.engine import analyze, score_period
from credit_engine.models import INFINITE, MISSING, PeriodData
from credit_engine.periods import ltm_from_quarters, ltm_from_ytd
from credit_engine.scorecard import Scorecard

SC = Scorecard.load()


def healthy(end=date(2025, 12, 31), months=12, kind="Annual", label="FY 2025", **kw) -> PeriodData:
    base = dict(
        revenue=1000.0, cogs=600.0, sga=150.0, depreciation=50.0, operating_income=200.0,
        interest_expense=20.0, tax_expense=40.0, net_income=140.0, cfo=220.0, capex=-60.0,
        dividends=-30.0, total_assets=1500.0, cash=100.0, total_current_assets=400.0,
        total_liabilities=800.0, st_debt=50.0, total_current_liabilities=250.0, lt_debt=350.0,
    )
    base.update(kw)
    return PeriodData(label=label, period_end=end, months=months, kind=kind, **base)


def ratio(basis, key):
    return next(r for r in basis.ratios if r.key == key)


def test_ebitda_is_operating_income_plus_da():
    res = score_period(healthy(amortization=10.0), None, SC)
    assert res.ebitda.ebitda == 260.0  # 200 + 50 + 10
    assert res.ebitda.ebitda_margin == pytest.approx(0.26)


OPENING = healthy(end=date(2024, 12, 31), label="FY 2024")


def test_negative_net_interest_is_infinite_and_scored_top_notch():
    res = score_period(healthy(interest_expense=-15.0), OPENING, SC).reported
    for key in ("ebit_coverage", "ebitda_coverage"):
        r = ratio(res, key)
        assert r.status == INFINITE and r.message == "Ratio is Infinite"
        assert r.notch == "AAA"
    assert res.weight_used == pytest.approx(1.0)


def test_missing_cfo_is_missing_and_reweighted():
    res = score_period(healthy(cfo=None), OPENING, SC).reported
    r = ratio(res, "dcf_to_debt")
    assert r.status == MISSING and r.message == "Data is Missing" and r.notch is None
    used = sum(x.weight for x in res.ratios if x.status != MISSING)
    assert res.weight_used == pytest.approx(used)
    assert res.score == pytest.approx(sum(x.contribution for x in res.ratios if x.contribution) / used)
    assert "re-weighted" in res.message


def test_limited_information_still_rated_and_labelled():
    # Missing interest knocks out both coverage ratios and ROC: 38% of the weight.
    res = score_period(healthy(interest_expense=None), OPENING, SC).reported
    assert res.weight_used == pytest.approx(0.62)
    assert res.rating is not None and res.message.startswith("Limited information (provisional)")


def test_credit_score_scale():
    from credit_engine.engine import coverage_label, credit_score
    assert credit_score(1) == 100 and credit_score(24) == 0 and credit_score(11) == 57
    assert coverage_label(1.0) == "Full opinion" and coverage_label(0.8) == "Substantial information"


def test_negative_ebitda_leverage_is_infinite_bottom_notch():
    res = score_period(healthy(operating_income=-100.0, depreciation=20.0), None, SC).reported
    r = ratio(res, "debt_to_ebitda")
    assert r.status == INFINITE and r.notch == "C"


def test_fcf_uses_opening_balance_sheet():
    opening = healthy(end=date(2024, 12, 31), label="FY 2024", total_current_assets=380.0)
    with_open = score_period(healthy(), opening, SC).reported
    without = score_period(healthy(), None, SC).reported
    assert ratio(with_open, "fcf_to_debt").status == "ok"
    assert ratio(without, "fcf_to_debt").status == MISSING
    # FFO 190, capex -60, NWC change (300-200)-(280-200)=+20 -> FCF 110; debt 400
    assert ratio(with_open, "fcf_to_debt").value == pytest.approx(110 / 400)


def test_return_on_capital_annualized_once():
    q = healthy(end=date(2025, 3, 31), months=3, kind="Quarter", label="Q1",
                net_income=35.0, interest_expense=5.0, tax_expense=10.0)
    r = ratio(score_period(q, None, SC).reported, "return_on_capital")
    assert r.value == pytest.approx((35 + 5 + 10) * 4 / (400 + 700))


def test_rating_ladder_reaches_bb_plus():
    assert SC.rating_for_score(12.0) == "BB+"
    assert SC.rating_for_score(11.87) == "BB+"
    assert SC.rating_for_score(10.6) == "BBB-"
    # The workbook's lookup could never output BB+:
    assert SC.rating_for_score_template(11.87) == "BBB-"
    assert all(SC.rating_for_score_template(s / 100) != "BB+" for s in range(0, 2450))


def test_reported_then_lease_adjusted():
    p = healthy(operating_lease_liabilities=300.0, operating_lease_cost=60.0)
    res = score_period(p, None, SC)
    assert res.reported.basis == "Reported" and res.lease_adjusted.basis == "Lease-adjusted"
    assert res.reported.total_debt == 400.0
    assert res.lease_adjusted.total_debt == 700.0
    assert res.lease_adjusted.ebitda == 310.0  # EBITDA 250 + lease cost 60
    assert res.ebitda.ebitdar == 310.0
    # interest gets 1/3 of lease cost: (250+60)/(20+20)
    assert ratio(res.lease_adjusted, "ebitda_coverage").value == pytest.approx(310 / 40)


def test_lease_adjusted_missing_inputs_message():
    res = score_period(healthy(), None, SC)
    assert res.lease_adjusted.rating is None
    assert res.lease_adjusted.message.startswith("Data is Missing")


def test_ltm_from_ytd_and_quarters():
    fy = healthy()
    ytd = healthy(end=date(2026, 9, 30), months=9, kind="YTD", label="9M 26", revenue=800.0)
    prior = healthy(end=date(2025, 9, 30), months=9, kind="YTD", label="9M 25", revenue=700.0)
    ltm = ltm_from_ytd(fy, ytd, prior)
    assert ltm.revenue == 1100.0 and ltm.months == 12 and ltm.total_assets == ytd.total_assets

    qs = [healthy(end=e, months=3, kind="Quarter", label=f"Q{i}", revenue=250.0 + i)
          for i, e in enumerate([date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)])]
    assert ltm_from_quarters(qs).revenue == 1006.0

    res = analyze("Test Co", [fy, ytd, prior])
    assert res.primary.kind == "LTM" and res.periods[0].kind == "LTM"
