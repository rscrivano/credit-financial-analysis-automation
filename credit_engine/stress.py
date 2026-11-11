"""Stress tests, re-scored with Ryan's scorecard (no AI).

* Rate shock: +200 bp on the floating-rate share of debt.
* Sector recession: the sector's median 2020 revenue change and operating-margin change
  (measured from SEC data, not assumed) applied to the period.
* Reverse stress: how far EBITDA can fall before the Reported rating reaches B- and CCC+.
Shocks flow through operating income, net income and operating cash flow one-for-one
(no tax shield, i.e., conservative); disclosed as an assumption.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from .engine import score_period
from .models import PeriodData
from .scorecard import Scorecard


def _shift(p: PeriodData, ebitda_delta: float = 0.0, interest_delta: float = 0.0, revenue=None) -> PeriodData:
    hit = ebitda_delta - interest_delta
    return replace(p, operating_income=None if p.operating_income is None else p.operating_income + ebitda_delta,
                   interest_expense=None if p.interest_expense is None else p.interest_expense + interest_delta,
                   net_income=None if p.net_income is None else p.net_income + hit,
                   cfo=None if p.cfo is None else p.cfo + hit,
                   revenue=revenue if revenue is not None else p.revenue)


def _rate(p, o, sc, share):
    r = score_period(p, o, sc, share)
    return {"reported": r.reported.rating, "lease_adjusted": r.lease_adjusted.rating,
            "reported_score": r.reported.score, "ebitda": r.ebitda.ebitda}


def rate_shock(p: PeriodData, opening, sc: Scorecard, share: float, floating: float, bps: int = 200) -> dict:
    debt = (p.lt_debt or 0) + p.get("st_debt")
    extra = debt * floating * bps / 10000 * p.months / 12
    return {"name": f"+{bps} bp rates on {floating:.0%} floating debt", "extra_interest": extra,
            **_rate(_shift(p, interest_delta=extra), opening, sc, share)}


def recession(p: PeriodData, opening, sc: Scorecard, share: float, rev_change: Optional[float],
              margin_change: Optional[float]) -> Optional[dict]:
    if rev_change is None or margin_change is None or not p.revenue or p.operating_income is None:
        return None
    new_rev = p.revenue * (1 + rev_change)
    new_oi = new_rev * (p.operating_income / p.revenue + margin_change)
    return {"name": f"Sector 2020 recession: revenue {rev_change:+.0%}, operating margin {margin_change * 100:+.1f} pts",
            **_rate(_shift(p, ebitda_delta=new_oi - p.operating_income, revenue=new_rev), opening, sc, share)}


def reverse(p: PeriodData, opening, sc: Scorecard, share: float, base_ebitda: Optional[float]) -> dict:
    out = {}
    if not base_ebitda or base_ebitda <= 0:
        return {"note": "EBITDA is zero or negative; reverse stress not meaningful."}
    for label, limit in (("B-", sc.notch_scale["B-"] - 0.5), ("CCC+", sc.notch_scale["CCC+"] - 0.5)):
        base = score_period(p, opening, sc, share).reported.score
        if base is None:
            out[label] = None
            continue
        if base >= limit:
            out[label] = 0.0
            continue
        lo, hi = 0.0, 2.0
        for _ in range(30):
            mid = (lo + hi) / 2
            s = score_period(_shift(p, ebitda_delta=-mid * base_ebitda), opening, sc, share).reported.score
            if s is not None and s >= limit:
                hi = mid
            else:
                lo = mid
        out[label] = hi if hi < 2.0 else None
    return out


def run_stress(p: PeriodData, opening, sc: Scorecard, share: float, floating: Optional[float],
               sector_recession: dict, base_ebitda: Optional[float]) -> dict:
    scen = []
    for f in ([floating] if floating is not None else [0.0, 0.5, 1.0]):
        scen.append(rate_shock(p, opening, sc, share, f))
    rec = recession(p, opening, sc, share, sector_recession.get("revenue_change_p50"),
                    sector_recession.get("op_margin_change_p50"))
    if rec:
        scen.append(rec)
    return {"base": _rate(p, opening, sc, share), "scenarios": scen,
            "reverse": reverse(p, opening, sc, share, base_ebitda), "floating_known": floating is not None,
            "notch_moves": notch_moves(p, opening, sc, share, base_ebitda)}


def notch_moves(p: PeriodData, opening, sc: Scorecard, share: float, base_ebitda: Optional[float]) -> dict:
    """EBITDA change (all else equal) that moves the Reported rating one notch down or up."""
    if not base_ebitda or base_ebitda <= 0:
        return {}
    now = score_period(p, opening, sc, share).reported.rating
    out = {"current": now}
    for side, sign, hi_lim in (("down", -1, 1.0), ("up", 1, 3.0)):
        rate = lambda d: score_period(_shift(p, ebitda_delta=sign * d * base_ebitda), opening, sc, share).reported.rating  # noqa: E731
        if rate(hi_lim) == now:
            out[side] = None
            continue
        lo, hi = 0.0, hi_lim
        for _ in range(25):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if rate(mid) == now else (lo, mid)
        out[side] = {"ebitda_change": sign * hi, "to": rate(hi)}
    return out


CASE_KEYS = {"ebitda_adj": (-1e7, 1e7), "debt_adj": (-1e7, 1e7), "rev_growth": (-90.0, 300.0), "ebitda_margin": (-100.0, 100.0)}


def analyst_case(p: PeriodData, opening, sc: Scorecard, share: float, ac: dict) -> Optional[dict]:
    """The analyst's own case beside Reported: EBITDA add-backs, debt adjustments and a one-year projection
    (revenue growth and EBITDA margin). Inputs are annual US$ m and %; Reported stays unchanged."""
    from dataclasses import replace

    from .engine import credit_score
    if not p.months:
        return None
    f = p.months / 12  # annual inputs -> this period's length
    base = score_period(p, opening, sc, share)
    e0 = base.ebitda.ebitda
    if e0 is None or not p.revenue:
        return {"error": "Revenue or EBITDA is missing for this period, so an analyst case can't be built."}
    g, m = ac.get("rev_growth"), ac.get("ebitda_margin")
    rev = p.revenue * (1 + (g or 0) / 100)
    e1 = rev * m / 100 if m is not None else e0 * rev / p.revenue  # margin given, or today's margin held
    e1 += (ac.get("ebitda_adj") or 0) * f
    q = _shift(p, ebitda_delta=e1 - e0, revenue=rev)
    if ac.get("debt_adj"):
        q = replace(q, lt_debt=(q.lt_debt or 0) + ac["debt_adj"])
    case = score_period(q, opening, sc, share)
    notes = []
    if g is not None:
        notes.append(f"Revenue {g:+.1f}% (one-year projection)")
    if m is not None:
        notes.append(f"EBITDA margin set to {m:.1f}%")
    if ac.get("ebitda_adj"):
        notes.append(f"EBITDA adjustment {ac['ebitda_adj']:+,.0f}m a year")
    if ac.get("debt_adj"):
        notes.append(f"Debt adjustment {ac['debt_adj']:+,.0f}m")
    notes.append("Interest, leases and the balance sheet are otherwise held at reported levels")

    def show(x):
        if x.value is None:
            return x.message or "–"
        return f"{x.value:.1%}" if "(%)" in x.name else f"{x.value:.2f}x"
    ratios = [{"name": a.name, "base": show(a), "case": show(b), "base_notch": a.notch, "case_notch": b.notch}
              for a, b in zip(base.reported.ratios, case.reported.ratios)]
    af = 12 / p.months
    return {"inputs": ac, "notes": notes, "ratios": ratios,
            "ebitda_12m": {"reported": e0 * af, "case": e1 * af}, "revenue_12m": {"reported": p.revenue * af, "case": rev * af},
            "reported": {"rating": base.reported.rating, "score": base.reported.score, "credit_score": credit_score(base.reported.score)},
            "case": {"rating": case.reported.rating, "score": case.reported.score, "credit_score": credit_score(case.reported.score),
                     "lease_adjusted": case.lease_adjusted.rating}}
