"""Build the bundled offline sample (data/sample/) from cached SEC company facts.

Keeps only the XBRL tags the mapper uses, so the files stay small enough for git.
    python tools/make_sample.py LUV ULCC
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from credit_engine.edgar import CACHE_DIR, SAMPLE_DIR, company_facts, lookup, ticker_map  # noqa: E402

USED_TAGS = {t for f in ("xbrl_map.py", "debt.py") for t in re.findall(r'"([A-Z][A-Za-z]+)"', (ROOT / "credit_engine" / f).read_text(encoding="utf-8"))}


def main(tickers: list[str]) -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    tmap, _ = ticker_map()
    sample_tickers = {}
    for i, t in enumerate(tickers):
        t, cik, title = lookup(t)
        facts, source = company_facts(cik)
        gaap = facts["facts"]["us-gaap"]
        trimmed = dict(facts)
        keep = {}
        for tag, body in gaap.items():
            if tag not in USED_TAGS:
                continue
            usd = [x for x in body.get("units", {}).get("USD", []) if x["end"] >= "2021-12-31"]
            if usd:
                keep[tag] = {"label": body.get("label"), "units": {"USD": usd}}
        trimmed["facts"] = {"us-gaap": keep}
        path = SAMPLE_DIR / f"CIK{cik:010d}.json"
        path.write_text(json.dumps(trimmed), encoding="utf-8")
        sample_tickers[str(i)] = {"cik_str": cik, "ticker": t, "title": title}
        print(f"{t}: {len(trimmed['facts']['us-gaap'])} tags, {path.stat().st_size // 1024} KB (from {source})")
    (SAMPLE_DIR / "company_tickers_sample.json").write_text(json.dumps(sample_tickers), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:] or ["LUV", "ULCC"])
