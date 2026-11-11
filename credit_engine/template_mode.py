"""Template-faithful mode: reproduces Ryan's Excel workbook formula for formula.

This exists so the app can prove it matches the original template exactly
(see tests/test_template_regression.py). The app's own results come from
engine.py, which applies the agreed rule changes.

Excel semantics mirrored here: blank cells count as 0, and the workbook's
"N/A" results are returned as None.
"""
from __future__ import annotations

from typing import Optional

from .models import PeriodData
from .periods import shift_month_end
from .scorecard import Scorecard

NA = None


def _z(v: Optional[float]) -> float:
    return 0.0 if v is None else v


def template_ratios(p: PeriodData, adjacent: Optional[PeriodData]) -> dict[str, Optional[float]]:
    """The 'Annualized Ratio' column of the Credit Rating sheet for one period.

    `adjacent` is the column immediately to the right on the Inputs sheet, which
    the template uses for the working-capital change in FCF.
    """
    rev = _z(p.revenue)
    ebitda = rev - _z(p.cogs) - _z(p.sga) - _z(p.other_opex)          # Inputs r12
    da = _z(p.amortization) + _z(p.depreciation)                     # r15
    opinc, intr, tax, ni = _z(p.operating_income), _z(p.interest_expense), _z(p.tax_expense), _z(p.net_income)
    ni_rec = ni + _z(p.nonrecurring)                                  # r23
    debt = _z(p.lt_debt) + _z(p.st_debt)                              # r49

    ffo = NA if ni == 0 else (ni if ni_rec == 0 else ni_rec) + da + _z(p.deferred_taxes) + _z(p.other_noncash)

    def nwc(q: Optional[PeriodData]) -> float:
        if q is None:
            return 0.0
        return (_z(q.total_current_assets) - _z(q.cash)) - (_z(q.total_current_liabilities) - _z(q.st_debt))

    if _z(p.total_current_assets) > 0 and ffo is not NA:
        fcf = ffo + _z(p.capex) - (nwc(p) - nwc(adjacent))           # r63
    else:
        fcf = NA
    dcf = NA if _z(p.cfo) == 0 else _z(p.cfo) + _z(p.capex) + _z(p.dividends)  # r64

    ta, tl = _z(p.total_assets), _z(p.total_liabilities)
    equity = NA if ta == 0 else (ta - tl if tl > 0 else NA)           # r68

    r = {}
    r["ebitda_margin"] = NA if ebitda == 0 else ebitda / (rev + _z(p.amort_deferred_revenue))
    r["ebit_coverage"] = NA if intr <= 0 else opinc / intr
    r["ebitda_coverage"] = NA if intr <= 0 else ebitda / intr
    r["ffo_to_debt"] = NA if ffo is NA or debt <= 0 else ffo / debt
    r["fcf_to_debt"] = NA if fcf is NA or debt <= 0 else fcf / debt
    r["dcf_to_debt"] = NA if dcf is NA else dcf / debt
    r["debt_to_ebitda"] = NA if ebitda == 0 else debt / ebitda
    r["debt_to_capital"] = NA if debt <= 0 or equity is NA else debt / (debt + equity)
    if ni == 0 or equity is NA:
        r["return_on_capital"] = NA
    else:
        r["return_on_capital"] = (12 / p.months) * (ni + intr + tax) / (debt + equity + _z(p.deferred_tax_liability))

    # Credit Rating sheet annualization: 12 / (days since prior column date / (365/12)).
    days = (p.period_end - shift_month_end(p.period_end, p.months)).days
    f = 12 / (days / (365 / 12))
    for k in ("ffo_to_debt", "fcf_to_debt", "dcf_to_debt", "return_on_capital"):
        if r[k] is not NA:
            r[k] *= f
    if r["debt_to_ebitda"] is not NA:
        r["debt_to_ebitda"] /= f
    return r


def template_rating(p: PeriodData, adjacent: Optional[PeriodData], sc: Scorecard) -> dict:
    """Notches, final score and rating exactly as the workbook computes them."""
    ratios = template_ratios(p, adjacent)
    notches, score = {}, 0.0
    for key, val in ratios.items():
        if val is NA:
            notches[key] = None  # weight silently drops out (template behaviour)
            continue
        notches[key] = sc.notch_for(key, val)
        score += sc.ratios[key]["weight"] * sc.notch_scale[notches[key]]
    return {"ratios": ratios, "notches": notches, "score": score,
            "rating": sc.rating_for_score_template(score)}
