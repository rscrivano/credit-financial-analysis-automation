"""Macro and industry (micro) indicators from FRED, cached daily. No API key needed."""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
from datetime import date, timedelta

from .config import REPO_ROOT
from .edgar import _user_agent

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
CACHE = REPO_ROOT / "data" / "cache" / "fred"
BENCH = REPO_ROOT / "data" / "benchmarks" / "sector_benchmarks.json"


def series(sid: str) -> list[tuple[date, float]]:
    path = CACHE / f"{sid}.csv"
    if path.is_file() and time.time() - path.stat().st_mtime < 86400:
        text = path.read_text()
    else:
        try:
            req = urllib.request.Request(FRED_CSV.format(id=sid), headers={"User-Agent": _user_agent()})
            text = urllib.request.urlopen(req, timeout=30).read().decode()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        except Exception:
            text = path.read_text() if path.is_file() else ""
    out = []
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        try:
            out.append((date.fromisoformat(row[0]), float(row[1])))
        except (ValueError, IndexError):
            continue
    return out


def _at(s, d: date):
    prior = [v for t, v in s if t <= d]
    return prior[-1] if prior else None


def snapshot(sid: str, yoy: bool = False) -> dict:
    """Latest value, value a year earlier, and the change. yoy=True turns an index into % growth."""
    s = series(sid)
    if not s:
        return {"id": sid, "available": False}
    last_d, last_v = s[-1]
    yr = _at(s, last_d - timedelta(days=365))
    if yoy:
        yr2 = _at(s, last_d - timedelta(days=730))
        cur = (last_v / yr - 1) * 100 if yr else None
        prev = (yr / yr2 - 1) * 100 if yr and yr2 else None
        return {"id": sid, "available": True, "as_of": str(last_d), "value": cur, "year_ago": prev,
                "change": None if cur is None or prev is None else cur - prev, "units": "% YoY"}
    return {"id": sid, "available": True, "as_of": str(last_d), "value": last_v, "year_ago": yr,
            "change": None if yr is None else last_v - yr,
            "pct_change": None if not yr else (last_v / yr - 1) * 100}


def benchmarks() -> dict:
    return json.loads(BENCH.read_text(encoding="utf-8")) if BENCH.is_file() else {"sectors": {}, "macro": {}}


def macro_panel() -> list[dict]:
    b = benchmarks()
    return [{"key": k, "label": m["label"], **snapshot(m["id"], m.get("yoy", False))} for k, m in b.get("macro", {}).items()]


INDICATOR_LABELS = {
    "JFUEL": "Jet fuel price, Gulf Coast ($/gal)", "RPM": "Airline revenue passenger miles (thousands)",
    "FREIGHT": "Freight transportation services index", "DIESEL": "Diesel price ($/gal)",
    "RETAIL": "Retail sales ex. food services ($m)", "SENTIMENT": "Consumer sentiment (U. Michigan)",
    "FOODSERV": "Food services & drinking places sales ($m)", "FOODCPI": "Food CPI (index)",
    "WHOLESALE": "Wholesale sales ($m)", "PPI": "Producer price index, all commodities",
    "IP_FOOD": "Industrial production: food, beverage, tobacco", "IP_CHEM": "Industrial production: chemicals",
    "NATGAS": "Henry Hub natural gas ($/MMBtu)", "PPI_PHARMA": "PPI: pharmaceutical preparations",
    "MEDCPI": "Medical care CPI (index)", "IP_MFG": "Industrial production: manufacturing", "CAPUTIL": "Manufacturing capacity utilization (%)",
    "IP_COMP": "Industrial production: computers & electronics", "VEHICLES": "Light vehicle sales (millions, SAAR)",
    "IP_AUTO": "Industrial production: motor vehicles & parts", "IP_METAL": "Industrial production: primary metals",
    "COPPER": "Copper price ($/metric ton)", "WTI": "WTI crude oil ($/bbl)", "IP_UTIL": "Industrial production: utilities",
    "PPI_SOFT": "PPI: software publishers", "IT_INVEST": "Business investment: information processing equipment ($bn)",
    "PROF_EMP": "Professional & technical services employment (thousands)", "UNRATE": "Unemployment rate (%)",
    "HC_EMP": "Health care employment (thousands)", "PPI_HOTEL": "PPI: hotels and motels",
    "CONSTR": "Total construction spending ($m)", "STARTS": "Housing starts (thousands, SAAR)",
    "MORTGAGE": "30-year mortgage rate (%)", "PCE": "Personal consumption expenditures ($bn)",
}


def industry_panel(sector_key: str) -> list[dict]:
    s = benchmarks()["sectors"].get(sector_key, {})
    return [{"key": INDICATOR_LABELS.get(k, k), **snapshot(sid)} for k, sid in s.get("fred", {}).items()]
