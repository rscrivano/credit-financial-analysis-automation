"""End-to-end run for public (ticker) or private (uploaded statements) companies.

Cheapest first; AI only where code can't do the job:
  1. Data: SEC XBRL facts (public) or the user's confirmed statements (private) -> spread    (code)
  2. User edits to the statements applied as tracked overrides                                (code)
  3. Ratings, sector, S&P-style anchor, stress, macro/micro data, data-integrity flags        (code)
  4. Accounting Analyst reads the 10-K/10-Q or statement-notes excerpt                         (AI)
  5. Off-balance-sheet decisions, Assumptions & Uncertainties                                  (code)
  6. Credit, Macro and Micro analysts in parallel -> Manager review -> Report Writer            (AI)
Every AI task: compact brief, 3-try cap, escalation to the Manager, run token budget, cache.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from typing import Optional

from .accounting import accounting_flags
from .edgar import EdgarError, company_facts, lookup, sector_for_sic, submissions
from .engine import DEFAULT_LEASE_INTEREST_SHARE, analyze, coverage_label, credit_score, score_period
from .agency import find_ratings, manual, merge
from .filings import filing_paragraphs, get_excerpt
from .integrity import integrity_flags
from .llm import LLMUnavailable, get_model, model_name
from .macro import industry_panel, macro_panel
from .models import BALANCE_FIELDS, FLOW_FIELDS
from .scorecard import Scorecard
from .sector import LABELS as SECTOR_LABELS
from .sector import analyze_sector, competitors, fmt, ratios_from_period, sector_key_for_name
from .debt import liquidity
from .sp_method import (BUSINESS_RISK, FINANCIAL_RISK, LIQUIDITY_CAPS, SECTOR_VOLATILITY, anchor, cap_rating,
                        financial_risk_table, suggest_business_risk, supplementary)
from .stress import analyst_case, run_stress
from .team import AccountingReview, Team, compact, quote_check, run_rest
from .uncertainty import DEFAULT_OBS_INCLUDE, build_uncertainties, extra_uncertainties
from .workbook_import import load_template_workbook, template_meta
from .xbrl_map import EdgarSpread, build_spread

STATEMENT_LINES = [  # (field, label) in display order
    ("revenue", "Revenue"), ("cogs", "Cost of goods sold"), ("sga", "SG&A"), ("depreciation", "Depreciation & amortization"),
    ("operating_income", "Operating income"), ("interest_expense", "Interest expense, net"), ("tax_expense", "Income tax"),
    ("net_income", "Net income"), ("cfo", "Operating cash flow"), ("capex", "Capital expenditures"),
    ("deferred_taxes", "Deferred taxes (cash flow)"), ("dividends", "Dividends / distributions"),
    ("cfi", "Net cash from investing"), ("cff", "Net cash from financing"), ("debt_issued", "Debt issued"),
    ("debt_repaid", "Debt repaid"), ("buybacks", "Share buybacks"),
    ("capex_gross", "Purchases of PP&E (gross)"), ("asset_sales", "Proceeds from asset sales"), ("acquisitions", "Acquisitions"),
    ("divestitures", "Divestitures"), ("inv_purchases", "Purchases of investments"), ("inv_sales", "Sales / maturities of investments"),
    ("cash", "Cash & equivalents"), ("receivables", "Accounts receivable"), ("inventory", "Inventory"),
    ("total_current_assets", "Total current assets"), ("fixed_assets", "PP&E, net"), ("goodwill", "Goodwill"),
    ("other_intangibles", "Other intangibles"), ("total_assets", "Total assets"), ("accounts_payable", "Accounts payable"),
    ("st_debt", "Short-term debt & current maturities"), ("total_current_liabilities", "Total current liabilities"),
    ("lt_debt", "Long-term debt"), ("deferred_tax_liability", "Deferred tax liability"),
    ("operating_lease_liabilities", "Operating lease liabilities"), ("operating_lease_cost", "Operating lease cost"),
    ("total_liabilities", "Total liabilities"), ("total_equity", "Shareholders' equity"),
]


# ---------- entry points ----------

def run(ticker: str, *, use_ai: bool = True, choices: Optional[dict] = None, model=None, run_analysts: bool = True,
        ai_cache_only: bool = False,
        overrides: Optional[dict] = None, **_) -> dict:
    """Public company: ticker -> SEC data -> full report."""
    t, cik, _ = lookup(ticker)
    facts, source = company_facts(cik)
    try:
        spread = build_spread(facts)
    except ValueError as e:
        raise EdgarError(str(e)) from e
    meta = {"mode": "public"}
    try:
        sub = submissions(cik)
        meta.update(sic=sub.get("sic"), sic_description=sub.get("sicDescription"), sector=sector_for_sic(sub.get("sic")))
    except EdgarError:
        pass
    return _assemble(spread, t, cik, source, use_ai=use_ai, choices=choices, model=model, ai_cache_only=ai_cache_only,
                     run_analysts=run_analysts, meta=meta, overrides=overrides)


def run_workbook(path: str, *, choices: Optional[dict] = None, use_ai: bool = True, model=None,
                 run_analysts: bool = True, overrides: Optional[dict] = None, **_) -> dict:
    """A workbook in Ryan's template layout (kept for the logic test and existing spreads)."""
    company, periods = load_template_workbook(path)
    tm = template_meta(path)
    meta = {"mode": "private", "sector": sector_key_for_name(tm["sector_name"]), "agency_rating": tm["agency_rating"],
            "floating_share": tm["floating_rate_share"], "quality": "per period"}
    return run_periods(company, periods, meta=meta, choices=choices, use_ai=use_ai, model=model,
                       run_analysts=run_analysts, source="uploaded workbook", overrides=overrides)


