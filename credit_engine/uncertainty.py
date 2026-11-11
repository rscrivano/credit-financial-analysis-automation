"""Assumptions & Uncertainties register.

Every judgment call the app makes is listed here with why it is uncertain, what
it does to the rating (re-scored by code, no tokens), and the options the user
can pick instead. Nothing is silently assumed.

severity: "info" (disclosed), "review" (check this), "decision" (pick an option)
"""
from __future__ import annotations

from typing import Callable, Optional

from .engine import AnalysisResult
from .models import INFINITE, MISSING
from .xbrl_map import EdgarSpread

# Nothing is added to debt automatically: AI-extracted amounts (e.g., a pension figure that may be the
# total obligation rather than the underfunded amount) need the user's call. Agencies usually add these:
AGENCY_USUALLY_ADDS = {"receivables_financing", "pension_opeb"}
DEFAULT_OBS_INCLUDE: dict = {}
CATEGORY_LABEL = {"guarantee": "Guarantees / letters of credit", "purchase_obligation": "Purchase commitments",
                  "unconsolidated_entity": "Unconsolidated entities / JVs", "receivables_financing": "Receivables financing",
                  "pension_opeb": "Pension / OPEB underfunding", "contingency": "Contingencies / litigation",
                  "other_commitment": "Other commitments"}


def _u(id, severity, area, title, detail, options=None, choice_key=None, chosen=None, impact=""):
    return {"id": id, "severity": severity, "area": area, "title": title, "detail": detail,
            "impact": impact, "options": options or [], "choice_key": choice_key, "chosen": chosen}


def _any_source(sp: EdgarSpread, field: str, prefix: str, kinds=None) -> list[str]:
    return [p.label for p in sp.periods if (kinds is None or p.kind in kinds)
            and any(s.startswith(prefix) or prefix in s for s in p.sources.get(field, []))]


