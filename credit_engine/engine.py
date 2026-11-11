"""The app's scoring engine: Ryan's template scorecard plus the agreed rules.

Rules (docs/spread_model_spec.md -> "Decisions"):
  1. An unscorable ratio is labelled "Ratio is Infinite" (scored at the top notch
     when that is good for the credit, the bottom notch when it is bad) or
     "Data is Missing" (left out; the remaining weights are re-weighted). If
     more than a third of the scorecard weight is missing, no rating is given.
  2. EBITDA = operating income + D&A, reported in its own section.
  3. Two bases: Reported first, then Lease-adjusted (operating lease liabilities
     added to debt; operating lease cost added back to EBITDA, split into an
     interest part and a depreciation part).
  4. LTM is the primary period when it can be built.
Also corrected versus the workbook: the score-to-rating lookup (BB+ reachable),
return on capital annualized once, and FCF working-capital change measured
against the balance sheet at the start of the period.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import (INFINITE, MISSING, OK, STATUS_MESSAGE, BasisResult, EbitdaSection,
                     PeriodData, PeriodResult, RatioResult)
from .periods import find_opening, ltm_from_quarters, ltm_from_ytd, near, shift_month_end
from .scorecard import Scorecard

FULL_OPINION, SUBSTANTIAL = 0.90, 2 / 3


def coverage_label(weight_used: float) -> str:
    """How much of the scorecard backs the opinion."""
    if weight_used >= FULL_OPINION - 1e-9:
        return "Full opinion"
    if weight_used >= SUBSTANTIAL - 1e-9:
        return "Substantial information"
    return "Limited information (provisional)"


def credit_score(score: Optional[float], worst: float = 24.0, best: float = 1.0) -> Optional[int]:
    """Weighted scorecard score (1 = AAA ... 24 = C) on a 0-100 scale, 100 = strongest."""
    if score is None:
        return None
    return max(0, min(100, round((worst - score) / (worst - best) * 100)))
DEFAULT_LEASE_INTEREST_SHARE = 1 / 3  # share of operating lease cost treated as interest


@dataclass
class AnalysisResult:
    company: str
    scorecard: str
    primary: Optional[PeriodResult]
    periods: list[PeriodResult]
    notes: list[str] = field(default_factory=list)
    primary_input: Optional[PeriodData] = None    # inputs behind `primary`, for re-scoring
    primary_opening: Optional[PeriodData] = None


def _add(*vals: Optional[float]) -> Optional[float]:
    return None if any(v is None for v in vals) else sum(vals)


def ebitda_section(p: PeriodData) -> EbitdaSection:
    da = _add(p.get("amortization"), p.get("depreciation"))
    ebitda = _add(p.operating_income, da)
    rev = p.revenue
    margin = ebitda / rev if ebitda is not None and rev not in (None, 0) else None
    lease_cost = p.operating_lease_cost
    return EbitdaSection(
        operating_income=p.operating_income, depreciation_amortization=da, ebitda=ebitda,
        revenue=rev, ebitda_margin=margin, operating_lease_cost=lease_cost,
        ebitdar=_add(ebitda, lease_cost) if lease_cost is not None else None,
    )


def _working_capital(q: Optional[PeriodData]) -> Optional[float]:
    if q is None:
        return None
    tca, cash, tcl, std = q.total_current_assets, q.cash, q.total_current_liabilities, q.get("st_debt")
    if None in (tca, cash, tcl, std):
        return None
    return (tca - cash) - (tcl - std)


def _basis(p: PeriodData, opening: Optional[PeriodData], sc: Scorecard, lease_adjusted: bool,
           lease_interest_share: float) -> BasisResult:
    name = "Lease-adjusted" if lease_adjusted else "Reported"
    eb = ebitda_section(p)

    debt = _add(p.get("lt_debt"), p.get("st_debt")) if p.lt_debt is not None else None
    ebitda, ebit, interest = eb.ebitda, p.operating_income, p.interest_expense
    ni = p.net_income
    ni_recurring = _add(ni, p.get("nonrecurring"))
    ffo = _add(ni_recurring, eb.depreciation_amortization, p.get("deferred_taxes"), p.get("other_noncash"))
    wc_now, wc_open = _working_capital(p), _working_capital(opening)
    fcf = _add(ffo, p.get("capex"), -(wc_now - wc_open)) if None not in (wc_now, wc_open) else None
    dcf = _add(p.cfo, p.get("capex"), p.get("dividends"))
    equity = _add(p.total_assets, -p.total_liabilities) if p.total_liabilities is not None else None

    if lease_adjusted:
        L, R = p.operating_lease_liabilities, p.operating_lease_cost
        if L is None or R is None:
            return BasisResult(name, [], None, None, 0.0,
                               message="Data is Missing: operating lease liabilities and lease cost are needed "
                                       "for the lease-adjusted basis.")
        lease_int = R * lease_interest_share
        lease_dep = R - lease_int
        debt = _add(debt, L)
        ebitda = _add(ebitda, R)
        ebit = _add(ebit, lease_int)
        interest = _add(interest, lease_int)
        ffo, fcf, dcf = (_add(x, lease_dep) if x is not None else None for x in (ffo, fcf, dcf))

    af = 12 / p.months
    ratios: list[RatioResult] = []

    def emit(key, value=None, status=OK, good=True, note=""):
        cfg = sc.ratios[key]
        w = cfg["weight"]
        if status == MISSING:
            notch = None
        elif status == INFINITE:
            notch = sc.top_notch if good else sc.bottom_notch
        else:
            notch = sc.notch_for(key, value)
        contrib = w * sc.notch_scale[notch] if notch else None
        ratios.append(RatioResult(key, cfg["name"], value, status, notch, w, contrib,
                                  STATUS_MESSAGE[status], note))

    # 1. EBITDA margin
    if ebitda is None or p.revenue is None or p.revenue <= 0:
        emit("ebitda_margin", status=MISSING)
    else:
        emit("ebitda_margin", ebitda / p.revenue)
    # 2-3. Coverage
    for key, numer in (("ebit_coverage", ebit), ("ebitda_coverage", ebitda)):
        if numer is None or interest is None:
            emit(key, status=MISSING)
        elif interest <= 0:
            emit(key, status=INFINITE, good=True, note="Net interest expense is zero or negative (interest income exceeds expense).")
        else:
            emit(key, numer / interest)
    # 4-6. Cash flow to debt (annualized)
    for key, cf, missing_note in (("ffo_to_debt", ffo, ""), ("fcf_to_debt", fcf,
                                   "" if opening is not None else "No opening balance sheet for the working-capital change."),
                                  ("dcf_to_debt", dcf, "")):
        if cf is None or debt is None:
            emit(key, status=MISSING, note=missing_note)
        elif debt <= 0:
            emit(key, status=INFINITE, good=True, note="No debt outstanding.")
        else:
            emit(key, cf * af / debt)
    # 7. Leverage
    if debt is None or ebitda is None:
        emit("debt_to_ebitda", status=MISSING)
    elif debt <= 0:
        emit("debt_to_ebitda", 0.0, note="No debt outstanding.")
    elif ebitda <= 0:
        emit("debt_to_ebitda", status=INFINITE, good=False, note="EBITDA is zero or negative, so leverage is unbounded; scored at the bottom notch.")
    else:
        emit("debt_to_ebitda", debt / (ebitda * af))
    # 8. Debt / capital
    if debt is None or equity is None:
        emit("debt_to_capital", status=MISSING)
    elif debt <= 0:
        emit("debt_to_capital", 0.0, note="No debt outstanding.")
    elif debt + equity <= 0:
        emit("debt_to_capital", status=INFINITE, good=False, note="Negative equity exceeds debt; scored at the bottom notch.")
    else:
        emit("debt_to_capital", debt / (debt + equity))
    # 9. Return on capital (annualized once)
    dtl = p.get("deferred_tax_liability")
    if None in (ni, interest, debt, equity):
        emit("return_on_capital", status=MISSING)
    else:
        numer = (ni + interest + p.get("tax_expense")) * af
        denom = debt + equity + dtl
        if denom <= 0:
            emit("return_on_capital", status=INFINITE, good=numer > 0, note="Capital base is zero or negative.")
        else:
            emit("return_on_capital", numer / denom)

    weight_used = sum(r.weight for r in ratios if r.status != MISSING)
    if weight_used <= 0:
        return BasisResult(name, ratios, None, None, 0.0, message="No ratio could be calculated from this data.",
                           total_debt=debt, ebitda=ebitda)
    # Always give an opinion from what is available, and say how much of the scorecard backs it.
    score = sum(r.contribution for r in ratios if r.contribution is not None) / weight_used
    msg = "" if weight_used > 1 - 1e-9 else (
        f"{coverage_label(weight_used)}: rated on {weight_used:.0%} of the scorecard (missing ratios re-weighted).")
    return BasisResult(name, ratios, score, sc.rating_for_score(score), weight_used, msg,
                       total_debt=debt, ebitda=ebitda)


def score_period(p: PeriodData, opening: Optional[PeriodData], sc: Scorecard,
                 lease_interest_share: float = DEFAULT_LEASE_INTEREST_SHARE) -> PeriodResult:
    return PeriodResult(
        label=p.label, period_end=p.period_end, months=p.months, kind=p.kind,
        ebitda=ebitda_section(p),
        reported=_basis(p, opening, sc, False, lease_interest_share),
        lease_adjusted=_basis(p, opening, sc, True, lease_interest_share),
    )


def _try_ltm(periods: list[PeriodData]) -> tuple[Optional[PeriodData], str]:
    ytds = sorted((p for p in periods if p.kind == "YTD"), key=lambda p: p.period_end, reverse=True)
    for y in ytds:
        fy_end = shift_month_end(y.period_end, y.months)
        fy = next((p for p in periods if p.kind == "Annual" and near(p.period_end, fy_end)), None)
        prior_end = shift_month_end(y.period_end, 12)
        prior = next((p for p in periods if p.kind == "YTD" and near(p.period_end, prior_end)
                      and p.months == y.months), None)
        if fy and prior:
            return ltm_from_ytd(fy, y, prior), ""
    qs = sorted((p for p in periods if p.kind == "Quarter"), key=lambda p: p.period_end, reverse=True)
    if len(qs) >= 4:
        last4 = qs[:4]
        if all(near(last4[i + 1].period_end, shift_month_end(last4[i].period_end, 3)) for i in range(3)):
            return ltm_from_quarters(last4), ""
    return None, ("LTM could not be built (needs the prior-year YTD period or four consecutive quarters); "
                  "the most recent period is shown as primary, annualized.")


def analyze(company: str, periods: list[PeriodData], sc: Optional[Scorecard] = None,
            lease_interest_share: float = DEFAULT_LEASE_INTEREST_SHARE,
            openings: Optional[list[PeriodData]] = None) -> AnalysisResult:
    """Score every period. `openings` are balance-sheet-only periods used for opening balances."""
    sc = sc or Scorecard.load()
    periods = [p for p in periods if not p.is_empty()]
    balance_pool = periods + list(openings or [])
    notes = []
    ltm, why = _try_ltm(periods)
    if why:
        notes.append(why)
    pool = periods + ([ltm] if ltm else [])

    order = {"LTM": 0, "YTD": 1, "Quarter": 2, "Annual": 3}
    pool.sort(key=lambda p: (order[p.kind], -p.period_end.toordinal()))
    results = [score_period(p, find_opening(p, balance_pool), sc, lease_interest_share) for p in pool]
    if ltm:
        i = 0
    else:  # most recent period of any kind
        i = max(range(len(results)), key=lambda k: (results[k].period_end, results[k].months)) if results else None
    if i is None:
        return AnalysisResult(company, sc.name, None, results, notes)
    # Headline = most recent period with complete data. A newer period that lacks inputs (e.g., interim debt only in a
    # company-specific tag) stays in the period table but doesn't drive the rating.
    if results[i].reported.weight_used < 1 - 1e-9:
        full = [k for k in range(len(results)) if results[k].reported.weight_used > 1 - 1e-9 and pool[k].kind != "Quarter"]
        if full:
            k = max(full, key=lambda k: (results[k].period_end, results[k].months))
            missing = [x.name.split(" (")[0] for x in results[i].reported.ratios if x.status == "missing"]
            notes.append(f"Headline period is {results[k].label}, the most recent period with complete data; "
                         f"{results[i].label} lacks {', '.join(missing)} and is shown in the period table only.")
            i = k
    return AnalysisResult(company, sc.name, results[i], results, notes,
                          primary_input=pool[i], primary_opening=find_opening(pool[i], balance_pool))