def run_periods(company: str, periods, *, meta: dict, choices=None, use_ai=True, model=None, run_analysts=True,
                source="uploaded statements", overrides: Optional[dict] = None, **_) -> dict:
    """Private company: confirmed statements -> report. Balance-sheet-only columns become opening balances."""
    rated = [p for p in periods if p.revenue is not None or p.net_income is not None]
    openings = [p for p in periods if p not in rated and p.total_assets is not None]
    return _assemble(EdgarSpread(company, None, rated, openings, []), "PRIVATE", None, source, use_ai=use_ai,
                     choices=choices, model=model, run_analysts=run_analysts, meta={"mode": "private", **meta},
                     overrides=overrides)


# ---------- helpers ----------

def _apply_overrides(sp: EdgarSpread, overrides: Optional[dict]) -> list[dict]:
    """User edits from the statements screen: {period label: {field: value}}. Recorded, never hidden."""
    edits = []
    for p in sp.periods + sp.openings:
        for field, val in (overrides or {}).get(p.label, {}).items():
            if field not in FLOW_FIELDS + BALANCE_FIELDS:
                continue
            old = getattr(p, field)
            new = None if val in (None, "") else float(val)
            if old != new:
                setattr(p, field, new)
                p.sources[field] = [f"Edited by user (was {old if old is not None else 'blank'})"]
                edits.append({"period": p.label, "field": field, "old": old, "new": new})
    return edits


def statements_table(sp: EdgarSpread) -> dict:
    cols = sorted(sp.periods, key=lambda p: (p.kind != "Annual", -p.period_end.toordinal()))
    rows = []
    for f, label in STATEMENT_LINES:
        vals = {p.label: getattr(p, f) for p in cols}  # every standard line, so blanks can be filled in the app
        rows.append({"field": f, "line": label, **{k: (None if v is None else round(v, 1)) for k, v in vals.items()}})
    return {"periods": [p.label for p in cols], "kinds": {p.label: f"{p.kind} · {p.quality}" for p in cols}, "rows": rows}


def _obs_summary(items: list[dict], choices: dict) -> dict:
    by_cat: dict = {}
    seen, unquantified = set(), []
    for it in items:
        if it.get("already_on_balance_sheet"):
            continue
        if it.get("amount_musd") is None:
            unquantified.append(f"{it['description']} ({it['category']})")
            continue
        k = (it["category"], round(it["amount_musd"]))
        if k in seen:
            continue
        seen.add(k)
        by_cat.setdefault(it["category"], {"amount": 0.0, "items": []})
        by_cat[it["category"]]["amount"] += it["amount_musd"]
        by_cat[it["category"]]["items"].append(it["description"])
    include = {**DEFAULT_OBS_INCLUDE, **choices.get("obs_include", {})}
    total = sum(d["amount"] * include.get(c, 0.0) for c, d in by_cat.items())
    return {"items": items, "by_category": by_cat, "included_total": total, "unquantified": unquantified}


