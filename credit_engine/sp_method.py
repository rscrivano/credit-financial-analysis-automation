"""S&P-style anchor rating: business risk profile x financial risk profile.

Follows the structure of S&P Global Ratings' corporate methodology (2013):
  * Financial risk from the two core ratios (FFO/debt, debt/EBITDA), standard-volatility table.
  * Anchor from the business-risk x financial-risk matrix.
The business risk profile (industry risk + competitive position) is analyst judgment at
S&P. Here the app SUGGESTS one from data (sector benchmarks), shows the rule it used, and
the user can override it. Modifiers (diversification, liquidity, governance, group
support) are not applied and are listed as an uncertainty.
"""
from __future__ import annotations

from typing import Optional

FINANCIAL_RISK = ["Minimal", "Modest", "Intermediate", "Significant", "Aggressive", "Highly leveraged"]
BUSINESS_RISK = ["Excellent", "Strong", "Satisfactory", "Fair", "Weak", "Vulnerable"]

# Standard volatility: (FFO/debt lower bound %, debt/EBITDA upper bound x) per financial risk category.
STANDARD_VOLATILITY = [(60, 1.5), (45, 2.0), (30, 3.0), (20, 4.0), (12, 5.0), (None, None)]

ANCHOR = {  # business risk -> anchors by financial risk (Minimal .. Highly leveraged)
    "Excellent":    ["aaa/aa+", "aa", "a+/a", "a-", "bbb", "bbb-/bb+"],
    "Strong":       ["aa/aa-", "a+/a", "a-/bbb+", "bbb", "bb+", "bb"],
    "Satisfactory": ["a/a-", "bbb+", "bbb/bbb-", "bbb-/bb+", "bb", "b+"],
    "Fair":         ["bbb/bbb-", "bbb-", "bb+", "bb", "bb-", "b"],
    "Weak":         ["bb+", "bb+", "bb", "bb-", "b+", "b/b-"],
    "Vulnerable":   ["bb-", "bb-", "bb-/b+", "b+", "b", "b-"],
}


def ffo_category(ffo_to_debt: Optional[float]) -> Optional[int]:
    if ffo_to_debt is None:
        return None
    pct = ffo_to_debt * 100
    for i, (lo, _) in enumerate(STANDARD_VOLATILITY[:-1]):
        if pct > lo:
            return i
    return 5


def leverage_category(debt_to_ebitda: Optional[float], ebitda_negative: bool = False) -> Optional[int]:
    if ebitda_negative:
        return 5
    if debt_to_ebitda is None:
        return None
    for i, (_, hi) in enumerate(STANDARD_VOLATILITY[:-1]):
        if debt_to_ebitda < hi:
            return i
    return 5


def financial_risk(ffo_to_debt, debt_to_ebitda, ebitda_negative=False, rule="weaker") -> dict:
    a, b = ffo_category(ffo_to_debt), leverage_category(debt_to_ebitda, ebitda_negative)
    cats = [c for c in (a, b) if c is not None]
    if not cats:
        return {"category": None, "ffo_cat": a, "lev_cat": b, "disagree": False}
    cat = max(cats) if rule == "weaker" else (min(cats) if rule == "stronger" else round(sum(cats) / len(cats)))
    return {"category": FINANCIAL_RISK[cat], "index": cat, "ffo_cat": FINANCIAL_RISK[a] if a is not None else None,
            "lev_cat": FINANCIAL_RISK[b] if b is not None else None, "disagree": a is not None and b is not None and a != b}


def suggest_business_risk(scale_pctile: Optional[float], margin_pctile: Optional[float],
                          sector_drawdown: Optional[float]) -> dict:
    """Transparent rule (not S&P's): average of the company's sector percentiles for scale (revenue)
    and profitability (EBITDA margin), capped for cyclical sectors (2020 median revenue drop > 20%)."""
    vals = [v for v in (scale_pctile, margin_pctile) if v is not None]
    if not vals:
        return {"suggested": None, "rule": "Not enough data to suggest a business risk profile."}
    avg = sum(vals) / len(vals)
    idx = 5 if avg < 15 else 4 if avg < 35 else 3 if avg < 55 else 2 if avg < 75 else 1 if avg < 92 else 0
    capped = False
    if sector_drawdown is not None and sector_drawdown < -0.20 and idx < 2:
        idx, capped = 2, True
    rule = (f"Average sector percentile of scale and EBITDA margin = {avg:.0f} → {BUSINESS_RISK[idx]}"
            + (" (capped at Satisfactory: the sector's median revenue fell "
               f"{sector_drawdown:.0%} in 2020, a cyclical industry)" if capped else "") + ".")
    return {"suggested": BUSINESS_RISK[idx], "score": avg, "rule": rule}


