"""Analyst chat: questions about the analysis on screen, answered only from its computed data.

Token-light by design: a compact context (computed figures plus the analysts' already-verified text),
the last three turns, and the question. The context comes first so the provider's prompt cache can reuse it
across questions; repeated questions are served from the result cache for free.
"""
from __future__ import annotations

import json

from .compare import ROWS, show
from .sector import fmt as sfmt

MAX_TURNS = 1  # the previous question and answer only: enough for a follow-up, far fewer tokens

# Topic routing: every question gets the core (ratings + scorecard); other sections only when the question needs them.
# A question that matches no topic gets everything, so answers stay complete.
TOPICS = {
    "lease": r"lease|adjusted|rent",
    "statements": r"revenue|sales|income|margin|cash|capex|statement|balance|asset|liabilit|equity|ebitda|profit|expense|cost|dividend|tax|interest",
    "history": r"trend|history|over time|previous|prior|quarter|year|period|chang|improv|deteriorat",
    "debt": r"risk|debt|maturit|refinanc|revolver|liquidity|bond|note|borrow|leverage|lever|coupon|due",
    "sector": r"sector|industry|median|tier|quartile",
    "peers": r"peer|competitor|compar|versus|\bvs\b|rival",
    "stress": r"risk|stress|recession|downturn|shock|scenario|downgrade|upgrade|move|sensitiv|fall|drop|breach|worst",
    "macro": r"macro|econom|gdp|inflation|cpi|rates?\b|treasury|spread|unemploy|fed\b|yield",
    "flags": r"flag|concern|assumption|uncertain|red|quality|audit|missing|reliab|trust",
    "case": r"\bcase\b|adjust|projection|my |scenario",
    "text": r"swot|strength|weakness|opportunit|threat|summary|outlook|why|explain|risk|accounting|gaap|view|opinion|think",
}
SECTION_KEYS = {"lease": ["scorecard_lease_adjusted"], "statements": ["statements"], "history": ["rating_history"],
                "debt": ["debt_maturities", "revolver_available", "liquidity_12m"], "sector": ["sector"], "peers": ["peer_median"],
                "stress": ["stress", "reverse_stress_ebitda_drop", "one_notch"], "macro": ["macro"],
                "flags": ["red_flags", "open_assumptions"], "case": ["analyst_case"], "text": ["analyst_text"]}
CORE = ["company", "ticker", "period", "units", "source", "ratings", "scorecard_reported"]


def topics_for(question: str) -> set:
    import re
    q = question.lower()
    return {t for t, pat in TOPICS.items() if re.search(pat, q)}


def select(ctx: dict, question: str) -> dict:
    """Core plus only the sections the question is about (everything if no topic is recognized)."""
    hits = topics_for(question)
    if not hits:
        return ctx
    keep = set(CORE) | {k for t in hits for k in SECTION_KEYS[t]}
    return {k: v for k, v in ctx.items() if k in keep and v not in (None, [], {}, "")}


def _ratio(x):
    if x.get("value") is None:
        return x.get("message") or "n/a"
    return f"{x['value']:.1%}" if "(%)" in x["name"] else f"{x['value']:.2f}x"


def _liq(liq: dict):
    if not liq:
        return None
    r1 = lambda d: {k: round(v) for k, v in (d or {}).items() if isinstance(v, (int, float))}  # noqa: E731
    src = r1(liq.get("sources"))
    if not liq.get("revolver_known"):
        src.pop("Revolver availability", None)  # not disclosed: say so instead of showing 0
    return {"assessment": liq.get("assessment"), "sources": src, "uses": r1(liq.get("uses")),
            "sources_to_uses": None if liq.get("ratio") is None else round(liq["ratio"], 2),
            **({} if liq.get("revolver_known") else {"note": "Revolver availability not disclosed in the XBRL data; sources may be understated"})}


