"""SEC EDGAR client: ticker -> CIK -> XBRL company facts, with a disk cache.

Data source: SEC's free XBRL APIs (https://www.sec.gov/edgar/sec-api-documentation).
SEC requires a User-Agent with a contact. The project's contact is built in
(DEFAULT_USER_AGENT); SEC_USER_AGENT in .env overrides it. When SEC can't be
reached, the app falls back to its cache, then to the bundled sample companies.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import REPO_ROOT, load_env

CACHE_DIR = REPO_ROOT / "data" / "cache"
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_MIN_INTERVAL = 0.15  # stay well under SEC's 10 requests/second
_last_call = 0.0


class EdgarError(Exception):
    pass


def normalize_ticker(raw: str) -> str:
    """Validate user input before it goes anywhere near a URL."""
    t = (raw or "").strip().upper()
    if not TICKER_RE.match(t):
        raise EdgarError(f"'{raw}' is not a valid ticker (letters, digits, '.' or '-', up to 10 characters).")
    return t


# SEC asks for a contact in the User-Agent. This project's dedicated contact is the
# default so the app works on any ticker from a fresh clone; SEC_USER_AGENT overrides it.
DEFAULT_USER_AGENT = "Credit-Financial-Analysis-Automation ryanscrivano1@gmail.com"


def _user_agent() -> str:
    load_env()
    return os.environ.get("SEC_USER_AGENT", "").strip() or DEFAULT_USER_AGENT


def _get_json(url: str) -> dict:
    global _last_call
    ua = _user_agent()
    if not ua:
        raise EdgarError("SEC_USER_AGENT is not set, so live SEC data is unavailable.")
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise EdgarError("SEC has no XBRL financial data for this company.") from e
        raise EdgarError(f"SEC request failed (HTTP {e.code}).") from e
    except urllib.error.URLError as e:
        raise EdgarError(f"Could not reach SEC ({e.reason}).") from e
    finally:
        _last_call = time.monotonic()
    return json.loads(data)


def _cached(path: Path, max_age_hours: float):
    if path.is_file() and (time.time() - path.stat().st_mtime) < max_age_hours * 3600:
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def ticker_map() -> tuple[dict[str, tuple[int, str]], str]:
    """{ticker: (cik, company title)} and where it came from."""
    path = CACHE_DIR / "company_tickers.json"
    raw, source = _cached(path, 24 * 7), "cache"
    if raw is None:
        try:
            raw, source = _get_json(TICKERS_URL), "live"
            _write(path, raw)
        except EdgarError:
            raw = _cached(path, float("inf"))
            if raw is None:
                raw = json.loads((SAMPLE_DIR / "company_tickers_sample.json").read_text(encoding="utf-8"))
                source = "sample"
    return {v["ticker"].upper(): (int(v["cik_str"]), v["title"]) for v in raw.values()}, source


def lookup(ticker: str) -> tuple[str, int, str]:
    t = normalize_ticker(ticker)
    m, source = ticker_map()
    if t not in m:
        hint = " (offline sample has LUV and ULCC only)" if source == "sample" else ""
        raise EdgarError(f"Ticker {t} was not found in SEC's company list{hint}.")
    cik, title = m[t]
    return t, cik, title


def submissions(cik: int, max_age_hours: float = 24) -> dict:
    """Company profile + recent filings (SIC code, name, filing list), cached 24h."""
    path = CACHE_DIR / f"submissions_CIK{cik:010d}.json"
    hit = _cached(path, max_age_hours)
    if hit is not None:
        return hit
    try:
        data = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        _write(path, data)
        return data
    except EdgarError:
        stale = _cached(path, float("inf"))
        if stale is not None:
            return stale
        raise


def sector_for_sic(sic) -> str | None:
    """Map an SEC SIC code to a sector key in config/sectors.json."""
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return None
    cfg = json.loads((REPO_ROOT / "credit_engine" / "config" / "sectors.json").read_text(encoding="utf-8"))
    for key, s in cfg["sectors"].items():
        if any(lo <= code <= hi for lo, hi in s["sic"]):
            return key
    return None


def company_facts(cik: int, max_age_hours: float = 24) -> tuple[dict, str]:
    """XBRL company facts JSON and its source: 'live', 'cache', or 'sample'."""
    path = CACHE_DIR / f"CIK{cik:010d}.json"
    hit = _cached(path, max_age_hours)
    if hit is not None:
        return hit, "cache"
    try:
        facts = _get_json(FACTS_URL.format(cik=cik))
        _write(path, facts)
        return facts, "live"
    except EdgarError as live_err:
        stale = _cached(path, float("inf"))
        if stale is not None:
            return stale, "cache"
        sample = SAMPLE_DIR / f"CIK{cik:010d}.json"
        if sample.is_file():
            return json.loads(sample.read_text(encoding="utf-8")), "sample"
        raise live_err