def _r(v):
    return None if v is None else round(v, 2)


def fmt_val(v, unit):
    return None if v is None else fmt(v, unit)


def _sp_anchor(p, sec: dict, choices: dict, p_in=None, ds: Optional[dict] = None, sector_key: Optional[str] = None) -> dict:
    """S&P-style indicative rating: S&P-adjusted debt (leases + after-tax pension deficit - surplus cash), core ratios on the
    sector's volatility table, business x financial risk anchor, then modifiers (financial policy, liquidity cap)."""
    if p is None:
        return {}
    ds = ds or {}
    basis = p.lease_adjusted if p.lease_adjusted.rating else p.reported
    rat = {r.key: r for r in basis.ratios}
    af = 12 / p.months if p.months else 1
    debt_b = basis.total_debt
    ebitda_ann = basis.ebitda * af if basis.ebitda is not None else None
    ffo_r = rat.get("ffo_to_debt")
    ffo_ann = ffo_r.value * debt_b if ffo_r and ffo_r.value is not None and debt_b else None
    if ffo_ann is None and p_in is not None and p_in.net_income is not None:
        ffo_ann = (p_in.net_income + (p_in.depreciation or 0.0) + p_in.get("amortization") + p_in.get("deferred_taxes")) * af
    sponsor = str((choices.get("micro") or {}).get("sponsor_owned", "")).lower() == "yes"
    pension = None
    if ds.get("pension_funded") is not None and ds["pension_funded"] < 0:
        pension = -ds["pension_funded"] * 0.79
    elif ds.get("pension_liability"):
        pension = ds["pension_liability"] * 0.79
    net_cash = choices.get("cash_netting", "off") == "on" and not sponsor  # default: no netting (only surplus cash qualifies)
    cash = (p_in.cash or 0.0) if (p_in is not None and net_cash) else 0.0
    adj_debt = None if debt_b is None else max(debt_b + (pension or 0.0) - cash, 0.0)
    ffo_adj = None if ffo_ann is None or adj_debt is None else (9.99 if adj_debt == 0 else ffo_ann / adj_debt)
    neg = ebitda_ann is not None and ebitda_ann <= 0
    lev_adj = None if adj_debt is None or ebitda_ann is None or neg else adj_debt / ebitda_ann
    table = choices.get("volatility_table") or SECTOR_VOLATILITY.get(sector_key or "", "standard")
    rule = choices.get("fin_risk_rule") or ("ffo" if table == "low" else "weaker")  # S&P leans on FFO/debt for utilities
    fin = financial_risk_table(ffo_adj, lev_adj, neg, rule, table)
    if sponsor:  # S&P: financial-sponsor ownership (FS-6) -> highly leveraged financial risk
        fin = {**fin, "category": FINANCIAL_RISK[5], "index": 5, "sponsor_override": True}
    sug = suggest_business_risk(sec.get("scale_percentile"), sec.get("margin_percentile"),
                                (sec.get("recession_2020") or {}).get("revenue_change_p50"))
    business = choices.get("business_risk") or sug.get("suggested")
    anc = anchor(business, fin.get("index"))
    supp, liq = [], {}
    if p_in is not None and adj_debt:
        cfo_a = None if p_in.cfo is None else p_in.cfo * af
        cap_a = p_in.get("capex") * af
        div_a = p_in.get("dividends") * af
        gi = getattr(p_in, "gross_interest", None)
        int_a = gi if gi else p_in.interest_expense
        int_a = None if int_a is None else int_a * af
        supp = supplementary({
            "cfo_to_debt": None if cfo_a is None else cfo_a / adj_debt,
            "focf_to_debt": None if cfo_a is None else (cfo_a + cap_a) / adj_debt,
            "dcf_to_debt": None if cfo_a is None else (cfo_a + cap_a + div_a) / adj_debt,
            "ffo_cash_interest": None if not int_a or int_a <= 0 or ffo_ann is None else (ffo_ann + int_a) / int_a,
            "ebitda_interest": None if not int_a or int_a <= 0 or ebitda_ann is None else ebitda_ann / int_a})
    if p_in is not None:
        liq = liquidity(p_in, ds, ffo_ann)
    if liq and not liq.get("revolver_known") and liq.get("assessment") in LIQUIDITY_CAPS:
        liq["assessment"] = "Undetermined"  # revolver availability not disclosed: sources likely understated, so no cap
    cap = LIQUIDITY_CAPS.get(liq.get("assessment"))
    final = cap_rating(anc, cap)
    return {"basis": basis.basis, "ffo_to_debt": ffo_adj, "debt_to_ebitda": lev_adj, "ebitda_negative": neg,
            "financial_risk": fin, "business_suggestion": sug, "business_risk": business,
            "business_overridden": bool(choices.get("business_risk")), "fin_rule": rule, "table": table,
            "anchor": anc, "final": final, "cap": cap, "liquidity": liq, "supplementary": supp, "sponsor": sponsor,
            "adjusted": {"reported_basis_debt": debt_b, "pension_after_tax": pension, "surplus_cash_netted": cash,
                         "adjusted_debt": adj_debt, "ebitda_12m": ebitda_ann, "ffo_12m": ffo_ann},
            "options": BUSINESS_RISK}


