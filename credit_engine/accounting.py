"""Accounting red flags, computed by rules (no LLM). Framed as items for review."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import PeriodData


@dataclass
class Flag:
    id: str
    severity: str  # "review" or "info"
    title: str
    detail: str
    evidence: str = ""


def _annual(periods: list[PeriodData]) -> list[PeriodData]:
    return sorted((p for p in periods if p.kind == "Annual"), key=lambda p: p.period_end, reverse=True)


def accounting_flags(periods: list[PeriodData], text_flags: dict | None = None) -> list[dict]:
    flags: list[Flag] = []
    fy = _annual(periods)
    if fy:
        cur = fy[0]
        prev = fy[1] if len(fy) > 1 else None
        # Accruals (Sloan): earnings running well ahead of cash.
        if None not in (cur.net_income, cur.cfo, cur.total_assets):
            avg_ta = (cur.total_assets + prev.total_assets) / 2 if prev and prev.total_assets else cur.total_assets
            acc = (cur.net_income - cur.cfo) / avg_ta
            if acc > 0.10:
                flags.append(Flag("accruals", "review", "High accruals",
                                  f"{cur.label}: (net income - operating cash flow) / avg assets = {acc:.1%}, above 10%.",
                                  "Earnings are not converting to cash."))
        if cur.net_income is not None and cur.cfo is not None and cur.net_income > 0 and cur.cfo < 0:
            flags.append(Flag("cash_vs_income", "review", "Profit without cash",
                              f"{cur.label}: net income {cur.net_income:,.0f} but operating cash flow {cur.cfo:,.0f}."))
        # Receivables growing much faster than revenue (DSO jump).
        if prev and None not in (cur.receivables, cur.revenue, prev.receivables, prev.revenue) and prev.revenue and cur.revenue:
            dso_c, dso_p = cur.receivables / cur.revenue * 365, prev.receivables / prev.revenue * 365
            if dso_p > 0 and dso_c / dso_p - 1 > 0.25:
                flags.append(Flag("dso", "review", "Receivables growing faster than sales",
                                  f"Days sales outstanding rose from {dso_p:.0f} to {dso_c:.0f} days ({cur.label})."))
    for p in periods[:1] + fy[:1]:
        if p.total_assets is not None and p.total_liabilities is not None and p.total_assets - p.total_liabilities <= 0:
            flags.append(Flag("negative_equity", "review", "Negative equity",
                              f"{p.label}: liabilities exceed assets by {p.total_liabilities - p.total_assets:,.0f}."))
            break
    titles = {"going_concern": "Going-concern doubt disclosed", "material_weakness": "Material weakness in controls",
              "restatement": "Restatement disclosed"}
    for k, ev in (text_flags or {}).items():
        flags.append(Flag(k, "review", titles.get(k, k), "Found in the latest 10-K text.", ev[:400]))
    return [asdict(f) for f in flags]
