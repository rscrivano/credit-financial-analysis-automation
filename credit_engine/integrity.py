"""Data-integrity red flags for financials, especially unaudited private-company statements.

The numbers are never changed. Each check only reports what looks inconsistent, with
the figures involved, so the analyst can go back to the company.
severity: "red" (internally inconsistent) or "review" (unusual; verify).
"""
from __future__ import annotations

from typing import Optional

from .models import PeriodData

UNAUDITED = {"reviewed", "compiled", "management", "management accounts", "internal"}


def _f(v: Optional[float]) -> str:
    return "–" if v is None else f"{v:,.1f}"


def _flag(sev, period, title, detail, fields):
    return {"severity": sev, "period": period, "title": title, "detail": detail, "fields": fields}


def _tol(*vals) -> float:
    """Rounding tolerance: 0.5 or 0.1% of the largest figure."""
    return max(0.5, 0.001 * max(abs(v) for v in vals if v is not None))


def check_period(p: PeriodData) -> list[dict]:
    out = []
    L = p.label
    ta, tl, te = p.total_assets, p.total_liabilities, p.total_equity

    # 1. The balance sheet must balance.
    if ta is not None and tl is not None and te is not None:
        diff = ta - (tl + te)
        if abs(diff) > _tol(ta, tl, te):
            out.append(_flag("red", L, "Balance sheet doesn't balance",
                             f"Total assets {_f(ta)} vs. total liabilities {_f(tl)} + equity {_f(te)} = {_f(tl + te)} "
                             f"(difference {_f(diff)}). One of these figures, or a line inside them, is wrong.",
                             ["total_assets", "total_liabilities", "total_equity"]))
    elif ta is not None and tl is not None and te is None and p.quality.lower() != "sec filing":
        out.append(_flag("review", L, "Balance check not possible",
                         "Shareholders' equity wasn't provided, so equity is computed as assets minus liabilities, "
                         "which always balances. Enter reported equity to test it.", ["total_equity"]))

    # 2. Subtotals must contain their parts.
    def over(part_name, part, whole_name, whole, fields):
        if part is not None and whole is not None and part - whole > _tol(part, whole):
            out.append(_flag("red", L, f"{part_name} exceeds {whole_name}",
                             f"{part_name} {_f(part)} > {whole_name} {_f(whole)}.", fields))
    over("Current assets", p.total_current_assets, "total assets", ta, ["total_current_assets", "total_assets"])
    over("Current liabilities", p.total_current_liabilities, "total liabilities", tl,
         ["total_current_liabilities", "total_liabilities"])
    parts = [v for v in (p.cash, p.receivables, p.inventory) if v is not None]
    if len(parts) >= 2:
        over("Cash + receivables + inventory", sum(parts), "current assets", p.total_current_assets,
             ["cash", "receivables", "inventory", "total_current_assets"])
    debt = None if p.lt_debt is None else p.lt_debt + p.get("st_debt")
    over("Total debt", debt, "total liabilities", tl, ["lt_debt", "st_debt", "total_liabilities"])
    over("Short-term debt", p.st_debt, "current liabilities", p.total_current_liabilities,
         ["st_debt", "total_current_liabilities"])

    # 3. Signs that shouldn't happen.
    for name, v, field in (("Revenue", p.revenue, "revenue"), ("Total assets", ta, "total_assets"),
                           ("Cash", p.cash, "cash"), ("Inventory", p.inventory, "inventory"),
                           ("Depreciation", p.depreciation, "depreciation"), ("Receivables", p.receivables, "receivables")):
        if v is not None and v < 0:
            out.append(_flag("red", L, f"Negative {name.lower()}", f"{name} is {_f(v)}.", [field]))
    if p.capex is not None and p.capex > 0:
        out.append(_flag("review", L, "Capex is positive",
                         f"Capex is {_f(p.capex)}; the template expects capex as a negative cash outflow. Either asset "
                         "sales exceeded purchases or the sign was entered wrong.", ["capex"]))

    # 4. Income statement should roughly tie: operating income - interest - tax vs net income.
    if None not in (p.operating_income, p.interest_expense, p.net_income, p.revenue) and p.revenue > 0:
        gap = p.operating_income - p.interest_expense - p.get("tax_expense") - p.net_income
        if abs(gap) > 0.10 * p.revenue:
            out.append(_flag("review", L, "Large unexplained items below operating income",
                             f"Operating income − interest − tax differs from net income by {_f(gap)} "
                             f"({abs(gap) / p.revenue:.0%} of revenue). Check for one-offs or a mis-keyed line.",
                             ["operating_income", "interest_expense", "tax_expense", "net_income"]))

    # 5a. Debt that looks incomplete: gross interest far too high for the debt reported.
    gi = getattr(p, "gross_interest", None)
    if gi and gi > 0 and p.months and (debt or 0) >= 0:
        annual = gi * 12 / p.months
        if debt is None or debt <= 0 or annual / debt > 0.25:
            out.append(_flag("red", L, "Debt looks incomplete",
                             f"Annualized gross interest {_f(annual)} vs. reported debt {_f(debt)}"
                             + (f" (implied rate {annual / debt:.0%})" if debt else "") + ". Debt is probably reported in "
                             "company-specific tags; enter total debt from the filing's balance sheet in Financials.",
                             ["lt_debt", "st_debt"]))
    # 5. Implied interest rate on debt.
    if debt and debt > 0 and p.interest_expense and p.interest_expense > 0 and p.months:
        rate = p.interest_expense * 12 / p.months / debt
        if rate > 0.20:  # low rates are normal under the net-interest convention, so only the high end is tested
            out.append(_flag("review", L, "Implied interest rate looks off",
                             f"Annualized interest {_f(p.interest_expense * 12 / p.months)} on debt {_f(debt)} = {rate:.1%}. "
                             "Debt or interest may be incomplete (e.g., missing facilities or interest income netted).",
                             ["interest_expense", "lt_debt", "st_debt"]))

    # 6. D&A larger than the asset base it depreciates.
    if p.depreciation and p.fixed_assets and p.months and p.depreciation * 12 / p.months > p.fixed_assets + p.get("other_intangibles") + p.get("goodwill"):
        out.append(_flag("review", L, "D&A exceeds fixed assets",
                         f"Annualized D&A {_f(p.depreciation * 12 / p.months)} > fixed and intangible assets.",
                         ["depreciation", "fixed_assets"]))

    if p.quality.lower() in UNAUDITED:
        out.append(_flag("review", L, f"{p.quality} statements (unaudited)",
                         "Figures have not been audited; treat the rating as provisional.", []))
    return out