QUESTIONS = {
    "top_customer_pct": "Largest customer share of revenue (%)",
    "top_supplier_pct": "Largest supplier share of purchases (%)",
    "recurring_pct": "Recurring / contracted revenue (%)",
    "pricing_power": "Can pass cost increases to customers?",
    "sponsor_owned": "Owned by a private equity sponsor?",
}


def _micro_flags(m: dict) -> list[dict]:
    out = []

    def num(k):
        try:
            return float(m.get(k)) if m.get(k) not in (None, "") else None
        except (TypeError, ValueError):
            return None
    c, s, rec = num("top_customer_pct"), num("top_supplier_pct"), num("recurring_pct")
    if c is not None and c >= 20:
        out.append({"severity": "review", "title": "Customer concentration",
                    "detail": f"Largest customer is {c:.0f}% of revenue; losing it would hit EBITDA directly."})
    if s is not None and s >= 30:
        out.append({"severity": "review", "title": "Supplier dependence", "detail": f"Largest supplier is {s:.0f}% of purchases."})
    if rec is not None and rec < 25:
        out.append({"severity": "review", "title": "Little recurring revenue",
                    "detail": f"Only {rec:.0f}% of revenue is recurring or contracted; cash flow is more volatile."})
    if str(m.get("pricing_power", "")).lower() == "no":
        out.append({"severity": "review", "title": "No pricing power",
                    "detail": "Cost inflation can't be passed on; margins are exposed to input costs."})
    if str(m.get("sponsor_owned", "")).lower() == "yes":
        out.append({"severity": "info", "title": "Sponsor-owned",
                    "detail": "S&P generally views financial-sponsor ownership as an aggressive financial policy, which "
                              "can cap the rating below what the ratios alone suggest."})
    return out


def _peer_rows(sector_key, p_in, company, growth=None):
    rev = p_in.revenue * 12 / p_in.months if p_in and p_in.revenue and p_in.months else None
    keys = ["ebitda_margin", "gross_margin", "debt_to_ebitda", "ebitda_interest", "dso", "inventory_turnover",
            "current_ratio", "revenue_growth"]
    me = ratios_from_period(p_in, None, growth) if p_in else {}
    rows = [{"name": f"{company} (this company)", "revenue": None if rev is None else round(rev),
             **{k: fmt_val(me.get(k), SECTOR_LABELS[k][1]) for k in keys}}]
    comps = competitors(sector_key, rev, company)
    for c in comps:
        rows.append({"name": c["name"], "revenue": round(c["revenue"]),
                     **{k: fmt_val(c.get(k), SECTOR_LABELS[k][1]) for k in keys}})
    import statistics
    agg = {"names": [c["name"] for c in comps], "metrics": []}
    for k in ["revenue"] + keys:
        vals = [c.get(k) for c in comps if c.get(k) is not None]
        mine = rev if k == "revenue" else me.get(k)
        med = statistics.median(vals) if vals else None
        direction = "higher" if k in ("ebitda_margin", "gross_margin", "ebitda_interest", "inventory_turnover", "current_ratio",
                                      "revenue_growth") else "lower" if k in ("debt_to_ebitda", "dso") else None
        better = None if mine is None or med is None or direction is None else (mine > med if direction == "higher" else mine < med)
        unit = "m" if k == "revenue" else SECTOR_LABELS[k][1]
        agg["metrics"].append({"key": k, "name": "Revenue (US$ m)" if k == "revenue" else SECTOR_LABELS[k][0], "unit": unit,
                               "company": mine, "peer_median": med, "n": len(vals), "better": better})
    rows.insert(1, {"name": f"Peer median ({len(comps)} companies)", "revenue": None if agg["metrics"][0]["peer_median"] is None
                    else round(agg["metrics"][0]["peer_median"]),
                    **{m["key"]: fmt_val(m["peer_median"], m["unit"]) for m in agg["metrics"][1:]}})
    return rows, keys, agg


