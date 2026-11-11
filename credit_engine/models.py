"""Data structures for one spread period and its scored results.

All amounts are in the reporting currency's millions, signed the way Ryan's
template expects them:
  * expenses (cogs, sga, interest_expense, tax_expense) are positive numbers
  * capex and dividends are negative (cash outflows)
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date
from typing import Optional

# Income statement and cash flow lines: summed across periods when building LTM.
FLOW_FIELDS = [
    "revenue", "cogs", "sga", "other_opex", "amortization", "depreciation",
    "operating_income", "interest_expense", "tax_expense", "net_income",
    "nonrecurring", "amort_deferred_revenue", "cfo", "capex", "deferred_taxes",
    "other_noncash", "dividends", "operating_lease_cost",
    "cfi", "cff", "debt_issued", "debt_repaid", "buybacks",
    "capex_gross", "asset_sales", "acquisitions", "divestitures", "inv_purchases", "inv_sales", "gross_interest",
]
# Balance sheet lines: taken from the period-end balance sheet.
BALANCE_FIELDS = [
    "total_assets", "cash", "receivables", "total_current_assets", "fixed_assets",
    "goodwill", "other_intangibles", "total_liabilities", "st_debt",
    "accounts_payable", "total_current_liabilities", "deferred_tax_liability",
    "lt_debt", "operating_lease_liabilities", "total_equity", "inventory",
]
# Lines where a blank means zero rather than "we don't know".
ZERO_IF_BLANK = {
    "other_opex", "amortization", "nonrecurring", "amort_deferred_revenue",
    "deferred_taxes", "other_noncash", "dividends", "other_intangibles",
    "goodwill", "deferred_tax_liability", "st_debt", "capex",
    "tax_expense",  # spreads leave tax blank for loss years; net income is still reported
}


@dataclass
class PeriodData:
    """One column of the spread."""

    label: str
    period_end: date
    months: int
    kind: str  # "YTD", "Quarter", "Annual", "LTM"

    revenue: Optional[float] = None
    cogs: Optional[float] = None
    sga: Optional[float] = None
    other_opex: Optional[float] = None
    amortization: Optional[float] = None
    depreciation: Optional[float] = None
    operating_income: Optional[float] = None
    interest_expense: Optional[float] = None  # net of capitalized interest and interest income, as spread
    tax_expense: Optional[float] = None
    net_income: Optional[float] = None
    nonrecurring: Optional[float] = None
    amort_deferred_revenue: Optional[float] = None
    cfo: Optional[float] = None
    capex: Optional[float] = None
    deferred_taxes: Optional[float] = None
    other_noncash: Optional[float] = None
    dividends: Optional[float] = None
    # Investing / financing detail (cash outflows negative)
    cfi: Optional[float] = None          # net cash from investing activities
    cff: Optional[float] = None          # net cash from financing activities
    debt_issued: Optional[float] = None
    debt_repaid: Optional[float] = None  # incl. finance-lease principal payments
    buybacks: Optional[float] = None
    capex_gross: Optional[float] = None    # purchases of PP&E before asset-sale proceeds
    asset_sales: Optional[float] = None    # proceeds from sales of PP&E
    acquisitions: Optional[float] = None
    divestitures: Optional[float] = None
    inv_purchases: Optional[float] = None  # purchases of securities / investments
    inv_sales: Optional[float] = None      # sales and maturities of securities / investments
    gross_interest: Optional[float] = None  # interest expense before interest income (used to sanity-check debt)

    total_assets: Optional[float] = None
    cash: Optional[float] = None
    receivables: Optional[float] = None
    total_current_assets: Optional[float] = None
    fixed_assets: Optional[float] = None
    goodwill: Optional[float] = None
    other_intangibles: Optional[float] = None
    total_liabilities: Optional[float] = None
    st_debt: Optional[float] = None  # CMLTD + other short-term debt
    accounts_payable: Optional[float] = None
    total_current_liabilities: Optional[float] = None
    deferred_tax_liability: Optional[float] = None
    lt_debt: Optional[float] = None

    # Lease inputs for the lease-adjusted basis (not in the original template).
    operating_lease_liabilities: Optional[float] = None  # current + non-current
    operating_lease_cost: Optional[float] = None

    # Reported separately so the balance sheet can be checked (TA = TL + equity).
    total_equity: Optional[float] = None
    inventory: Optional[float] = None
    quality: str = ""  # Audited / Reviewed / Compiled / Management / Quarterly / SEC filing

    fx_avg: float = 1.0
    # field name -> where the number came from (filing, XBRL tag, workbook cell)
    sources: dict = field(default_factory=dict)

    def get(self, name: str) -> Optional[float]:
        """Value with blank-means-zero applied to optional lines."""
        v = getattr(self, name)
        if v is None and name in ZERO_IF_BLANK:
            return 0.0
        return v

    def is_empty(self) -> bool:
        return self.revenue is None and self.total_assets is None


def input_field_names() -> list[str]:
    return [f.name for f in fields(PeriodData) if f.name in FLOW_FIELDS + BALANCE_FIELDS]


# Ratio status values and the user-facing messages Ryan specified.
OK = "ok"
INFINITE = "infinite"
MISSING = "missing"
STATUS_MESSAGE = {INFINITE: "Ratio is Infinite", MISSING: "Data is Missing", OK: ""}


@dataclass
class RatioResult:
    key: str
    name: str
    value: Optional[float]
    status: str  # OK / INFINITE / MISSING
    notch: Optional[str]
    weight: float
    contribution: Optional[float]  # weight * notch number (before re-weighting)
    message: str = ""
    note: str = ""  # extra explanation, e.g. "EBITDA <= 0, scored C"


@dataclass
class EbitdaSection:
    operating_income: Optional[float]
    depreciation_amortization: Optional[float]
    ebitda: Optional[float]
    revenue: Optional[float]
    ebitda_margin: Optional[float]
    operating_lease_cost: Optional[float] = None
    ebitdar: Optional[float] = None  # lease-adjusted EBITDA


@dataclass
class BasisResult:
    basis: str  # "Reported" or "Lease-adjusted"
    ratios: list[RatioResult]
    score: Optional[float]
    rating: Optional[str]
    weight_used: float  # share of scorecard weight that was scored
    message: str = ""
    total_debt: Optional[float] = None
    ebitda: Optional[float] = None


@dataclass
class PeriodResult:
    label: str
    period_end: date
    months: int
    kind: str
    ebitda: EbitdaSection
    reported: BasisResult
    lease_adjusted: BasisResult
