"""Map SEC XBRL company facts onto the spread template's lines.

Every number keeps its source (XBRL tag, form, filing date, accession number),
or a note when it was derived (e.g., Q4 = full year - 9 months) or estimated.

Conventions follow Ryan's template:
  * interest expense is net: gross interest - capitalized interest - interest income
  * capex is net of proceeds from asset sales, and negative
  * cash includes short-term investments
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from .models import PeriodData

Value = tuple[Optional[float], list[str]]


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _src(tag: str, f: dict) -> str:
    return f"us-gaap:{tag} — {f.get('form')} filed {f.get('filed')} (FY{f.get('fy')} {f.get('fp')}, accn {f.get('accn')})"


class FactIndex:
    """Latest-filed USD value for each (tag, period)."""

    def __init__(self, facts_json: dict):
        self.entity = facts_json.get("entityName", "")
        self.cik = facts_json.get("cik")
        self.dur: dict[str, dict[tuple[date, date], dict]] = defaultdict(dict)
        self.inst: dict[str, dict[date, dict]] = defaultdict(dict)
        for tag, body in facts_json.get("facts", {}).get("us-gaap", {}).items():
            for x in body.get("units", {}).get("USD", []):
                end = _d(x["end"])
                if "start" in x:
                    key, bucket = (_d(x["start"]), end), self.dur[tag]
                else:
                    key, bucket = end, self.inst[tag]
                if key not in bucket or x["filed"] > bucket[key]["filed"]:
                    bucket[key] = x

    def duration(self, tag: str, start: date, end: date) -> Value:
        facts = self.dur.get(tag, {})
        f = facts.get((start, end))
        if f is not None:
            return f["val"] / 1e6, [_src(tag, f)]
        # Derive from year-to-date figures: [s0, end] - [s0, start - 1 day]
        prior_end = start - timedelta(days=1)
        for (s0, e), longer in facts.items():
            if e == end and s0 < start and (s0, prior_end) in facts:
                shorter = facts[(s0, prior_end)]
                return ((longer["val"] - shorter["val"]) / 1e6,
                        [f"Derived: {_src(tag, longer)} minus {_src(tag, shorter)}"])
        return None, []

    def instant(self, tag: str, end: date) -> Value:
        f = self.inst.get(tag, {}).get(end)
        return (f["val"] / 1e6, [_src(tag, f)]) if f else (None, [])


# --- field resolvers -------------------------------------------------------

def _first(getter: Callable[[str], Value], tags: list[str]) -> tuple[Optional[float], list[str], Optional[str]]:
    for t in tags:
        v, s = getter(t)
        if v is not None:
            return v, s, t
    return None, [], None


REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"]
DA = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
      "DepreciationAmortizationAndAccretionNet", "Depreciation"]
GROSS_INTEREST = ["InterestExpenseNonoperating", "InterestExpense", "InterestExpenseDebt"]
NET_INTEREST = ["InterestIncomeExpenseNonoperatingNet", "InterestIncomeExpenseNet"]  # income - expense
INTEREST_INCOME = ["InvestmentIncomeInterest", "InterestIncomeOther", "InvestmentIncomeInterestAndDividend"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]

SIMPLE_FLOWS = {
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "tax_expense": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "deferred_taxes": ["DeferredIncomeTaxExpenseBenefit", "DeferredIncomeTaxesAndTaxCredits"],
    "operating_lease_cost": ["OperatingLeaseCost"],
    "cfi": ["NetCashProvidedByUsedInInvestingActivities", "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"],
    "cff": ["NetCashProvidedByUsedInFinancingActivities", "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"],
    "debt_issued": ["ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt", "ProceedsFromIssuanceOfSeniorLongTermDebt",
                    "ProceedsFromDebtNetOfIssuanceCosts", "ProceedsFromLongTermLinesOfCredit", "ProceedsFromLinesOfCredit"],
}
INVESTING = [  # (field, tags, sign): payments stored as negative cash flows
    ("acquisitions", ["PaymentsToAcquireBusinessesNetOfCashAcquired", "PaymentsToAcquireBusinessesGross"], -1),
    ("divestitures", ["ProceedsFromDivestitureOfBusinessesNetOfCashDivested", "ProceedsFromDivestitureOfBusinesses"], 1),
    ("inv_purchases", ["PaymentsToAcquireShortTermInvestments", "PaymentsToAcquireInvestments", "PaymentsToAcquireMarketableSecurities",
                       "PaymentsToAcquireAvailableForSaleSecuritiesDebt", "PaymentsToAcquireEquityMethodInvestments"], -1),
    ("inv_sales", ["ProceedsFromSaleOfShortTermInvestments", "ProceedsFromSaleMaturityAndCollectionsOfInvestments",
                   "ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
                   "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt"], 1),
]
REPAY = ["RepaymentsOfLongTermDebt", "RepaymentsOfDebt", "RepaymentsOfLongTermDebtAndCapitalSecurities",
         "RepaymentsOfLongTermDebtAndCapitalLeaseObligations", "RepaymentsOfSeniorDebt", "RepaymentsOfLongTermLinesOfCredit",
         "RepaymentsOfLinesOfCredit"]
SIMPLE_BALANCE = {
    "total_assets": ["Assets"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent", "AccountsAndOtherReceivablesNetCurrent",
                    "AccountsNotesAndLoansReceivableNetCurrent", "AccountsReceivableGrossCurrent"],
    "total_current_assets": ["AssetsCurrent"],
    "fixed_assets": ["PropertyPlantAndEquipmentNet"],
    "goodwill": ["Goodwill"],
    "other_intangibles": ["IntangibleAssetsNetExcludingGoodwill"],
    "accounts_payable": ["AccountsPayableCurrent", "AccountsPayableTradeCurrent", "AccountsPayableAndAccruedLiabilitiesCurrent"],
    "total_current_liabilities": ["LiabilitiesCurrent"],
    "deferred_tax_liability": ["DeferredIncomeTaxLiabilitiesNet", "DeferredTaxLiabilitiesNoncurrent"],
    "total_equity": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"],
    "inventory": ["InventoryNet"],
}


def fill_flows(p: PeriodData, idx: FactIndex, start: date, end: date) -> None:
    get = lambda t: idx.duration(t, start, end)  # noqa: E731

    for field, tags in SIMPLE_FLOWS.items():
        v, s, _ = _first(get, tags)
        setattr(p, field, v)
        if s:
            p.sources[field] = s

    p.revenue, p.sources["revenue"], _ = _first(get, REVENUE)

    v, s, _ = _first(get, ["OperatingIncomeLoss"])
    if v is None and p.revenue is not None:
        costs, cs, _ = _first(get, ["CostsAndExpenses"])
        if costs is not None:
            v, s = p.revenue - costs, ["Derived: revenue minus us-gaap:CostsAndExpenses"] + cs
    p.operating_income, p.sources["operating_income"] = v, s

    v, s, tag = _first(get, DA)
    p.depreciation, p.sources["depreciation"] = v, s
    if tag == "Depreciation":  # amortization reported separately only in this case
        a, asrc, _ = _first(get, ["AmortizationOfIntangibleAssets"])
        p.amortization, p.sources["amortization"] = a, asrc

    gross, gs, _ = _first(get, GROSS_INTEREST)
    if gross is not None:
        cap, cs, _ = _first(get, ["InterestCostsCapitalized"])
        inc, isrc, _ = _first(get, INTEREST_INCOME)
        p.interest_expense = gross - (cap or 0.0) - (inc or 0.0)
        p.gross_interest = gross
        p.sources["interest_expense"] = (
            [f"Net interest = gross {gross:,.0f} - capitalized {cap or 0:,.0f} - interest income {inc or 0:,.0f}"]
            + gs + cs + isrc
            + ([] if cap is not None else ["Capitalized interest not tagged in SEC data; not deducted."]))
    else:
        # Some filers (e.g., Delta) report only net interest: income minus expense.
        net, ns, tag = _first(get, NET_INTEREST)
        if net is not None:
            p.interest_expense = -net
            p.sources["interest_expense"] = [f"Net interest expense = -({tag}); already net of interest income"] + ns
        else:
            # Interest expense in a company-specific tag only: cash interest paid is the closest standard figure.
            paid, ps_, _ = _first(get, ["InterestPaidNet", "InterestPaid"])
            if paid is not None:
                p.interest_expense = paid
                p.gross_interest = paid
                p.sources["interest_expense"] = ["Proxy: cash interest paid (no interest expense line in SEC standard data)"] + ps_

    if p.operating_income is None:
        # No operating-income line (common in pharma/financial-style statements): EBIT = pre-tax income + net interest.
        pre, prs_, _ = _first(get, ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"])
        if pre is not None:
            p.operating_income = pre + (p.interest_expense or 0.0)
            p.sources["operating_income"] = ["Derived: pre-tax income + net interest (no operating income line reported)"] + prs_

    pay, ps, _ = _first(get, CAPEX)
    if pay is not None:
        proceeds, prs, _ = _first(get, ["ProceedsFromSaleOfPropertyPlantAndEquipment", "ProceedsFromSaleOfProductiveAssets"])
        p.capex = -pay + (proceeds or 0.0)
        p.sources["capex"] = ps + prs
        p.capex_gross, p.sources["capex_gross"] = -pay, ps
        if proceeds is not None:
            p.asset_sales, p.sources["asset_sales"] = proceeds, prs
    for field, tags, sign in INVESTING:
        v, s, _ = _first(get, tags)
        if v is not None:
            setattr(p, field, sign * v)
            p.sources[field] = s

    rep, rs, _ = _first(get, REPAY)
    flp, fs, _ = _first(get, ["FinanceLeasePrincipalPayments", "RepaymentsOfLongTermCapitalLeaseObligations"])
    if rep is not None or flp is not None:
        p.debt_repaid = -((rep or 0.0) + (flp or 0.0))
        p.sources["debt_repaid"] = rs + fs
    bb, bs, _ = _first(get, ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"])
    if bb is not None:
        p.buybacks, p.sources["buybacks"] = -bb, bs

    div, ds, _ = _first(get, ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"])
    if div is not None:
        p.dividends, p.sources["dividends"] = -div, ds

    if p.operating_lease_cost is None:
        v, s, _ = _first(get, ["OperatingLeasePayments"])
        if v is not None:
            p.operating_lease_cost = v
            p.sources["operating_lease_cost"] = ["Operating lease cash payments used (lease cost not tagged)"] + s


def fill_balance(p: PeriodData, idx: FactIndex, end: date) -> None:
    get = lambda t: idx.instant(t, end)  # noqa: E731

    for field, tags in SIMPLE_BALANCE.items():
        v, s, _ = _first(get, tags)
        setattr(p, field, v)
        if s:
            p.sources[field] = s

    cash, cs, _ = _first(get, ["CashAndCashEquivalentsAtCarryingValue",
                                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"])
    sti, ss, _ = _first(get, ["ShortTermInvestments", "MarketableSecuritiesCurrent"])
    p.cash = None if cash is None else cash + (sti or 0.0)
    p.sources["cash"] = cs + ss

    tl, ts, _ = _first(get, ["Liabilities"])
    if tl is None:
        tle, s1, _ = _first(get, ["LiabilitiesAndStockholdersEquity"])
        eq, s2, _ = _first(get, ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                                 "StockholdersEquity"])
        if tle is not None and eq is not None:
            tl, ts = tle - eq, ["Derived: total liabilities & equity minus equity"] + s1 + s2
    p.total_liabilities, p.sources["total_liabilities"] = tl, ts

    # Short-term debt: current portion of LTD (+ finance leases if not already combined) + borrowings.
    combined, s, _ = _first(get, ["LongTermDebtAndCapitalLeaseObligationsCurrent"])
    parts: list[str] = []
    if combined is not None:
        std, parts = combined, s
    else:
        cur, s, _ = _first(get, ["LongTermDebtCurrent", "DebtCurrent"])
        fl, fs, _ = _first(get, ["FinanceLeaseLiabilityCurrent"])
        std = None if cur is None and fl is None else (cur or 0.0) + (fl or 0.0)
        parts = s + fs
    for tag in ("ShortTermBorrowings", "CommercialPaper"):
        v, s = get(tag)
        if v is not None:
            std, parts = (std or 0.0) + v, parts + s
    p.st_debt, p.sources["st_debt"] = std, parts

    combined, s, _ = _first(get, ["LongTermDebtAndCapitalLeaseObligations"])
    if combined is not None:
        p.lt_debt, p.sources["lt_debt"] = combined, s
    else:
        nc, s, _ = _first(get, ["LongTermDebtNoncurrent"])
        if nc is None:
            total, s1, _ = _first(get, ["LongTermDebt"])
            cur, s2, _ = _first(get, ["LongTermDebtCurrent"])
            if total is not None:
                nc, s = total - (cur or 0.0), ["Derived: long-term debt minus current portion"] + s1 + s2
        nc2, s3, _ = _first(get, ["LongTermDebtAndFinanceLeasesNoncurrent", "LongTermNotesPayable", "SeniorLongTermNotes",
                                  "LongTermLineOfCredit", "OtherLongTermDebtNoncurrent"]) if nc is None else (None, [], None)
        if nc is None and nc2 is not None:
            nc, s = nc2, s3
        fl, fs, _ = _first(get, ["FinanceLeaseLiabilityNoncurrent"])
        if nc is not None:
            p.lt_debt, p.sources["lt_debt"] = nc + (fl or 0.0), s + fs
        else:
            # No debt tag at all (debt sits in company-specific tags): leases alone are NOT total debt.
            p.lt_debt = None
            p.sources["lt_debt"] = ["Not in SEC standard data (company-specific tags); enter from the 10-K balance sheet"]

    total, s, _ = _first(get, ["OperatingLeaseLiability"])
    if total is None:
        c, s1, _ = _first(get, ["OperatingLeaseLiabilityCurrent"])
        n, s2, _ = _first(get, ["OperatingLeaseLiabilityNoncurrent"])
        if c is not None or n is not None:
            total, s = (c or 0.0) + (n or 0.0), s1 + s2
    p.operating_lease_liabilities, p.sources["operating_lease_liabilities"] = total, s


# --- period discovery ------------------------------------------------------

ANCHORS = ["NetIncomeLoss", "OperatingIncomeLoss"] + REVENUE


def _months(start: date, end: date) -> int:
    return max(1, round(((end - start).days + 1) / 30.44))


def _windows(idx: FactIndex, lo: int, hi: int, forms: Optional[set] = None) -> list[tuple[date, date]]:
    out = set()
    for tag in ANCHORS:
        for (s, e), f in idx.dur.get(tag, {}).items():
            if lo <= (e - s).days <= hi and (forms is None or f.get("form") in forms):
                out.add((s, e))
    return sorted(out, key=lambda w: w[1], reverse=True)


@dataclass
class EdgarSpread:
    company: str
    cik: Optional[int]
    periods: list[PeriodData]   # periods to score
    openings: list[PeriodData]  # balance-sheet-only periods (opening balances)
    notes: list[str]
    debt: dict = field(default_factory=dict)  # maturity ladder, leases, revolver, pension (debt.py)


def build_spread(facts_json: dict, n_years: int = 3, n_quarters: int = 4) -> EdgarSpread:
    idx = FactIndex(facts_json)
    notes: list[str] = []
    annual = _windows(idx, 350, 380, {"10-K", "10-K/A", "10-KT"})
    if not annual:
        raise ValueError("SEC has no full fiscal year of financial data for this filer yet (for example, a newly formed or "
                         "reorganized holding company). Try the predecessor company's ticker or upload its statements.")

    def make(label, kind, start, end) -> PeriodData:
        p = PeriodData(label=label, period_end=end, months=_months(start, end), kind=kind, quality="SEC filing")
        fill_flows(p, idx, start, end)
        fill_balance(p, idx, end)
        p.sources["_window"] = f"{start} to {end}"
        return p

    periods: list[PeriodData] = []
    for s, e in annual[:n_years]:
        periods.append(make(f"FY {e:%Y}", "Annual", s, e))

    fy_start, fy_end = annual[0]
    ytd = [w for w in _windows(idx, 150, 300) if w[0] == fy_end + timedelta(days=1)]
    if ytd:
        ys, ye = ytd[0]
        m = _months(ys, ye)
        periods.append(make(f"{m}M YTD {ye:%b-%Y}", "YTD", ys, ye))
        prior = [w for w in _windows(idx, 150, 300)
                 if w[0] == fy_start and abs((w[1] - ye).days + 365) <= 7]
        if prior:
            ps_, pe_ = prior[0]
            periods.append(make(f"{m}M YTD {pe_:%b-%Y}", "YTD", ps_, pe_))
        else:
            notes.append("Prior-year YTD not found; LTM may fall back to quarters.")

    balance_dates = sorted(idx.inst.get("Assets", {}), reverse=True)
    for i in range(min(n_quarters, len(balance_dates) - 1)):
        end, prev = balance_dates[i], balance_dates[i + 1]
        if 80 <= (end - prev).days <= 100:
            periods.append(make(f"Q {end:%b-%Y}", "Quarter", prev + timedelta(days=1), end))

    # Operating lease cost is often tagged only annually: estimate the gap from the latest fiscal year.
    fy_cost = next(((s, e, v) for s, e in annual
                    for v in [idx.duration("OperatingLeaseCost", s, e)[0] or
                              idx.duration("OperatingLeasePayments", s, e)[0]] if v is not None), None)
    for p in periods:
        if p.operating_lease_cost is None and fy_cost and p.operating_lease_liabilities is not None:
            s, e, v = fy_cost
            p.operating_lease_cost = v * p.months / 12
            p.sources["operating_lease_cost"] = [
                f"Estimate: fiscal {e:%Y} operating lease cost {v:,.0f} x {p.months}/12 (not tagged for this period)"]

    # Opening balance sheets that aren't already period ends.
    have = {p.period_end for p in periods}
    openings = []
    for p in periods:
        start = _d(p.sources["_window"].split(" to ")[0]) - timedelta(days=1)
        if start not in have and start in idx.inst.get("Assets", {}):
            o = PeriodData(label=f"Balance sheet {start:%b-%Y}", period_end=start, months=0, kind="Balance")
            fill_balance(o, idx, start)
            openings.append(o)
            have.add(start)

    from .debt import debt_structure
    return EdgarSpread(idx.entity, idx.cik, periods, openings, notes, debt_structure(idx, facts_json))