# ---------- the run ----------

def _assemble(sp: EdgarSpread, t: str, cik, source: str, *, use_ai: bool, choices: Optional[dict], model=None,
              run_analysts: bool = True, meta: Optional[dict] = None, overrides: Optional[dict] = None,
              ai_cache_only: bool = False) -> dict:
    meta, choices = meta or {}, choices or {}
    edits = _apply_overrides(sp, overrides)
    share = float(choices.get("lease_interest_share", DEFAULT_LEASE_INTEREST_SHARE))
    res = analyze(sp.company, sp.periods, lease_interest_share=share, openings=sp.openings)
    sc = Scorecard.load()
    p, p_in, p_open = res.primary, res.primary_input, res.primary_opening

    ai = {"enabled": False, "reason": "", "usage": [], "problems": [], "model": None, "tasks": [], "analysts_skipped": False}
    team, model_supplied = None, model is not None
    if use_ai:
        try:
            model = model or get_model()
            ai.update(enabled=True, model=model_name())
            team = Team(model, t, ai, cache_only=ai_cache_only)
        except LLMUnavailable as e:
            ai["reason"] = str(e)

    # Source text for the Accounting Analyst: 10-K/10-Q excerpt (public) or statement notes (private)
    excerpt, src_text, src_label, filing = None, "", "", None
    if cik is not None:
        try:
            excerpt = get_excerpt(cik)
            src_text, src_label = excerpt.text, f"{excerpt.form} filed {excerpt.filed}"
            filing = {"form": excerpt.form, "accession": excerpt.accession, "filed": excerpt.filed, "url": excerpt.url,
                      "excerpt_tokens_est": len(excerpt.text) // 4}
            if excerpt.removed_injections:
                ai["problems"].append(f"Removed {len(excerpt.removed_injections)} sentence(s) from the filing text that "
                                      "looked like instructions to an AI (prompt-injection screen).")
        except (EdgarError, OSError) as e:
            ai["problems"].append(f"Could not read the latest filing ({e}).")
    else:
        src_text = meta.get("notes_excerpt", "")
        src_label = f"notes to the {meta.get('quality', '').lower() or 'provided'} financial statements"

    # S&P / Moody's / Fitch as disclosed in the company's own filings (10-Q read last so the newer statement wins);
    # ratings the user enters override them.
    agency: dict = {}
    if cik is not None:
        for forms in (("10-K",), ("10-Q",)):
            try:
                fm, paras, _ = filing_paragraphs(cik, forms)
                agency = merge(find_ratings(paras, f"{fm['form']} filed {fm['filed']}"), agency)
            except (EdgarError, OSError):
                pass
    agency.update(manual(choices.get("agency_ratings")))

    integrity = integrity_flags(sp.periods)
    accounting = None
    if team and src_text and run_analysts:
        brief = (f"Company: {sp.company}. Source: {src_label}. Statement type: {meta.get('quality', 'SEC filing')}. "
                 f"Data checks: {compact([f['title'] for f in integrity][:8])}. Units: {meta.get('unit_note', 'US$ millions')}."
                 f"\n<source_excerpt>\n{src_text}\n</source_excerpt>")
        accounting = asyncio.run(team.task("accounting", AccountingReview, brief, quote_check(src_text)))
    acc = accounting.model_dump() if accounting else (choices.get("_prev_accounting") or None)
    items = (acc or {}).get("obs_items", [])
    risks = (acc or {}).get("qualitative_risks", [])

    obs = _obs_summary(items, choices)

    def rescore(lease_interest_share: float = share, extra_debt: float = 0.0) -> dict:
        if p_in is None:
            return {}
        q = replace(p_in, lt_debt=(p_in.lt_debt or 0.0) + extra_debt) if extra_debt else p_in
        r = score_period(q, p_open, sc, lease_interest_share)
        return {"reported": r.reported.rating, "lease_adjusted": r.lease_adjusted.rating,
                "obs_adjusted": (r.lease_adjusted.rating or r.reported.rating) if extra_debt else None, "result": r}

    obs_basis = None
    if obs["included_total"] > 0:
        rr = rescore(extra_debt=obs["included_total"])["result"]
        b = rr.lease_adjusted if rr.lease_adjusted.rating else rr.reported
        obs_basis = {**asdict(b), "basis": f"{b.basis} + off-balance-sheet", "added_debt": obs["included_total"]}

    flags = accounting_flags(sp.periods, excerpt.keyword_flags if excerpt else meta.get("text_flags", {}))
    uncertainties = build_uncertainties(res, sp, choices, rescore, obs, ai)

    sector_key = choices.get("sector") or meta.get("sector")
    prior = None
    if p_in is not None:
        prior = next((q for q in sp.periods if q.kind == "Annual" and q.revenue
                      and abs((p_in.period_end - q.period_end).days - 365) <= 20), None)
    growth = None
    if p_in is not None and prior is None:  # LTM/YTD: compare the latest YTD with the same months a year earlier
        ytds = sorted((q for q in sp.periods if q.kind in ("YTD", "Quarter") and q.revenue), key=lambda q: q.period_end, reverse=True)
        for y in ytds:
            py = next((q for q in sp.periods if q.kind == y.kind and q.months == y.months and q.revenue
                       and abs((y.period_end - q.period_end).days - 365) <= 10), None)
            if py:
                growth = y.revenue / py.revenue - 1
                break
    sec = analyze_sector(sector_key, p_in, prior, growth) if p_in is not None else {"available": False, "flags": []}
    integrity += [{**f, "periods": [f["period"]]} for f in sec.get("flags", [])]
    sp_view = _sp_anchor(p, sec, choices, p_in, sp.debt, sector_key)
    stress = None
    if p_in is not None:
        floating = choices.get("floating_share", meta.get("floating_share"))
        stress = run_stress(p_in, p_open, sc, share, None if floating is None else float(floating),
                            sec.get("recession_2020", {}) if sec.get("available") else {}, p.ebitda.ebitda)
    case = analyst_case(p_in, p_open, sc, share, choices["analyst_case"]) if p_in is not None and choices.get("analyst_case") else None
    macro = macro_panel()
    industry = industry_panel(sector_key) if sector_key else []
    micro = _micro_flags(choices.get("micro", {}))
    peers, peer_keys, peer_agg = _peer_rows(sector_key, p_in, sp.company, growth) if sec.get("available") else ([], [], {})
    uncertainties += extra_uncertainties(sec, sp_view, stress, meta, choices, sector_key)
    if edits:
        uncertainties.append({"id": "user_edits", "severity": "review", "area": "Statements",
                              "title": f"You edited {len(edits)} value(s)",
                              "detail": "; ".join(f"{e['period']} {e['field']}: {e['old']} → {e['new']}" for e in edits)[:600],
                              "impact": "Ratings and checks reflect your edits.", "options": [], "choice_key": None, "chosen": None})
    if choices.get("lease_basis") == "off" and p:
        p.lease_adjusted.rating = None
        p.lease_adjusted.message = "Hidden by user choice."

    # ---------- analysts (Credit, Macro, Micro in parallel) -> Manager -> Writer ----------
    team_out = {"outputs": {"accounting": acc}, "escalations": [], "tokens_spent": 0}
    if team and p is not None and run_analysts:
        def show(r):
            if r.value is None:
                return r.message or "n/a"
            return f"{r.value:.1%}" if "(%)" in r.name else f"{r.value:.2f}x"
        credit = {"company": sp.company, "period": p.label, "units": "US$ millions",
                  "ratings": {"credit_score_0_100": credit_score(p.reported.score), "reported_rating": p.reported.rating,
                              "information_coverage": f"{p.reported.weight_used:.0%} ({coverage_label(p.reported.weight_used)})",
                              "lease_adjusted_rating": p.lease_adjusted.rating,
                              "sp_style_anchor": sp_view.get("anchor"), "sp_style_indicative": sp_view.get("final"),
                              "sp_liquidity": (sp_view.get("liquidity") or {}).get("assessment"),
                              "agency_ratings_disclosed": {a: v["rating"] + (f", {v['outlook']} outlook" if v.get("outlook") else "")
                                                           for a, v in agency.items()} or "none disclosed"},
                  "ebitda": None if p.ebitda.ebitda is None else f"{p.ebitda.ebitda:,.0f}",
                  "ratios": [[r.name, show(r), r.notch] for r in p.reported.ratios],
                  "lease_adjusted_ratios": [[r.name, show(r), r.notch] for r in p.lease_adjusted.ratios],
                  "sector_tiers": [[r["name"], fmt_val(r["value"], r["unit"]), r["tier"]] for r in sec.get("rows", [])],
                  "stress": stress and [[s["name"], s["reported"]] for s in stress["scenarios"]],
                  "reverse_stress": stress and {k: (None if v is None else f"{v:.0%}") for k, v in (stress.get("reverse") or {}).items()
                                                if k != "note"},
                  "data_red_flags": [f["title"] for f in integrity if f["severity"] == "red"],
                  "gaap_findings": [[g["topic"], g["severity"]] for g in (acc or {}).get("gaap_findings", [])],
                  "off_balance_sheet": [[i["category"], i["amount_musd"]] for i in items][:6]}
        macro_b = {"company": sp.company, "sector": sec.get("sector"),
                   "macro": [[m["label"], _r(m.get("value")), _r(m.get("year_ago")), _r(m.get("change")), m.get("as_of")]
                             for m in macro if m.get("available")],
                   "columns": "indicator, latest, year ago, change, as of",
                   "industry": [[i["key"], _r(i.get("value")), _r(i.get("pct_change")), i.get("as_of")] for i in industry if i.get("available")],
                   "sector_2020_recession": sec.get("recession_2020"),
                   "rate_shock": stress and [[s["name"], s["reported"]] for s in stress["scenarios"]]}
        micro_b = {"company": sp.company, "sector": sec.get("sector"), "sector_companies": sec.get("companies"),
                   "overall_vs_sector": sec.get("overall"), "metrics": peer_keys, "company_and_competitors": peers,
                   "sector_median": {r["name"]: fmt_val(r.get("p50"), r["unit"]) for r in sec.get("rows", [])},
                   "questionnaire": choices.get("micro", {}), "questionnaire_flags": [m["title"] for m in micro]}
        briefs = {"credit": compact(credit), "macro": compact(macro_b), "micro": compact(micro_b)}
        if not model_supplied:  # fresh API client for the second event loop
            team.model = get_model()
        team_out = run_rest(team, briefs, {"red_flags": credit["data_red_flags"]}, acc)
    elif team and not run_analysts:
        ai["analysts_skipped"] = True

    tot = {k: sum(u.get(k, 0) for u in ai["usage"]) for k in ("input_tokens", "cached_input_tokens", "output_tokens")}
    return {
        "ticker": t, "cik": cik, "company": sp.company, "data_source": source, "choices": choices, "meta": meta,
        "primary": p and asdict(p), "periods": [asdict(r) for r in res.periods],
        "obs_adjusted": obs_basis, "off_balance_sheet": obs, "risks": risks, "flags": flags,
        "uncertainties": uncertainties, "integrity": integrity, "edits": edits,
        "statements": statements_table(sp), "source_excerpt": src_text, "source_label": src_label, "filing": filing,
        "sector_key": sector_key, "sector": sec, "sp_anchor": sp_view, "stress": stress, "macro": macro,
        "industry": industry, "micro": micro, "peers": peers, "peer_keys": peer_keys, "peer_aggregate": peer_agg,
        "team": team_out, "ai": {**ai, "totals": tot},
        "agency_rating": choices.get("agency_rating") or meta.get("agency_rating") or "", "agency_ratings": agency,
        "debt_structure": sp.debt, "analyst_case": case,
        "credit_score": p and {"score": credit_score(p.reported.score), "rating": p.reported.rating,
                               "coverage": p.reported.weight_used, "coverage_label": coverage_label(p.reported.weight_used),
                               "missing": [r.name for r in p.reported.ratios if r.status == "missing"]},
        "sources": {pp.label: pp.sources for pp in sp.periods},
    }
