"""Period helpers: month-end date math, opening balance sheet lookup, and LTM builds."""
from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, timedelta
from typing import Optional

from .models import BALANCE_FIELDS, FLOW_FIELDS, PeriodData


def shift_month_end(d: date, months: int) -> date:
    """Month-end date `months` before `d`. 52/53-week fiscal periods end a few days into the next month
    (e.g., Oct 2 for a September quarter), so dates in the first week count as the previous month's end."""
    if d.day <= 7:
        d = d.replace(day=1) - timedelta(days=1)
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, calendar.monthrange(y, m)[1])


def near(a: date, b: date, tolerance_days: int = 10) -> bool:
    """Dates match allowing for 52/53-week fiscal calendars (period ends not on month ends)."""
    return abs((a - b).days) <= tolerance_days


def find_opening(period: PeriodData, periods: list[PeriodData]) -> Optional[PeriodData]:
    """The balance sheet at the start of `period` (its end date minus its months)."""
    start = shift_month_end(period.period_end, period.months)
    for p in periods:
        if p is not period and near(p.period_end, start) and p.total_assets is not None:
            return p
    return None


def _combine(label: str, end_source: PeriodData, parts: list[tuple[PeriodData, int]]) -> PeriodData:
    """Flows = signed sum of parts; balance sheet = end_source's."""
    out = replace(end_source, label=label, months=12, kind="LTM", sources={})
    for f in FLOW_FIELDS:
        vals = [(p.get(f), sign) for p, sign in parts]
        if any(v is None for v, _ in vals):
            setattr(out, f, None)
        else:
            setattr(out, f, sum(v * sign for v, sign in vals))
    for f in BALANCE_FIELDS:
        setattr(out, f, getattr(end_source, f))
    out.sources = {"_built_from": [f"{'+' if s > 0 else '-'}{p.label}" for p, s in parts]}
    return out


def ltm_from_ytd(fiscal_year: PeriodData, ytd: PeriodData, prior_ytd: PeriodData) -> PeriodData:
    """LTM = last fiscal year + current YTD - prior-year YTD."""
    label = f"LTM {ytd.period_end:%b-%Y}"
    return _combine(label, ytd, [(fiscal_year, 1), (ytd, 1), (prior_ytd, -1)])


def ltm_from_quarters(quarters: list[PeriodData]) -> PeriodData:
    """LTM = sum of the last four quarters (most recent last)."""
    if len(quarters) != 4:
        raise ValueError("need exactly four quarters")
    latest = max(quarters, key=lambda q: q.period_end)
    return _combine(f"LTM {latest.period_end:%b-%Y}", latest, [(q, 1) for q in quarters])
