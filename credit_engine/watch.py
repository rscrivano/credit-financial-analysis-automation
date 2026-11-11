"""Watchlist: remember companies and check SEC for new 10-K / 10-Q filings.

Only when a new filing exists is the company re-scored (code only, no AI tokens), so the check stays light
on SEC's servers. The list itself lives in the analyst's browser.
"""
from __future__ import annotations

from datetime import date

from .edgar import EdgarError, company_facts, lookup, submissions

FORMS = ("10-K", "10-Q")
MAX_WATCH = 25


def latest(cik: int, max_age_hours: float = 1) -> dict:
    r = submissions(cik, max_age_hours=max_age_hours)["filings"]["recent"]
    for i, form in enumerate(r["form"]):
        if form in FORMS:
            return {"form": form, "accession": r["accessionNumber"][i], "filed": r["filingDate"][i]}
    return {}


def entry(r: dict) -> dict:
    """Watchlist entry for an analyzed public company (state as of now)."""
    _, cik, _ = lookup(r["ticker"])
    f = latest(cik, 24)
    return {"ticker": r["ticker"], "company": r["company"], "accession": f.get("accession"), "form": f.get("form"),
            "filed": f.get("filed"), "credit_score": (r.get("credit_score") or {}).get("score"),
            "rating": (r.get("primary") or {}).get("reported", {}).get("rating"),
            "sp_style": (r.get("sp_anchor") or {}).get("final"), "checked": date.today().isoformat(), "status": "Added"}


def check(items: list[dict]) -> list[dict]:
    from . import pipeline
    out = []
    for it in items[:MAX_WATCH]:
        it = dict(it)
        try:
            _, cik, _ = lookup(it["ticker"])
            f = latest(cik)
            if f and f.get("accession") != it.get("accession"):
                company_facts(cik, max_age_hours=0)  # new filing: refresh the XBRL data before re-scoring
                r = pipeline.run(it["ticker"], use_ai=False)
                new = entry(r) | {"accession": f["accession"], "form": f["form"], "filed": f["filed"]}
                moved = []
                for k, name in (("rating", "reported"), ("sp_style", "S&P-style"), ("credit_score", "score")):
                    if new.get(k) != it.get(k):
                        moved.append(f"{name} {it.get(k) or '–'} → {new.get(k) or '–'}")
                new["status"] = f"New {f['form']} filed {f['filed']}" + (": " + "; ".join(moved) if moved else ": no rating change")
                new["changed"] = bool(moved)
                it = new
            else:
                it["status"] = "No new filing"
                it["changed"] = False
        except EdgarError as e:
            it["status"] = f"Couldn't check: {str(e)[:80]}"
        it["checked"] = date.today().isoformat()
        out.append(it)
    return out
