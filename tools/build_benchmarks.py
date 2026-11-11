"""Build sector health-tier benchmarks from SEC data (run once; output is committed).

    python tools/build_benchmarks.py

1. SEC SIC code list -> SIC codes in each sector's ranges.
2. EDGAR company listing per SIC code -> CIKs in each sector.
3. SEC XBRL "frames" (one value per filer per period) for ~35 tags -> per-company ratios.
4. Percentiles per sector -> data/benchmarks/sector_benchmarks.json
   (p10/p25/p50/p75/p90; Strong = better than p75, Struggling = worse than p25).
5. Verifies each FRED indicator in config/sectors.json and drops ones FRED doesn't return.
No AI involved.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from credit_engine.edgar import CACHE_DIR, _get_json, _user_agent  # noqa: E402

CFG = ROOT / "credit_engine" / "config" / "sectors.json"
OUT = ROOT / "data" / "benchmarks" / "sector_benchmarks.json"
FRAME_DIR = CACHE_DIR / "frames"
YEAR = 2025

DUR = {  # field -> tags (first found per company wins)
    "rev": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "oi": ["OperatingIncomeLoss"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"],
    "int": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "ni": ["NetIncomeLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}
INST = {
    "assets": ["Assets"], "liab": ["Liabilities"], "equity": ["StockholdersEquity"],
    "ca": ["AssetsCurrent"], "cl": ["LiabilitiesCurrent"], "inv": ["InventoryNet"],
    "ar": ["AccountsReceivableNetCurrent"], "ap": ["AccountsPayableCurrent"],
    "ltd_nc": ["LongTermDebtAndCapitalLeaseObligations", "LongTermDebtNoncurrent"],
    "ltd_c": ["LongTermDebtAndCapitalLeaseObligationsCurrent", "LongTermDebtCurrent", "DebtCurrent"],
}
HISTORY = {"rev_prev": ("rev", YEAR - 1), "rev_2019": ("rev", 2019), "rev_2020": ("rev", 2020),
           "oi_2019": ("oi", 2019), "oi_2020": ("oi", 2020)}

# ratio -> direction ("higher" better, "lower" better, "neutral" = only unusual at the extremes)
RATIOS = {"ebitda_margin": "higher", "gross_margin": "higher", "inventory_turnover": "higher", "dso": "lower",
          "dpo": "neutral", "current_ratio": "higher", "debt_to_ebitda": "lower", "ebitda_interest": "higher",
          "ffo_to_debt": "higher", "focf_to_debt": "higher", "debt_to_capital": "lower", "ebit_to_capital": "higher",
          "revenue_growth": "higher", "capex_to_revenue": "neutral"}


def frame(tag: str, period: str) -> dict[int, float]:
    path = FRAME_DIR / f"{tag}_{period}.json"
    if path.is_file():
        data = json.loads(path.read_text())
    else:
        try:
            data = _get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json")
        except Exception:
            data = {"data": []}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    return {d["cik"]: d["val"] / 1e6 for d in data.get("data", [])}


def merged(tags: list[str], period: str) -> dict[int, float]:
    out: dict[int, float] = {}
    for t in tags:
        for cik, v in frame(t, period).items():
            out.setdefault(cik, v)
    return out


def sic_codes() -> list[int]:
    import urllib.request
    req = urllib.request.Request("https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list",
                                 headers={"User-Agent": _user_agent()})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    return sorted({int(c) for c in re.findall(r">\s*(\d{3,4})\s*<", html)})


def ciks_for_sic(sic: int) -> set[int]:
    import urllib.request
    cache = FRAME_DIR / f"sic_{sic}.json"
    if cache.is_file():
        return set(json.loads(cache.read_text()))
    out, start = set(), 0
    while True:
        url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=10-K&dateb=&owner=include"
               f"&count=100&start={start}&output=atom")
        req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
        txt = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        found = {int(c) for c in re.findall(r"<cik>(\d+)</cik>", txt)}
        out |= found
        time.sleep(0.15)
        if len(found) < 100 or start > 2000:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(sorted(out)))
            return out
        start += 100


def pct(vals: list[float]) -> dict:
    v = sorted(vals)
    q = statistics.quantiles(v, n=20, method="inclusive")  # 5% steps
    return {"p10": q[1], "p25": q[4], "p50": q[9], "p75": q[14], "p90": q[17], "n": len(v)}


def company_ratios(d: dict) -> dict:
    g = d.get
    r = {}
    rev = g("rev")
    if not rev or rev <= 0:
        return r
    ebitda = (g("oi") or 0) + (g("da") or 0) if g("oi") is not None and g("da") is not None else None
    debt = (g("ltd_nc") or 0) + (g("ltd_c") or 0) if g("ltd_nc") is not None or g("ltd_c") is not None else None
    if ebitda is not None:
        r["ebitda_margin"] = ebitda / rev
    if g("cogs") and g("cogs") > 0:
        r["gross_margin"] = (rev - g("cogs")) / rev
        if g("inv") and g("inv") > 0:
            r["inventory_turnover"] = g("cogs") / g("inv")
        if g("ap") is not None:
            r["dpo"] = g("ap") / g("cogs") * 365
    if g("ar") is not None:
        r["dso"] = g("ar") / rev * 365
    if g("ca") and g("cl") and g("cl") > 0:
        r["current_ratio"] = g("ca") / g("cl")
    if debt is not None and ebitda and ebitda > 0:
        r["debt_to_ebitda"] = debt / ebitda
    if ebitda is not None and g("int") and g("int") > 0:
        r["ebitda_interest"] = ebitda / g("int")
    if debt and debt > 0:
        if g("ni") is not None and g("da") is not None:
            r["ffo_to_debt"] = (g("ni") + g("da")) / debt
        if g("cfo") is not None and g("capex") is not None:
            r["focf_to_debt"] = (g("cfo") - g("capex")) / debt
        if g("equity") is not None and debt + g("equity") > 0:
            r["debt_to_capital"] = debt / (debt + g("equity"))
            if g("oi") is not None:
                r["ebit_to_capital"] = g("oi") / (debt + g("equity"))
    if g("rev_prev") and g("rev_prev") > 0:
        r["revenue_growth"] = rev / g("rev_prev") - 1
    if g("capex") is not None:
        r["capex_to_revenue"] = g("capex") / rev
    return r


def verify_fred(series: str) -> bool:
    import urllib.request
    try:
        req = urllib.request.Request(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}",
                                     headers={"User-Agent": _user_agent()})
        rows = urllib.request.urlopen(req, timeout=30).read().decode().strip().splitlines()
        return len(rows) > 12 and rows[-1].split(",")[-1] not in ("", ".")
    except Exception:
        return False


def main():
    cfg = json.loads(CFG.read_text())
    print("loading SEC frames ...")
    data: dict[int, dict] = {}
    for f, tags in DUR.items():
        for cik, v in merged(tags, f"CY{YEAR}").items():
            data.setdefault(cik, {})[f] = v
    for f, tags in INST.items():
        for cik, v in merged(tags, f"CY{YEAR}Q4I").items():
            data.setdefault(cik, {})[f] = v
    for f, (base, yr) in HISTORY.items():
        for cik, v in merged(DUR[base], f"CY{yr}").items():
            data.setdefault(cik, {})[f] = v
    names: dict[int, str] = {}
    for tag in DUR["rev"]:
        path = FRAME_DIR / f"{tag}_CY{YEAR}.json"
        if path.is_file():
            for d in json.loads(path.read_text()).get("data", []):
                names.setdefault(d["cik"], d.get("entityName", ""))
    print(f"{len(data)} companies with {YEAR} data")

    codes = sic_codes()
    print(f"{len(codes)} SIC codes")
    out = {"as_of": time.strftime("%Y-%m-%d"), "fiscal_year": YEAR,
           "source": "SEC XBRL frames (all public filers) grouped by SEC SIC code", "sectors": {}}
    for key, s in cfg["sectors"].items():
        ciks = set()
        for lo, hi in s["sic"]:
            for c in codes:
                if lo <= c <= hi:
                    ciks |= ciks_for_sic(c)
        rows = [company_ratios(data[c]) for c in ciks if c in data]
        rows = [r for r in rows if r]
        peers = []
        for c in ciks:
            if c in data and data[c].get("rev", 0) > 0:
                r = company_ratios(data[c])
                peers.append({"cik": c, "name": names.get(c, ""), "revenue": round(data[c]["rev"], 1),
                              **{k: round(v, 4) for k, v in r.items()}})
        peers.sort(key=lambda x: -x["revenue"])
        ratios = {}
        for k in RATIOS:
            vals = [r[k] for r in rows if k in r]
            if len(vals) >= 8:
                ratios[k] = {**pct(vals), "direction": RATIOS[k]}
        rec = [(data[c]["rev_2020"] / data[c]["rev_2019"] - 1) for c in ciks if c in data
               and data[c].get("rev_2019", 0) > 0 and data[c].get("rev_2020") is not None]
        mrg = [(data[c]["oi_2020"] / data[c]["rev_2020"] - data[c]["oi_2019"] / data[c]["rev_2019"]) for c in ciks
               if c in data and data[c].get("rev_2019", 0) > 0 and data[c].get("rev_2020", 0) > 0
               and data[c].get("oi_2019") is not None and data[c].get("oi_2020") is not None]
        scale = [data[c]["rev"] for c in ciks if c in data and data[c].get("rev", 0) > 0]
        fred = {k: v for k, v in s["fred"].items() if verify_fred(v)}
        out["sectors"][key] = {
            "name": s["name"], "companies": len(rows), "ratios": ratios,
            "revenue_scale": pct(scale) if len(scale) >= 8 else None,
            "recession_2020": {"revenue_change_p50": statistics.median(rec) if len(rec) >= 8 else None,
                               "op_margin_change_p50": statistics.median(mrg) if len(mrg) >= 8 else None,
                               "n": len(rec)},
            "fred": fred, "fred_dropped": sorted(set(s["fred"]) - set(fred)), "peers": peers,
        }
        print(f"{s['name']:40} companies={len(rows):4} ratios={len(ratios):2} fred={list(fred)}")
    macro_ok = {k: v for k, v in cfg["macro"].items() if verify_fred(v["id"])}
    out["macro"] = macro_ok
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, "| macro series ok:", list(macro_ok))


if __name__ == "__main__":
    main()