def build_uncertainties(res: AnalysisResult, sp: EdgarSpread, choices: dict,
                        rescore: Callable[..., dict], obs: dict, ai: dict) -> list[dict]:
    out = []
    p = res.primary
    if p is None:
        return [_u("no_data", "decision", "Data", "No period could be rated", "SEC data was insufficient.")]
    share = choices.get("lease_interest_share", 1 / 3)

    out.append(_u("benchmarks", "info", "Scorecard", "Scorecard benchmarks",
                  "Ratios are graded against S&P 3-year medians for U.S. industrials (2006-2008), not sector-specific "
                  "medians. Capital-intensive sectors (e.g., airlines) can look weaker on margins and return on capital."))

    # Lease-adjusted basis inputs
    if p.lease_adjusted.rating:
        alt = {s: rescore(lease_interest_share=s)["lease_adjusted"] for s in (0.25, 0.5)}
        matters = any(v != p.lease_adjusted.rating for v in alt.values())
        out.append(_u("lease_interest_share", "decision" if matters else "info", "Leases",
                      "Share of lease cost treated as interest",
                      f"The Lease-adjusted basis treats {share:.0%} of operating lease cost as interest and the rest as "
                      "depreciation (Moody's convention is 1/3). Filings don't state this split.",
                      [{"value": 1 / 3, "label": "1/3, Moody's convention (default)"},
                       {"value": 0.25, "label": f"1/4 -> Lease-adjusted {alt[0.25]}"},
                       {"value": 0.5, "label": f"1/2 -> Lease-adjusted {alt[0.5]}"}],
                      "lease_interest_share", share,
                      f"Lease-adjusted rating: {alt[0.25]} at 1/4, {p.lease_adjusted.rating} at {share:.0%}, {alt[0.5]} at 1/2."
                      + ("" if matters else " No effect on the rating, so no decision is needed.")))
        if p.reported.score is not None and p.lease_adjusted.score < p.reported.score:
            out.append(_u("lease_better", "info", "Leases", "Lease-adjusted rating is better than Reported",
                          "Adding lease cost back to EBITDA can raise EBITDA more than adding lease liabilities raises "
                          "debt, especially when reported EBITDA is weak or negative. This is consistent with agency "
                          "methodology but means the Reported basis is the more conservative view here."))
    est = _any_source(sp, "operating_lease_cost", "Estimate")
    if est:
        out.append(_u("lease_cost_estimate", "review", "Leases", "Operating lease cost estimated for some periods",
                      f"Lease cost isn't tagged for {', '.join(est)}; it was pro-rated from the latest fiscal year "
                      "(a time-based estimate, not a forecast).",
                      [{"value": "on", "label": "Keep the pro-rated estimate (default)"},
                       {"value": "off", "label": "Hide the Lease-adjusted basis"}],
                      "lease_basis", choices.get("lease_basis", "on")))
    cash_basis = _any_source(sp, "operating_lease_cost", "Operating lease cash payments")
    if cash_basis:
        out.append(_u("lease_cash_basis", "info", "Leases", "Lease cash payments used as lease cost",
                      f"For {', '.join(cash_basis)} the filing tags lease cash payments, not lease expense. They are "
                      "usually close but not identical."))
    if p.lease_adjusted.rating is None and p.lease_adjusted.message:
        out.append(_u("lease_missing", "review", "Leases", "Lease-adjusted basis not available", p.lease_adjusted.message))

    # Interest convention
    if _any_source(sp, "interest_expense", "not tagged"):
        out.append(_u("capitalized_interest", "info", "Interest", "Capitalized interest not deducted",
                      "Interest is gross interest minus interest income. Capitalized interest isn't in SEC's standard "
                      "tags for this company, so interest may be higher than under the scorecard's net-interest convention "
                      "(coverage slightly understated)."))

    derived = _any_source(sp, "cfo", "Derived", kinds={"Quarter"})
    if derived:
        out.append(_u("derived_quarters", "info", "Data", "Some quarterly figures are derived",
                      f"Quarterly cash flows for {', '.join(derived)} are year-to-date minus prior year-to-date "
                      "(10-Qs report cash flow year-to-date only)."))
    for n in res.notes:
        out.append(_u("ltm", "info", "Periods", "Trailing-twelve-months view not available", n))

    # Ratio statuses on the primary period
    for basis in (p.reported, p.lease_adjusted):
        inf = [r for r in basis.ratios if r.status == INFINITE]
        if inf:
            out.append(_u(f"infinite_{basis.basis}", "info", "Ratios", f"{basis.basis}: Ratio is Infinite",
                          "; ".join(f"{r.name}: {r.note} Scored {r.notch}." for r in inf)))
        miss = [r for r in basis.ratios if r.status == MISSING]
        if miss and basis.rating:
            debt_hint = (" Debt isn't in SEC's standardized data for this company: enter long-term and short-term debt from "
                         "the 10-K balance sheet in Financials → Detailed → Balance Sheet, then Recalculate."
                         if any("company-specific" in s for pp in sp.periods for s in pp.sources.get("lt_debt", [])) else "")
            out.append(_u(f"missing_{basis.basis}", "decision" if basis.weight_used < 0.9 else "review", "Ratios",
                          f"{basis.basis}: Data is Missing",
                          f"{', '.join(r.name for r in miss)}. {basis.message}{debt_hint}"))
        elif basis.rating is None and basis.ratios:
            hint = (" Debt isn't in SEC's standardized data for this company: enter long-term and short-term debt from "
                    "the 10-K balance sheet in Financials → Detailed → Balance Sheet, then Recalculate."
                    if any("company-specific" in s for pp in sp.periods for s in pp.sources.get("lt_debt", [])) else
                    " Enter the missing figures in Financials → Detailed, then Recalculate.")
            out.append(_u(f"insufficient_{basis.basis}", "decision", "Ratios", f"{basis.basis}: limited information",
                          basis.message + " Missing: " + ", ".join(r.name for r in miss) + "." + hint))

    # Off-balance-sheet
    for cat, d in obs.get("by_category", {}).items():
        label = CATEGORY_LABEL[cat]
        if cat in DEFAULT_OBS_INCLUDE:
            out.append(_u(f"obs_{cat}", "info", "Off-balance sheet", f"{label} added to debt",
                          f"{d['amount']:,.0f} added at 100% (rating-agency practice). Pension amounts are pre-tax."))
        elif d["amount"] > 0:
            included = choices.get("obs_include", {}).get(cat, 0.0)
            alt = rescore(extra_debt=obs["included_total"] + d["amount"] * (1 - included))["obs_adjusted"]
            out.append(_u(f"obs_{cat}", "decision", "Off-balance sheet", f"{label}: count as debt?",
                          f"Found {d['amount']:,.0f} of {label.lower()} (quote verified in the 10-K). "
                          + ("Rating agencies usually add these to debt (for pensions, only the underfunded amount; "
                             "check the quote shows funded status, not total obligation)."
                             if cat in AGENCY_USUALLY_ADDS else
                             "Agencies usually don't treat these as debt unless they are firm and debt-like.")
                          + " Excluded until you choose.",
                          [{"value": 0.0, "label": "Exclude (default)"},
                           {"value": 1.0, "label": f"Include at 100% -> {alt}"}],
                          f"obs_include.{cat}", included, f"Including it gives {alt}."))
    if obs.get("unquantified"):
        out.append(_u("obs_unquantified", "review", "Off-balance sheet", "Items found without a stated amount",
                      "; ".join(obs["unquantified"])[:600] + ". Not added to debt; check the filing."))
    for prob in ai.get("problems", []):
        out.append(_u("ai_check", "review", "AI checks", "An AI output failed a check", prob))
    low = [i["description"] for i in obs.get("items", []) if i.get("confidence") == "low"]
    if low:
        out.append(_u("obs_low_conf", "review", "Off-balance sheet", "Low-confidence items", "; ".join(low)[:500]))
    if not ai.get("enabled"):
        out.append(_u("ai_off", "info", "AI", "AI sections skipped", ai.get("reason", "AI was not run.")))
    return out


