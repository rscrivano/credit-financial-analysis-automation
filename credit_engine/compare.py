"""Side-by-side comparison of several public companies.

Each company runs through the normal pipeline with code-only maths and cached AI work only (no new
analyst calls), then one AI call writes the comparison. Without AI, a code-written comparison is used.
"""
from __future__ import annotations

from typing import Optional

from .edgar import EdgarError
from .sector import LABELS, fmt

MAX_COMPANIES = 10  # soft cap: each company is a SEC pull; keeps cost and rate limits sane
RATING_ORDER = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-",
                "CCC+", "CCC", "CCC-", "CC", "C", "D"]
PEER_KEYS = ["ebitda_margin", "gross_margin", "debt_to_ebitda", "ebitda_interest", "current_ratio", "revenue_growth", "dso"]
HIGHER = {"credit_score", "ebitda_margin", "gross_margin", "ebitda_interest", "current_ratio", "revenue_growth",
          "ffo_to_debt_adj", "revenue", "reverse_ebitda_drop"}
LOWER = {"debt_to_ebitda", "dso", "debt_to_ebitda_adj", "due_2y_pct", "red_flags"}


def _rank(rating: Optional[str]) -> int:
    return RATING_ORDER.index(rating) if rating in RATING_ORDER else 99


def company_metrics(r: dict) -> dict:
    """Numbers used across the comparison table, brief and narrative (all from the deterministic engine)."""
    agg = {m["key"]: m["company"] for m in (r.get("peer_aggregate") or {}).get("metrics", [])}
    sp, cs, ds = r.get("sp_anchor") or {}, r.get("credit_score") or {}, r.get("debt_structure") or {}
    lad = ds.get("debt") or {}
    due2 = (lad.get("Y1", 0) + lad.get("Y2", 0)) / sum(lad.values()) if lad and sum(lad.values()) > 0 else None
    rev = (r.get("stress") or {}).get("reverse") or {}
    p = r.get("primary") or {}
    return {
        "company": r["company"], "ticker": r.get("ticker"), "period": p.get("label"),
        "credit_score": cs.get("score"), "coverage": cs.get("coverage_label"),
        "reported_rating": (p.get("reported") or {}).get("rating"),
        "lease_adjusted_rating": (p.get("lease_adjusted") or {}).get("rating"),
        "sp_style": sp.get("final"), "sp_anchor": sp.get("anchor"), "business_risk": sp.get("business_risk"),
        "financial_risk": (sp.get("financial_risk") or {}).get("category") if isinstance(sp.get("financial_risk"), dict) else sp.get("financial_risk"), "liquidity": (sp.get("liquidity") or {}).get("assessment"),
        "agency": {a: v["rating"] for a, v in (r.get("agency_ratings") or {}).items()},
        "revenue": agg.get("revenue"), **{k: agg.get(k) for k in PEER_KEYS},
        "ffo_to_debt_adj": sp.get("ffo_to_debt"), "debt_to_ebitda_adj": sp.get("debt_to_ebitda"),
        "due_2y_pct": due2, "reverse_ebitda_drop": rev.get("B-"),
        "sector": (r.get("sector") or {}).get("sector"), "sector_position": (r.get("sector") or {}).get("overall"),
        "red_flags": sum(1 for f in r.get("integrity", []) if f.get("severity") == "red"),
    }


ROWS = [("credit_score", "Credit score (0–100)", "int"), ("reported_rating", "Reported rating", "txt"),
        ("lease_adjusted_rating", "Lease-adjusted rating", "txt"), ("sp_style", "S&P-style (indicative)", "txt"),
        ("business_risk", "Business risk", "txt"), ("financial_risk", "Financial risk", "txt"),
        ("liquidity", "Liquidity", "txt"), ("revenue", "Revenue, annualized (US$ m)", "m"),
        *[(k, LABELS[k][0], LABELS[k][1]) for k in PEER_KEYS],
        ("ffo_to_debt_adj", "FFO / adjusted debt", "pct"), ("debt_to_ebitda_adj", "Adjusted debt / EBITDA", "x"),
        ("due_2y_pct", "Debt due within 2 years", "pct"), ("reverse_ebitda_drop", "EBITDA drop before B- (reverse stress)", "pct"),
        ("sector_position", "Position vs sector", "txt"), ("red_flags", "Data red flags", "int")]


def show(v, unit) -> str:
    if v is None:
        return "–"
    if unit == "txt":
        return str(v)
    if unit == "int":
        return f"{v:.0f}"
    if unit == "m":
        return f"{v:,.0f}"
    return fmt(v, unit)


def best_of(metrics: list[dict], key: str):
    vals = [(m[key], m["company"]) for m in metrics if isinstance(m.get(key), (int, float))]
    if len(vals) < 2 or key not in HIGHER | LOWER:
        return None
    pick = (max if key in HIGHER else min)(vals)
    return None if sum(1 for v, _ in vals if v == pick[0]) > 1 else pick[1]  # ties have no single best


def ranking(metrics: list[dict]) -> list[dict]:
    """Deterministic ranking: credit score, then S&P-style rating."""
    order = sorted(metrics, key=lambda m: (-(m["credit_score"] or -1), _rank(m["sp_style"])))
    return [{"company": m["company"], "rank": i + 1,
             "rationale": f"Credit score {show(m['credit_score'], 'int')}, reported {m['reported_rating'] or '–'}, "
                          f"S&P-style {m['sp_style'] or '–'}, debt/EBITDA {show(m['debt_to_ebitda'], 'x')}."}
            for i, m in enumerate(order)]