def check_series(periods: list[PeriodData]) -> list[dict]:
    """Checks across periods: large swings and quarters that don't add up to year-to-date."""
    out = []
    for kind in ("Annual", "Quarter"):
        ps = sorted((p for p in periods if p.kind == kind and not p.is_empty()), key=lambda p: p.period_end)
        for a, b in zip(ps, ps[1:]):
            for name, f in (("Revenue", "revenue"), ("Total assets", "total_assets")):
                va, vb = getattr(a, f), getattr(b, f)
                if va and vb and va > 0 and abs(vb / va - 1) > 0.5:
                    out.append(_flag("review", b.label, f"{name} moved {vb / va - 1:+.0%} vs. {a.label}",
                                     f"{name} {_f(va)} → {_f(vb)}. Confirm (acquisition, divestiture, or entry error).", [f]))
    for y in (p for p in periods if p.kind == "YTD"):
        qs = [q for q in periods if q.kind == "Quarter" and q.period_end <= y.period_end
              and (y.period_end - q.period_end).days < y.months * 31]
        if len(qs) * 3 == y.months:
            for name, f in (("Revenue", "revenue"), ("Net income", "net_income"), ("Operating cash flow", "cfo")):
                vals = [getattr(q, f) for q in qs]
                if None not in vals and getattr(y, f) is not None and abs(sum(vals) - getattr(y, f)) > _tol(getattr(y, f), sum(vals)):
                    out.append(_flag("red", y.label, f"Quarters don't add up to YTD ({name.lower()})",
                                     f"{' + '.join(_f(v) for v in vals)} = {_f(sum(vals))} vs. YTD {_f(getattr(y, f))}.", [f]))
    return out


def integrity_flags(periods: list[PeriodData]) -> list[dict]:
    flags = []
    for p in periods:
        if not p.is_empty():
            flags += check_period(p)
    flags += check_series(periods)
    # Same finding in several periods -> one line listing the periods (first period's figures shown).
    merged: dict = {}
    for f in flags:
        k = (f["severity"], f["title"])
        if k in merged:
            merged[k]["periods"].append(f["period"])
        else:
            merged[k] = {**f, "periods": [f["period"]]}
    order = {"red": 0, "review": 1}
    return sorted(merged.values(), key=lambda f: order[f["severity"]])