def anchor(business: Optional[str], fin_index: Optional[int]) -> Optional[str]:
    if business is None or fin_index is None:
        return None
    return ANCHOR[business][fin_index].upper().replace("/", " / ")


# ---------- closer to S&P: volatility tables, supplementary ratios, modifiers ----------
# Core-ratio thresholds by volatility table: (FFO/debt lower bound %, debt/EBITDA upper bound x) per category.
VOLATILITY_TABLES = {
    "standard": [(60, 1.5), (45, 2.0), (30, 3.0), (20, 4.0), (12, 5.0), (None, None)],
    "medial": [(50, 1.75), (35, 2.5), (23, 3.5), (13, 4.5), (9, 5.5), (None, None)],
    "low": [(35, 2.0), (23, 3.0), (13, 4.0), (9, 5.0), (6, 6.0), (None, None)],
}
# The app's mapping of sectors to S&P volatility tables (low = regulated utilities; medial = stable, non-cyclical sectors).
SECTOR_VOLATILITY = {"utilities": "low", "food_bev": "medial", "consumer_products": "medial", "telecom_media": "medial",
                     "healthcare_services": "medial"}
# Supplementary ratios (standard table): lower bounds per category Minimal..Aggressive; below the last = Highly leveraged.
SUPPLEMENTARY = {"cfo_to_debt": ("CFO / debt (%)", [50, 35, 25, 15, 10]),
                 "focf_to_debt": ("Free operating cash flow / debt (%)", [40, 25, 15, 10, 5]),
                 "dcf_to_debt": ("Discretionary cash flow / debt (%)", [25, 15, 10, 5, 2]),
                 "ffo_cash_interest": ("(FFO + cash interest) / cash interest (x)", [13, 9, 6, 4, 2]),
                 "ebitda_interest": ("EBITDA / interest (x)", [15, 10, 6, 3, 2])}
NOTCHES = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C"]


def financial_risk_table(ffo_to_debt, debt_to_ebitda, ebitda_negative=False, rule="weaker", table="standard") -> dict:
    tb = VOLATILITY_TABLES[table]
    a = None if ffo_to_debt is None else next((i for i, (lo, _) in enumerate(tb[:-1]) if ffo_to_debt * 100 > lo), 5)
    b = 5 if ebitda_negative else (None if debt_to_ebitda is None else
                                   next((i for i, (_, hi) in enumerate(tb[:-1]) if debt_to_ebitda < hi), 5))
    cats = [c for c in (a, b) if c is not None]
    if not cats:
        return {"category": None, "index": None, "ffo_cat": None, "lev_cat": None, "disagree": False, "table": table}
    if rule == "ffo" and a is not None:
        idx = a
    else:
        idx = max(cats) if rule in ("weaker", "ffo") else (min(cats) if rule == "stronger" else round(sum(cats) / len(cats)))
    return {"category": FINANCIAL_RISK[idx], "index": idx, "ffo_cat": None if a is None else FINANCIAL_RISK[a],
            "lev_cat": None if b is None else FINANCIAL_RISK[b], "disagree": a is not None and b is not None and a != b,
            "table": table}


def supplementary(values: dict) -> list[dict]:
    out = []
    for k, (name, bounds) in SUPPLEMENTARY.items():
        v = values.get(k)
        if v is None:
            out.append({"key": k, "name": name, "value": None, "category": "Data is Missing"})
            continue
        x = v * 100 if "(%)" in name else v
        idx = next((i for i, lo in enumerate(bounds) if x > lo), 5)
        out.append({"key": k, "name": name, "value": v, "category": FINANCIAL_RISK[idx]})
    return out


def cap_rating(rating_range: Optional[str], cap: Optional[str]) -> Optional[str]:
    """Apply a ceiling to an anchor like 'BBB / BBB-'."""
    if not rating_range or not cap:
        return rating_range
    parts = [x.strip() for x in rating_range.split("/")]
    capped = [x if NOTCHES.index(x) >= NOTCHES.index(cap) else cap for x in parts if x in NOTCHES]
    capped = list(dict.fromkeys(capped))
    return " / ".join(capped) if capped else rating_range


LIQUIDITY_CAPS = {"Less than adequate": "BB+", "Weak": "B-"}