def code_writeup(metrics: list[dict], reports: list[dict]) -> dict:
    """Plain comparison written by code (used when AI is off or unavailable)."""
    rk = ranking(metrics)
    top, low = rk[0]["company"], rk[-1]["company"]
    fin = []
    for key, label, unit in ROWS:
        b = best_of(metrics, key)
        if b and key not in ("credit_score", "red_flags"):
            vals = ", ".join(f"{m['company']} {show(m.get(key), unit)}" for m in metrics)
            fin.append(f"{label}: best is {b} ({vals}).")
    sw = []
    for r in reports:
        rows = (r.get("sector") or {}).get("rows", [])
        strong = [x["name"] for x in rows if x.get("tier") == "Strong"][:3]
        weak = [x["name"] for x in rows if x.get("tier") == "Struggling"][:3]
        sw.append(f"{r['company']}: strengths vs sector – {', '.join(strong) or 'none stand out'}; "
                  f"weaknesses – {', '.join(weak) or 'none stand out'}.")
    eco = []
    for r in reports:
        sec = r.get("sector") or {}
        rec = sec.get("recession_2020") or {}
        eco.append(f"{r['company']} ({sec.get('sector') or 'sector not set'}): "
                   + (f"sector revenue moved {rec["revenue_change_p50"]:.0%} in the 2020 recession. " if isinstance(rec.get("revenue_change_p50"), (int, float)) else "")
                   + f"Liquidity {(r.get('sp_anchor') or {}).get('liquidity', {}).get('assessment', '–') if isinstance((r.get('sp_anchor') or {}).get('liquidity'), dict) else '–'}.")
    return {"headline": f"{top} ranks strongest and {low} weakest of the {len(metrics)} companies on credit quality.",
            "overall": " ".join(f"{x['rank']}. {x['company']}: {x['rationale']}" for x in rk),
            "financial": " ".join(fin), "swot": " ".join(sw),
            "economic": " ".join(eco) + " All companies face the same macro backdrop shown in the Macro tab.",
            "ranking": rk, "source": "code"}


def _r(v):
    return round(v, 2) if isinstance(v, float) else v


def _recession(r) -> dict:
    rec = (r.get("sector") or {}).get("recession_2020") or {}
    pc = lambda v: None if v is None else f"{v:.0%}"
    return {"sector_revenue_change": pc(rec.get("revenue_change_p50")),
            "sector_operating_margin_change": None if rec.get("op_margin_change_p50") is None else
            f"{rec['op_margin_change_p50'] * 100:.1f} pts"}


def brief(metrics: list[dict], reports: list[dict]) -> dict:
    comp = []
    for m, r in zip(metrics, reports):
        w = (((r.get("team") or {}).get("outputs") or {}).get("writer") or {})
        rows = (r.get("sector") or {}).get("rows", [])
        comp.append({**{k: show(m.get(k), u) for k, u in [(k, u) for k, _, u in ROWS]},
                     "company": m["company"], "period": m["period"], "agency": m["agency"] or "none disclosed",
                     "swot": w.get("swot") or {"strong_vs_sector": [x["name"] for x in rows if x.get("tier") == "Strong"],
                                               "weak_vs_sector": [x["name"] for x in rows if x.get("tier") == "Struggling"]},
                     "sector_2020_recession": _recession(r),
                     "stress": [[s["name"], s["reported"]] for s in ((r.get("stress") or {}).get("scenarios") or [])][:3]})
    macro = [[x["label"], _r(x.get("value")), _r(x.get("year_ago")), x.get("as_of")]
             for x in (reports[0].get("macro") or []) if x.get("available")]
    return {"companies": comp, "macro": macro, "units": "US$ millions; ratios as shown"}


def run_comparison(tickers: list[str], *, use_ai: bool = True, model=None, choices: Optional[dict] = None) -> dict:
    from . import pipeline
    seen, todo = set(), []
    for t in tickers:
        t = (t or "").strip().upper()
        if t and t not in seen:
            seen.add(t)
            todo.append(t)
    todo = todo[:MAX_COMPANIES]
    reports, errors = {}, {}
    for t in todo:
        try:
            reports[t] = pipeline.run(t, use_ai=use_ai, model=model, choices=dict(choices or {}), ai_cache_only=True)
        except EdgarError as e:
            errors[t] = str(e)
    ok = [reports[t] for t in todo if t in reports and reports[t].get("primary")]
    metrics = [company_metrics(r) for r in ok]
    out = {"tickers": [r["ticker"] for r in ok], "errors": errors, "metrics": metrics, "rows": ROWS, "ai": {"usage": [], "tasks": []},
           "best": {k: best_of(metrics, k) for k, _, _ in ROWS}, "reports": {r["ticker"]: r for r in ok}}
    if len(ok) < 2:
        out["writeup"] = None
        return out
    out["writeup"] = code_writeup(metrics, ok)
    if use_ai:
        from .llm import get_model
        try:
            m = model or get_model()
        except Exception:  # no key configured: keep the code-written comparison
            m = None
        if m is not None:
            w, esc = __import__("credit_engine.team", fromlist=["write_comparison"]).write_comparison(
                m, out["ai"], brief(metrics, ok), run_id="CMP-" + "-".join(out["tickers"]))
            if w:
                out["writeup"] = {**w, "source": "ai"}
            out["ai"]["escalations"] = esc
    return out