def report_context(r: dict) -> dict:
    p, sp = r.get("primary") or {}, r.get("sp_anchor") or {}
    out = (r.get("team") or {}).get("outputs") or {}
    st, stt = r.get("stress") or {}, r.get("statements") or {}
    per = stt.get("periods", [])
    cols = [c for c in [p.get("label"), next((c for c in per if c.startswith("FY")), None)] if c in per]
    cols = list(dict.fromkeys(cols))
    ds = r.get("debt_structure") or {}
    fr = sp.get("financial_risk")
    w = out.get("writer") or {}
    return {
        "company": r["company"], "ticker": r.get("ticker"), "period": p.get("label"), "units": "US$ millions",
        "source": r.get("data_source"),
        "ratings": {"credit_score_0_100": (r.get("credit_score") or {}).get("score"),
                    "coverage": (r.get("credit_score") or {}).get("coverage_label"),
                    "reported": (p.get("reported") or {}).get("rating"), "lease_adjusted": (p.get("lease_adjusted") or {}).get("rating"),
                    "sp_style_anchor": sp.get("anchor"), "sp_style_final": sp.get("final"), "business_risk": sp.get("business_risk"),
                    "financial_risk": fr.get("category") if isinstance(fr, dict) else fr,
                    "liquidity": (sp.get("liquidity") or {}).get("assessment"),
                    "agency": {a: v["rating"] for a, v in (r.get("agency_ratings") or {}).items()} or "none disclosed"},
        "scorecard_reported": [[x["name"], _ratio(x), x.get("notch"), f"{x['weight']:.0%}"] for x in (p.get("reported") or {}).get("ratios", [])],
        "scorecard_lease_adjusted": [[x["name"], _ratio(x), x.get("notch")] for x in (p.get("lease_adjusted") or {}).get("ratios", [])],
        "statements": {"periods": cols, "rows": [[row["line"], *[row.get(c) for c in cols]] for row in stt.get("rows", [])
                                                 if any(row.get(c) is not None for c in cols)]},
        "rating_history": [[x["label"], x["reported"]["rating"], x["lease_adjusted"]["rating"]] for x in r.get("periods", [])][:8],
        "debt_maturities": ds.get("debt"), "revolver_available": ds.get("revolver_available"),
        "liquidity_12m": _liq((sp.get("liquidity") or {})),
        "sector": {"name": (r.get("sector") or {}).get("sector"), "overall": (r.get("sector") or {}).get("overall"),
                   "ratios": [[x["name"], sfmt(x["value"], x["unit"]) if x["value"] is not None else "n/a", x["tier"],
                               sfmt(x["p50"], x["unit"])] for x in (r.get("sector") or {}).get("rows", [])]},
        "peer_median": {"peers": (r.get("peer_aggregate") or {}).get("names"),
                        "metrics": [[m["name"], m["company"] if m["unit"] == "m" else sfmt(m["company"], m["unit"]),
                                     m["peer_median"] if m["unit"] == "m" else sfmt(m["peer_median"], m["unit"])]
                                    for m in (r.get("peer_aggregate") or {}).get("metrics", [])]},
        "stress": [[s["name"], s.get("reported")] for s in st.get("scenarios", [])],
        "reverse_stress_ebitda_drop": {k: (None if v is None else f"{v:.0%}") for k, v in (st.get("reverse") or {}).items() if k != "note"},
        "one_notch": {k: (v if not isinstance(v, dict) else f"EBITDA {v['ebitda_change']:+.0%} -> {v['to']}")
                      for k, v in (st.get("notch_moves") or {}).items()},
        "macro": [[m["label"], m.get("value"), m.get("year_ago"), m.get("as_of")] for m in (r.get("macro") or []) if m.get("available")],
        "red_flags": [f["title"] for f in r.get("integrity", []) if f.get("severity") == "red"],
        "open_assumptions": [u["title"] for u in r.get("uncertainties", []) if u.get("severity") != "info"][:8],
        "analyst_case": (r.get("analyst_case") or {}).get("case") and {k: r["analyst_case"][k] for k in ("notes", "reported", "case")},
        "analyst_text": {"summary": w.get("executive_summary"), "swot": w.get("swot"), "credit": w.get("credit_section"),
                         "economic": w.get("economic_section"), "sector": w.get("sector_section"),
                         "accounting": w.get("accounting_section")} if w else "AI analyst team not run for this company",
    }


def comparison_context(c: dict) -> dict:
    w = c.get("writeup") or {}
    return {"comparison_of": [f"{m['ticker']} = {m['company']} ({m['period']})" for m in c["metrics"]], "units": "US$ millions",
            "table": [[label, *[show(m.get(k), u) for m in c["metrics"]]] for k, label, u in ROWS],
            "agency": {m["ticker"]: m["agency"] or "none disclosed" for m in c["metrics"]},
            "writeup": {k: w.get(k) for k in ("headline", "overall", "financial", "swot", "economic")},
            "ranking": [[x["rank"], x["company"], x["rationale"]] for x in w.get("ranking", [])]}


def _notch_num(n):
    from .scorecard import Scorecard
    return Scorecard.load().notch_scale.get(n or "", 99)


