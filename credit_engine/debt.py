"""Debt structure and S&P-style liquidity (code only).

Debt maturities, lease payment schedules, revolver availability, fair value and pension funded
status come from the 10-K's standardized XBRL disclosures (the debt and lease footnotes).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

BUCKETS = [("Y1", "Next 12 months"), ("Y2", "Year 2"), ("Y3", "Year 3"), ("Y4", "Year 4"), ("Y5", "Year 5"), ("After5", "Thereafter")]
DEBT_TAGS = {"Y1": "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths", "Y2": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
             "Y3": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree", "Y4": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour",
             "Y5": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive", "After5": "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"}
OPL = {"Y1": "LesseeOperatingLeaseLiabilityPaymentsDueNextTwelveMonths", "Y2": "LesseeOperatingLeaseLiabilityPaymentsDueYearTwo",
       "Y3": "LesseeOperatingLeaseLiabilityPaymentsDueYearThree", "Y4": "LesseeOperatingLeaseLiabilityPaymentsDueYearFour",
       "Y5": "LesseeOperatingLeaseLiabilityPaymentsDueYearFive", "After5": "LesseeOperatingLeaseLiabilityPaymentsDueAfterYearFive"}
FINL = {k: v.replace("LesseeOperatingLeaseLiability", "FinanceLeaseLiability") for k, v in OPL.items()}
SINGLE = {"revolver_capacity": ["LineOfCreditFacilityMaximumBorrowingCapacity"],
          "revolver_available": ["LineOfCreditFacilityRemainingBorrowingCapacity"],
          "fair_value": ["LongTermDebtFairValue", "DebtInstrumentFairValue"],
          "total_ltd": ["LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities", "LongTermDebt", "DebtInstrumentCarryingAmount"],
          "commercial_paper": ["CommercialPaper"], "secured": ["SecuredDebt"], "unsecured": ["UnsecuredDebt"],
          "pension_funded": ["DefinedBenefitPlanFundedStatusOfPlan"],
          "pension_liability": ["PensionAndOtherPostretirementDefinedBenefitPlansLiabilitiesNoncurrent",
                                "DefinedBenefitPensionPlanLiabilitiesNoncurrent"]}
RATE_TAGS = ["LongTermDebtWeightedAverageInterestRate", "DebtWeightedAverageInterestRate"]


def _latest_instant(idx, tag: str):
    facts = idx.inst.get(tag, {})
    if not facts:
        return None, None
    d = max(facts)
    return facts[d]["val"] / 1e6, d


def debt_structure(idx, facts_json: Optional[dict] = None) -> dict:
    """Latest maturity ladder and related debt disclosures, with the date and tag of each figure."""
    out: dict = {"sources": {}}
    for name, tags in (("debt", DEBT_TAGS), ("op_lease", OPL), ("fin_lease", FINL)):
        vals, dates = {}, set()
        for k, tag in tags.items():
            v, d = _latest_instant(idx, tag)
            if v is not None:
                vals[k], _ = v, dates.add(d)
        if vals:
            as_of = max(dates)
            vals = {k: (_latest_instant_on(idx, tags[k], as_of)) for k in tags}
            out[name] = {k: v for k, v in vals.items() if v is not None}
            out["sources"][name] = f"10-K maturity table (XBRL), as of {as_of}"
            out.setdefault("as_of", str(as_of))
    for k, tags in SINGLE.items():
        for tag in tags:
            v, d = _latest_instant(idx, tag)
            if v is not None:
                out[k] = v
                out["sources"][k] = f"us-gaap:{tag} as of {d}"
                break
    if facts_json:  # rates are unit 'pure', not USD
        gaap = facts_json.get("facts", {}).get("us-gaap", {})
        for tag in RATE_TAGS:
            xs = [x for x in gaap.get(tag, {}).get("units", {}).get("pure", []) if "start" not in x]
            if xs:
                x = max(xs, key=lambda x: (x["end"], x["filed"]))
                out["weighted_rate"] = x["val"]
                out["sources"]["weighted_rate"] = f"us-gaap:{tag} as of {x['end']}"
                break
    d = out.get("debt")
    if d and "After5" not in d and out.get("total_ltd"):
        rest = out["total_ltd"] - sum(d.values())
        if rest > 0:
            d["After5"] = rest
            out["after5_derived"] = True
    return out


def _latest_instant_on(idx, tag, on: date):
    f = idx.inst.get(tag, {}).get(on)
    return None if f is None else f["val"] / 1e6


def ladder_total(lad: Optional[dict]) -> float:
    return sum((lad or {}).values())


LIQ = [(2.0, "Exceptional"), (1.5, "Strong"), (1.2, "Adequate"), (1.0, "Less than adequate"), (0.0, "Weak")]


def liquidity(p, ds: dict, ffo_annual: Optional[float]) -> dict:
    """S&P-style sources / uses over the next 12 months (simplified: no committed-facility covenant test)."""
    cash = p.cash or 0.0
    rev = ds.get("revolver_available")
    af = 12 / p.months if p.months else 1
    ffo = max(ffo_annual or 0.0, 0.0)
    y1 = (ds.get("debt") or {}).get("Y1")
    debt_due = y1 if y1 is not None else (p.st_debt or 0.0)
    lease_due = (ds.get("fin_lease") or {}).get("Y1", 0.0)
    capex = -(p.capex or 0.0) * af
    divs = -(p.dividends or 0.0) * af
    sources = {"Cash & short-term investments": cash, "Revolver availability": rev or 0.0, "Funds from operations (12m)": ffo}
    uses = {"Debt maturities (12m)": debt_due, "Finance-lease payments (12m)": lease_due, "Capital expenditures (12m)": max(capex, 0.0),
            "Dividends / distributions (12m)": max(divs, 0.0)}
    s, u = sum(sources.values()), sum(uses.values())
    ratio = s / u if u > 0 else None
    label = "Exceptional" if ratio is None else next(lbl for lim, lbl in LIQ if ratio >= lim)
    return {"sources": sources, "uses": uses, "ratio": ratio, "assessment": label,
            "basis": "debt maturity table" if y1 is not None else "short-term debt on the balance sheet",
            "revolver_known": rev is not None}
