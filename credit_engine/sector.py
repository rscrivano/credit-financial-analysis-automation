"""Sector-relative analysis: where the company sits against its sector's public filers.

Tiers per ratio come from the sector's own distribution (data/benchmarks/sector_benchmarks.json):
  Strong = better than the sector's 75th percentile, Normal = middle half, Struggling = worse than 25th.
Values far outside the sector range are flagged as possible input errors. No AI.
"""
from __future__ import annotations

from typing import Optional

from .macro import benchmarks
from .models import PeriodData

LABELS = {"ebitda_margin": ("EBITDA margin", "pct"), "gross_margin": ("Gross margin", "pct"),
          "inventory_turnover": ("Inventory turnover", "x"), "dso": ("Days sales outstanding", "days"),
          "dpo": ("Days payables outstanding", "days"), "current_ratio": ("Current ratio", "x"),
          "debt_to_ebitda": ("Debt / EBITDA", "x"), "ebitda_interest": ("EBITDA / interest", "x"),
          "ffo_to_debt": ("FFO / debt (NI + D&A)", "pct"), "focf_to_debt": ("(CFO − capex) / debt", "pct"),
          "debt_to_capital": ("Debt / capital", "pct"), "ebit_to_capital": ("EBIT / capital", "pct"),
          "revenue_growth": ("Revenue growth", "pct"), "capex_to_revenue": ("Capex / revenue", "pct")}
FIELDS = {"inventory_turnover": ["inventory", "cogs"], "dso": ["receivables", "revenue"], "dpo": ["accounts_payable", "cogs"],
          "current_ratio": ["total_current_assets", "total_current_liabilities"], "gross_margin": ["cogs", "revenue"],
          "ebitda_margin": ["operating_income", "depreciation"], "debt_to_ebitda": ["lt_debt", "st_debt"],
          "ebitda_interest": ["interest_expense"], "capex_to_revenue": ["capex"], "revenue_growth": ["revenue"]}


def sector_options() -> list[dict]:
    return [{"label": s["name"], "value": k} for k, s in sorted(benchmarks()["sectors"].items(), key=lambda kv: kv[1]["name"])]


def sector_key_for_name(name: str) -> Optional[str]:
    for k, s in benchmarks()["sectors"].items():
        if s["name"].lower() == (name or "").strip().lower():
            return k
    return None


def ratios_from_period(p: PeriodData, prior_annual: Optional[PeriodData] = None, growth: Optional[float] = None) -> dict:
    """Same definitions as tools/build_benchmarks.py, on annualized figures."""
    af = 12 / p.months if p.months else 1
    rev = p.revenue * af if p.revenue else None
    if not rev or rev <= 0:
        return {}
    g = lambda v: None if v is None else v * af  # noqa: E731
    oi, da = g(p.operating_income), g(p.get("depreciation")) if p.depreciation is not None else None
    if da is not None:
        da += g(p.get("amortization"))
    cogs, interest = g(p.cogs), g(p.interest_expense)
    debt = None if p.lt_debt is None else p.lt_debt + p.get("st_debt")
    equity = p.total_equity if p.total_equity is not None else (
        None if p.total_assets is None or p.total_liabilities is None else p.total_assets - p.total_liabilities)
    ebitda = None if oi is None or da is None else oi + da
    r = {}
    if ebitda is not None:
        r["ebitda_margin"] = ebitda / rev
    if cogs and cogs > 0:
        r["gross_margin"] = (rev - cogs) / rev
        if p.inventory and p.inventory > 0:
            r["inventory_turnover"] = cogs / p.inventory
        if p.accounts_payable is not None:
            r["dpo"] = p.accounts_payable / cogs * 365
    if p.receivables is not None:
        r["dso"] = p.receivables / rev * 365
    if p.total_current_assets and p.total_current_liabilities:
        r["current_ratio"] = p.total_current_assets / p.total_current_liabilities
    if debt is not None and ebitda and ebitda > 0:
        r["debt_to_ebitda"] = debt / ebitda
    if ebitda is not None and interest and interest > 0:
        r["ebitda_interest"] = ebitda / interest
    if debt and debt > 0:
        if p.net_income is not None and da is not None:
            r["ffo_to_debt"] = (g(p.net_income) + da) / debt
        if p.cfo is not None and p.capex is not None:
            r["focf_to_debt"] = (g(p.cfo) + g(p.capex)) / debt
        if equity is not None and debt + equity > 0:
            r["debt_to_capital"] = debt / (debt + equity)
            if oi is not None:
                r["ebit_to_capital"] = oi / (debt + equity)
    if prior_annual and prior_annual.revenue and p.kind in ("Annual", "LTM"):
        r["revenue_growth"] = rev / prior_annual.revenue - 1
    if growth is not None and "revenue_growth" not in r:
        r["revenue_growth"] = growth
    if p.capex is not None:
        r["capex_to_revenue"] = -g(p.capex) / rev
    return r