def _ratios(r, n=3):
    rs = [x for x in ((r.get("primary") or {}).get("reported") or {}).get("ratios", []) if x.get("notch")]
    rs.sort(key=lambda x: _notch_num(x["notch"]))
    fmt = lambda x: f"{x['name']} {_ratio(x)} ({x['notch']}, weight {x['weight']:.0%})"  # noqa: E731
    return [fmt(x) for x in rs[:n]], [fmt(x) for x in rs[::-1][:n]]


def instant_answer(r: dict, question: str):
    """The starter questions are answered from the computed data by code: 0 tokens, same facts."""
    q = " ".join(question.lower().split()).rstrip("?")
    p, sp, cs = r.get("primary") or {}, r.get("sp_anchor") or {}, r.get("credit_score") or {}
    rep, la = (p.get("reported") or {}).get("rating"), (p.get("lease_adjusted") or {}).get("rating")
    best, worst = _ratios(r)
    fr = sp.get("financial_risk")
    fr = fr.get("category") if isinstance(fr, dict) else fr
    if q in ("why did it get this rating", "why this rating"):
        return {"answer": (
            f"The Reported rating is {rep} (credit score {cs.get('score')}, {cs.get('coverage_label', '').lower()}). It is the "
            f"weighted average of the scorecard ratios for {p.get('label')}.\n"
            f"Strongest: {'; '.join(best)}.\nWeakest: {'; '.join(worst)}.\n"
            f"Lease-adjusted is {la}: lease liabilities are added to debt and part of lease cost is treated as interest.\n"
            f"S&P-style (indicative) is {sp.get('final') or '–'}: business risk {sp.get('business_risk') or '–'} × financial "
            f"risk {fr or '–'}, liquidity {(sp.get('liquidity') or {}).get('assessment') or '–'}."),
            "where_to_look": "3 CREDIT"}
    if q == "what would move the rating up or down":
        nm = (r.get("stress") or {}).get("notch_moves") or {}
        rev = (r.get("stress") or {}).get("reverse") or {}
        up, down = nm.get("up"), nm.get("down")
        lines = [f"Up one notch to {up['to']}: EBITDA about {up['ebitda_change']:+.0%}, all else equal." if up else
                 "Up: no realistic EBITDA increase (up to +300%) lifts the Reported rating a notch on its own.",
                 f"Down one notch to {down['to']}: EBITDA about {down['ebitda_change']:+.0%}, all else equal." if down else
                 "Down: EBITDA would have to disappear before the Reported rating moves.",
                 f"Reverse stress: EBITDA can fall {rev['B-']:.0%} before the rating reaches B-." if isinstance(rev.get("B-"), (int, float)) and rev["B-"] else "",
                 f"The weakest ratios hold the score down most: {'; '.join(worst)}.",
                 "Debt reduction, higher margins or lower capex lift these. Test your own view in the Analyst case card."]
        return {"answer": "\n".join(x for x in lines if x), "where_to_look": "3 CREDIT"}
    if q == "how does it compare with its peers":
        agg = r.get("peer_aggregate") or {}
        if not agg.get("names"):
            return None
        better = [m for m in agg["metrics"] if m["better"] is True]
        weaker = [m for m in agg["metrics"] if m["better"] is False]
        show = lambda m: f"{m['name']} {_pv(m, 'company')} vs median {_pv(m, 'peer_median')}"  # noqa: E731
        sec = r.get("sector") or {}
        return {"answer": (
            f"Compared with the median of {len(agg['names'])} public competitors ({', '.join(agg['names'])}):\n"
            f"Better on {len(better)}: {'; '.join(show(m) for m in better) or 'none'}.\n"
            f"Weaker on {len(weaker)}: {'; '.join(show(m) for m in weaker) or 'none'}.\n"
            f"Against all {sec.get('companies', '–')} {sec.get('sector', '')} filers, the overall position is "
            f"{sec.get('overall') or '–'}."), "where_to_look": "7 SECTOR/COMPS"}
    return None


def _pv(m, k):
    v = m.get(k)
    return "–" if v is None else (f"{v:,.0f}m" if m["unit"] == "m" else sfmt(v, m["unit"]))


def ask(model, ai: dict, context: dict, history: list[dict], question: str):
    from .team import ChatAnswer, Team, compact, number_check
    import asyncio
    brief = {"context": select(context, question), "earlier_turns": [[h["q"], h["a"]] for h in history[-MAX_TURNS:]],
             "question": question}
    team = Team(model, "CHAT", ai)
    out = asyncio.run(team.task("chat", ChatAnswer, compact(brief), number_check(brief)))
    return out, team.escalations


def context_size(ctx: dict) -> int:
    return len(json.dumps(ctx, default=str)) // 4  # rough token estimate