def extra_uncertainties(sec: dict, spv: dict, stress: dict | None, meta: dict, choices: dict,
                        sector_key: str | None) -> list[dict]:
    """Sector, S&P-style anchor and stress-test judgment calls."""
    from .sector import sector_options
    out = []
    opts = [{"value": o["value"], "label": o["label"]} for o in sector_options()]
    if not sector_key:
        out.append(_u("sector", "decision", "Sector", "Pick the company's sector",
                      "Sector benchmarks, the business-risk suggestion and the recession scenario need a sector.",
                      opts, "sector", None))
    else:
        how = (f"from its SEC industry code {meta.get('sic')} ({meta.get('sic_description')})" if meta.get("sic")
               else "as entered" if meta.get("sector") == sector_key and not choices.get("sector") else "as selected")
        out.append(_u("sector", "info", "Sector", f"Sector: {sec.get('sector', sector_key)}",
                      f"Set {how}. Benchmarks come from {sec.get('companies', 0)} public filers in this sector "
                      "(fiscal 2025, SEC data). Change it with the sector dropdown."))
        if sec.get("available") and sec.get("companies", 0) < 20:
            out.append(_u("sector_thin", "review", "Sector", "Small benchmark sample",
                          f"Only {sec['companies']} public companies in this sector; percentiles are less reliable."))
        if sec.get("available"):
            out.append(_u("sector_interest", "info", "Sector", "Coverage vs. sector uses different interest bases",
                          "Peers' EBITDA/interest uses gross interest expense from SEC data; the company's uses "
                          "the scorecard's net interest, which can make the company look slightly stronger."))
    if spv:
        sug = spv.get("business_suggestion", {})
        out.append(_u("business_risk", "decision", "S&P-style anchor", "Business risk profile (analyst judgment)",
                      "S&P sets this from industry risk and competitive position by judgment. Suggested: "
                      f"{sug.get('rule', 'not enough data')}",
                      [{"value": b, "label": b + (" (suggested)" if b == sug.get("suggested") else "")}
                       for b in spv.get("options", [])], "business_risk", spv.get("business_risk")))
        fin = spv.get("financial_risk", {})
        if fin.get("disagree"):
            out.append(_u("fin_rule", "decision", "S&P-style anchor", "Core ratios point to different financial risk",
                          f"FFO/debt says {fin.get('ffo_cat')}, debt/EBITDA says {fin.get('lev_cat')}. S&P resolves "
                          "this with supplementary ratios and judgment.",
                          [{"value": "weaker", "label": "Use the weaker (default, conservative)"},
                           {"value": "stronger", "label": "Use the stronger"},
                           {"value": "middle", "label": "Use the middle"}], "fin_risk_rule", spv.get("fin_rule")))
        tbl = spv.get("table", "standard")
        out.append(_u("volatility_table", "decision", "S&P-style rating", f"Ratio scale: {tbl} volatility table",
                      "S&P grades FFO/debt and debt/EBITDA on a looser scale for very stable industries (low: regulated "
                      "utilities) and moderately stable ones (medial: e.g., food & beverage, consumer staples, telecom). "
                      "The app assigns the table by sector; change it if this company's cash flows are more or less stable.",
                      [{"value": "standard", "label": "Standard (most industries)"},
                       {"value": "medial", "label": "Medial (stable, non-cyclical)"},
                       {"value": "low", "label": "Low (regulated utilities)"}], "volatility_table", tbl))
        netted = (spv.get("adjusted") or {}).get("surplus_cash_netted")
        out.append(_u("cash_netting", "decision", "S&P-style rating", "Surplus cash in adjusted debt",
                      "S&P subtracts only *surplus* cash (beyond operating needs) from debt. Without a reliable way to "
                      "measure surplus cash from filings, the default is not to net cash (conservative).",
                      [{"value": "off", "label": "Don't net cash (default)"},
                       {"value": "on", "label": "Net all cash & short-term investments"}],
                      "cash_netting", "on" if netted else "off"))
        liq = spv.get("liquidity") or {}
        if liq.get("assessment") == "Undetermined":
            out.append(_u("liquidity_undetermined", "review", "S&P-style rating", "Liquidity assessment undetermined",
                          "Revolver availability isn't in the filing's standard data, so liquidity sources are understated "
                          "and no liquidity cap is applied. Check the credit-facility note."))
        out.append(_u("sp_modifiers", "info", "S&P-style rating", "Modifiers applied and not applied",
                      "Applied: S&P-adjusted debt (leases, after-tax pension deficit, optional cash netting), sector "
                      "volatility table, financial-sponsor policy (if answered in the questionnaire) and the liquidity cap. "
                      "Not modeled: comparable-ratings analysis, diversification, management/governance, group/government "
                      "support, normalization of one-off items, and deconsolidation of captive finance subsidiaries."))
    if stress:
        if not stress.get("floating_known"):
            out.append(_u("floating", "decision", "Stress test", "Floating-rate share of debt unknown",
                          "The rate shock is shown at 0%, 50% and 100% floating. Pick the actual share if known.",
                          [{"value": 0.0, "label": "0% (all fixed)"}, {"value": 0.5, "label": "50%"},
                           {"value": 1.0, "label": "100% (all floating)"}], "floating_share", None))
        out.append(_u("stress_2020", "info", "Stress test", "Recession scenario is the sector's actual 2020",
                      "The recession case applies the sector's median 2020 revenue and operating-margin change from "
                      "SEC data. 2020 was a pandemic shock, so for travel and hospitality it is an extreme case rather "
                      "than a typical downturn."))
        out.append(_u("stress_tax", "info", "Stress test", "Shocks carry no tax shield",
                      "EBITDA and interest shocks reduce net income and operating cash flow one-for-one "
                      "(conservative)."))
    return out