def percentile(v: float, b: dict) -> float:
    pts = [(10, b["p10"]), (25, b["p25"]), (50, b["p50"]), (75, b["p75"]), (90, b["p90"])]
    if v <= pts[0][1]:
        return 5.0
    if v >= pts[-1][1]:
        return 95.0
    for (pa, va), (pb, vb) in zip(pts, pts[1:]):
        if va <= v <= vb:
            return pa + (pb - pa) * ((v - va) / (vb - va) if vb != va else 0.5)
    return 50.0


def tier(v: float, b: dict) -> str:
    d = b["direction"]
    if d == "higher":
        return "Strong" if v >= b["p75"] else "Normal" if v >= b["p25"] else "Struggling"
    if d == "lower":
        return "Strong" if v <= b["p25"] else "Normal" if v <= b["p75"] else "Struggling"
    return "Normal" if b["p10"] <= v <= b["p90"] else "Unusual"


def far_outside(v: float, b: dict) -> bool:
    """Far beyond the sector's 10th-90th range: more likely an input error than a weak company."""
    return v > b["p90"] + 2 * (b["p90"] - b["p50"]) or v < b["p10"] - 2 * (b["p50"] - b["p10"])


def analyze_sector(sector_key: Optional[str], p: PeriodData, prior_annual: Optional[PeriodData] = None,
                   growth: Optional[float] = None) -> dict:
    bm = benchmarks()["sectors"].get(sector_key or "")
    if not bm:
        return {"available": False, "reason": "No sector selected." if not sector_key else "Sector not in benchmarks."}
    vals = ratios_from_period(p, prior_annual, growth)
    rows, flags, score = [], [], []
    for k, b in bm["ratios"].items():
        v = vals.get(k)
        name, unit = LABELS[k]
        if v is None:
            rows.append({"key": k, "name": name, "unit": unit, "value": None, "tier": "Data is Missing", **b})
            continue
        t = tier(v, b)
        rows.append({"key": k, "name": name, "unit": unit, "value": v, "tier": t, "percentile": percentile(v, b), **b})
        if t in ("Strong", "Normal", "Struggling") and b["direction"] != "neutral":
            score.append({"Strong": 1, "Normal": 0, "Struggling": -1}[t])
        if far_outside(v, b):
            flags.append({"severity": "review", "period": p.label, "title": f"{name} far outside the sector range",
                          "detail": f"{name} is {fmt(v, unit)} vs. the sector's middle 80% of {fmt(b['p10'], unit)} to "
                                    f"{fmt(b['p90'], unit)}. Verify the inputs before relying on it.",
                          "fields": FIELDS.get(k, [])})
    avg = sum(score) / len(score) if score else None
    overall = None if avg is None else "Strong" if avg > 0.33 else "Struggling" if avg < -0.33 else "Normal"
    scale = bm.get("revenue_scale")
    rev = p.revenue * 12 / p.months if p.revenue and p.months else None
    margin_row = next((r for r in rows if r["key"] == "ebitda_margin" and r["value"] is not None), None)
    return {"available": True, "sector": bm["name"], "companies": bm["companies"], "rows": rows, "flags": flags,
            "overall": overall, "overall_score": avg,
            "scale_percentile": percentile(rev, scale) if rev and scale else None,
            "margin_percentile": margin_row["percentile"] if margin_row else None,
            "recession_2020": bm.get("recession_2020", {})}


def fmt(v, unit):
    if v is None:
        return "–"
    return f"{v:.1%}" if unit == "pct" else f"{v:.0f} days" if unit == "days" else f"{v:.2f}x"


def competitors(sector_key: Optional[str], revenue_annual: Optional[float], company: str = "", n_near: int = 5,
                n_large: int = 3) -> list[dict]:
    """Named public competitors: the n closest in revenue, plus the n largest (leaders), excluding the company."""
    bm = benchmarks()["sectors"].get(sector_key or "", {})
    peers = [p for p in bm.get("peers", []) if p.get("name") and _norm_name(p["name"]) != _norm_name(company)]
    if not peers:
        return []
    out = peers[:n_large]
    if revenue_annual:
        near = sorted(peers, key=lambda p: abs((p["revenue"] or 0) - revenue_annual))
        out += [p for p in near if p not in out][:n_near]
    return out


def _norm_name(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum()).replace("inc", "").replace("corp", "").replace("co", "")
